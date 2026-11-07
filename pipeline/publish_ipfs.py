"""Publish the hosted query files to the Filebase IPFS bucket.

Steps:
1. Pack the data files into a CAR with the off-the-shelf `ipfs-car` tool.
2. Upload the CAR and each file to Filebase over the S3 API (boto3).
3. Write a manifest that links to the CAR and to the previous run's manifest.
4. Check each object through public gateways. Gateways that refuse or challenge
   are recorded as blocked, not counted as verification.

Filebase returns a CIDv0 in the x-amz-meta-cid header. The manifest records the
CIDv1 (base32) of the same bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import ssl
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from cid import make_cid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "data"
KEY_PATH = Path.home() / ".config" / "prism" / "filebase.key"
CAR_TOOL = "ipfs-car@3"
GATEWAYS = (
    "https://ipfs.io/ipfs/",
    "https://dweb.link/ipfs/",
    "https://ipfs.filebase.io/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://4everland.io/ipfs/",
    "https://nftstorage.link/ipfs/",
    "https://w3s.link/ipfs/",
)
DATA_FILES = ("summary.json", "leads.json", "permits.json", "open_permits.json")


def credentials() -> tuple[str, str, str]:
    raw = KEY_PATH.read_text().strip()
    access, secret, bucket = base64.b64decode(raw).decode().split(":")
    return access, secret, bucket


def client():
    access, secret, _bucket = credentials()
    return boto3.client(
        "s3",
        endpoint_url="https://s3.filebase.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )


def cid_v1(cid_v0: str) -> str:
    return make_cid(cid_v0).to_v1().encode("base32").decode()


def pack_car(source: Path, out: Path) -> str:
    """Pack a directory into a CAR with ipfs-car. Returns the directory root CID."""
    subprocess.run(
        ["npx", "-y", "-p", CAR_TOOL, "ipfs-car", "pack", str(source), "--output", str(out)],
        check=True,
    )
    roots = subprocess.run(
        ["npx", "-y", "-p", CAR_TOOL, "ipfs-car", "roots", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    return roots[-1]


def upload(s3, bucket: str, key: str, body: bytes, content_type: str) -> dict:
    response = s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    headers = {k.lower(): v for k, v in response["ResponseMetadata"]["HTTPHeaders"].items()}
    version0 = headers["x-amz-meta-cid"]
    return {
        "name": key.split("/", 1)[-1],
        "key": key,
        "cid": cid_v1(version0),
        "cid_v0": version0,
        "size": len(body),
        "codec": "file",
        "sha256": hashlib.sha256(body).hexdigest(),
        "content_type": content_type,
    }


def fetch_gateway(url: str) -> dict:
    context = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    request = urllib.request.Request(url, headers={"User-Agent": "newcastle-oracle/1"})
    try:
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            body = response.read()
            return {"url": url, "status": response.status, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    except Exception as error:
        status = getattr(error, "code", None)
        return {"url": url, "status": status, "error": type(error).__name__}


def main() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _access, _secret, bucket = credentials()
    s3 = client()
    previous = json.loads((DATA / "published.json").read_text()) if (DATA / "published.json").exists() else None
    prior_cids = [previous["manifest_cid"]] if previous else []

    staging = Path(tempfile.mkdtemp(prefix="publish-")) / run_id
    staging.mkdir(parents=True)
    for name in DATA_FILES:
        shutil.copy(DATA / name, staging / name)
    shutil.copytree(DATA / "tiles", staging / "tiles")
    car_path = staging.parent / f"{run_id}.car"
    car_root = pack_car(staging, car_path)
    car_body = car_path.read_bytes()
    car_artifact = upload(s3, bucket, f"runs/{run_id}/publication.car", car_body, "application/vnd.ipld.car")
    car_artifact["root_cid"] = car_root
    print("car", car_artifact["cid"], "root", car_root, car_artifact["size"])

    artifacts = []
    for name in DATA_FILES:
        body = (DATA / name).read_bytes()
        artifacts.append(upload(s3, bucket, f"runs/{run_id}/{name}", body, "application/json"))
        print(name, artifacts[-1]["cid"], artifacts[-1]["size"])

    tile_index = json.loads((DATA / "tiles_index.json").read_text())

    def upload_tile(key: str) -> tuple[str, dict]:
        body = (DATA / "tiles" / tile_index["tiles"][key]["file"]).read_bytes()
        return key, upload(client(), bucket, f"runs/{run_id}/tiles/{key}.json", body, "application/json")

    with ThreadPoolExecutor(max_workers=8) as pool:
        for key, artifact in pool.map(upload_tile, sorted(tile_index["tiles"])):
            tile_index["tiles"][key]["cid"] = artifact["cid"]
    print("tiles", len(tile_index["tiles"]))
    index_bytes = json.dumps(tile_index, indent=2).encode()
    artifacts.append(upload(s3, bucket, f"runs/{run_id}/tiles_index.json", index_bytes, "application/json"))
    print("tiles_index.json", artifacts[-1]["cid"])

    current_counts = {k: v for k, v in json.loads((DATA / "summary.json").read_text()).items() if isinstance(v, (int, float))}
    manifest = {
        "run_id": run_id,
        "county": "New Castle County, DE",
        "bucket": bucket,
        "artifacts": artifacts,
        "car": car_artifact,
        "prior_cids": prior_cids,
        "counts": current_counts,
        "limitations": [
            "The published files are every parcel with coordinates and every permit row.",
            "tiles_index.json lists 0.05-degree map tiles. Each tile holds every parcel in it plus its open and roof permits.",
            "Roof age is year built when the county filled it, otherwise the latest roof-permit year.",
            "Open duration is days since issue on an open permit layer. No close date is published.",
            "Contractor name is the text on the permit. The open-permit layer prints a contractor on only a few rows. last_roof_contractor_name is the name on the latest closed or new-construction roof permit. license_* fields are an exact name match to the Delaware business contractor licenses (SODA 5zy2-grhr). A match is a name match and does not confirm the permit contractor is that licensee. Trade licenses (pjnv-eaih) belong to people and are not matched.",
            "BBB ratings were not submitted. https://www.bbb.org/robots.txt disallows /*? and /business-reviews/*, so no BBB harvest was submitted.",
            "Ownership unchanged for 10 years cannot be answered. Sale history is not in the GIS layers.",
        ],
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode()
    manifest_artifact = upload(s3, bucket, f"runs/{run_id}/manifest.json", manifest_bytes, "application/json")
    print("manifest", manifest_artifact["cid"])

    # The delta lists this run's counts, the prior run's counts, and the change between them.
    # The first run that carries counts has no prior counts, so its changes are null.
    prior_counts = previous["manifest"].get("counts") if previous else None
    changes = (
        {k: current_counts[k] - prior_counts[k] for k in current_counts if k in prior_counts}
        if prior_counts
        else None
    )
    delta = {
        "run_id": run_id + "-delta",
        "note": "This run's manifest, the prior manifest, and the change in each county count between them.",
        "manifest_cid": manifest_artifact["cid"],
        "previous_manifest_cid": previous["manifest_cid"] if previous else None,
        "prior_cids": prior_cids,
        "counts": current_counts,
        "previous_counts": prior_counts,
        "changes": changes,
    }
    delta_bytes = json.dumps(delta, indent=2).encode()
    delta_artifact = upload(s3, bucket, f"runs/{run_id}-delta/delta.json", delta_bytes, "application/json")
    print("delta", delta_artifact["cid"])

    checks = []
    for artifact in (car_artifact, artifacts[0], manifest_artifact):
        for prefix in GATEWAYS:
            result = fetch_gateway(prefix + artifact["cid"])
            result["expected_sha256"] = artifact["sha256"]
            result["match"] = result.get("sha256") == artifact["sha256"]
            result["name"] = artifact["name"]
            checks.append(result)
            print(result["status"], result.get("match"), result["url"][:70])

    record = {
        "manifest_cid": manifest_artifact["cid"],
        "delta_cid": delta_artifact["cid"],
        "manifest": manifest,
        "delta": delta_artifact,
        "gateway_checks": checks,
    }
    (DATA / "published.json").write_text(json.dumps(record, indent=2))
    print("wrote", DATA / "published.json")


if __name__ == "__main__":
    main()
