"""Pin the published small files to a second provider (Pinata) and record the result.

The bytes come from the primary provider (Filebase), are checked against the sha256
in the manifest, and are then pinned to Pinata. A pin counts only if Pinata returns
the same CID that was published. The result is written to web/data/published.json
under "second_pins". Credential: ~/.config/prism/pinata.jwt (mode 600), never printed.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "web" / "data" / "published.json"
JWT_PATH = Path(os.path.expanduser("~/.config/prism/pinata.jwt"))
PIN_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
SOURCE = "https://ipfs.filebase.io/ipfs/{cid}"
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 4
# python.org builds of Python on macOS may not ship CA roots; use the system bundle.
CA_BUNDLE = "/etc/ssl/cert.pem"
SSL_CONTEXT = ssl.create_default_context(cafile=CA_BUNDLE) if os.path.exists(CA_BUNDLE) else ssl.create_default_context()


def fetch_bytes(cid: str) -> bytes:
    delay = 2
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(SOURCE.format(cid=cid), timeout=60, context=SSL_CONTEXT) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS or attempt == ATTEMPTS:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == ATTEMPTS:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


def readback_digest(cid: str) -> str | None:
    """Fetch the pinned CID from the Pinata gateway and return the sha256 of the bytes."""
    try:
        request = urllib.request.Request(f"https://gateway.pinata.cloud/ipfs/{cid}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60, context=SSL_CONTEXT) as response:
            return hashlib.sha256(response.read()).hexdigest()
    except (urllib.error.URLError, TimeoutError):
        return None


def pin_file(name: str, data: bytes, jwt: str) -> dict:
    boundary = uuid.uuid4().hex
    options = json.dumps({"cidVersion": 1}).encode()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode(),
        b"Content-Type: application/json\r\n\r\n",
        data,
        f"\r\n--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="pinataOptions"\r\n\r\n',
        options,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    delay = 2
    for attempt in range(1, ATTEMPTS + 1):
        request = urllib.request.Request(
            PIN_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS or attempt == ATTEMPTS:
                return {"error": f"HTTP {error.code}"}
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == ATTEMPTS:
                return {"error": type(error).__name__}
        time.sleep(delay)
        delay *= 2
    return {"error": "unreachable"}


def main() -> None:
    record = json.loads(PUBLISHED.read_text())
    jwt = JWT_PATH.read_text().strip()
    summary = next(a for a in record["manifest"]["artifacts"] if a["name"].endswith("summary.json"))
    # The manifest's sha256 is recorded on its gateway checks, not in the artifact list.
    manifest_sha = next(
        (c["expected_sha256"] for c in record.get("gateway_checks", [])
         if c["name"].endswith("manifest.json") and c.get("expected_sha256")),
        None,
    )
    manifest_artifact = {
        "name": record["manifest"]["run_id"] + "/manifest.json",
        "cid": record["manifest_cid"],
        "sha256": manifest_sha,
    }
    targets = [summary, manifest_artifact]

    results = []
    for artifact in targets:
        data = fetch_bytes(artifact["cid"])
        digest = hashlib.sha256(data).hexdigest()
        expected = artifact.get("sha256")
        if expected and digest != expected:
            results.append({"name": artifact["name"], "cid": artifact["cid"], "error": "source sha256 mismatch"})
            continue
        short = artifact["name"].split("/")[-1]
        pinned = pin_file(short, data, jwt)
        returned = pinned.get("IpfsHash")
        readback = readback_digest(returned) if returned else None
        results.append({
            "provider": "pinata",
            "name": artifact["name"],
            "cid": artifact["cid"],
            "sha256": digest,
            "pinned": bool(returned),
            "returned_cid": returned,
            "cid_match": returned == artifact["cid"],
            "readback_sha256": readback,
            "readback_match": readback == digest,
            "error": pinned.get("error"),
        })
        print(short, "pinned" if returned else "failed", "readback-match" if readback == digest else "readback-mismatch", pinned.get("error", ""))

    record["second_pins"] = results
    PUBLISHED.write_text(json.dumps(record, indent=2))
    print("wrote second_pins to", PUBLISHED)


if __name__ == "__main__":
    main()
