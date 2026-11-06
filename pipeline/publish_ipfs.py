"""Publish the hosted query files to the Filebase IPFS bucket.

Filebase returns a CIDv0. The manifest records the CIDv1 (base32) of the
same bytes. A second tiny object is published afterward so the first CID
stays immutable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from cid import make_cid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "data"
KEY_PATH = Path.home() / ".config" / "prism" / "filebase.key"
GATEWAYS = (
    "https://ipfs.io/ipfs/",
    "https://dweb.link/ipfs/",
    "https://ipfs.filebase.io/ipfs/",
    "https://nftstorage.link/ipfs/",
    "https://w3s.link/ipfs/",
)


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


def upload(s3, bucket: str, key: str, body: bytes, content_type: str) -> dict:
    response = s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    headers = {k.lower(): v for k, v in response["ResponseMetadata"]["HTTPHeaders"].items()}
    version0 = headers["x-amz-meta-cid"]
    digest = hashlib.sha256(body).hexdigest()
    return {
        "name": key.split("/", 1)[-1],
        "key": key,
        "cid": cid_v1(version0),
        "cid_v0": version0,
        "size": len(body),
        "codec": "file",
        "sha256": digest,
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
    artifacts = []
    files = [
        ("summary.json", "application/json"),
        ("leads.json", "application/json"),
        ("permits.json", "application/json"),
    ]
    for name, content_type in files:
        body = (DATA / name).read_bytes()
        artifacts.append(upload(s3, bucket, f"runs/{run_id}/{name}", body, content_type))
        print(name, artifacts[-1]["cid"], artifacts[-1]["size"])

    manifest = {
        "run_id": run_id,
        "county": "New Castle County, DE",
        "bucket": bucket,
        "artifacts": artifacts,
        "prior_cids": [],
        "limitations": [
            "Roof age is year built when the county filled it, otherwise the latest roof-permit year.",
            "Open duration is days since issue on an open permit layer. No close date is published.",
            "Contractor name is the text on the permit, not a Delaware license match.",
            "BBB ratings are not loaded.",
            "Ownership unchanged for 10 years cannot be answered. Sale history is not in the GIS layers.",
        ],
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode()
    manifest_artifact = upload(s3, bucket, f"runs/{run_id}/manifest.json", manifest_bytes, "application/json")
    print("manifest", manifest_artifact["cid"])

    # A second object, published after the first manifest, so the first CID is unchanged.
    delta = {
        "run_id": run_id + "-delta",
        "note": "Second publish. The prior manifest CID is unchanged. The county pipeline's second ingest assembled 0 parcels.",
        "prior_manifest_cid": manifest_artifact["cid"],
    }
    delta_bytes = json.dumps(delta, indent=2).encode()
    delta_artifact = upload(s3, bucket, f"runs/{run_id}-delta/delta.json", delta_bytes, "application/json")
    print("delta", delta_artifact["cid"])

    checks = []
    for artifact in (artifacts[0], manifest_artifact):
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
