"""Prepare and run portable jobs through a local subprocess or an SSH profile."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from . import worker


SSH_ALIAS = "POLISPLEXITY_HPC_SSH_PROFILE"
JOB_ROOT = "POLISPLEXITY_HPC_JOB_ROOT"


def prepare(root, manifest_path, profile):
    if profile not in worker.PROFILES:
        raise ValueError("Unknown execution profile")
    root = root.resolve(strict=True)
    manifest_file = worker.checked_path(manifest_path)
    manifest = json.loads(worker.read_file(root, manifest_path))
    return prepare_manifest(root / manifest_file.parent, manifest, profile)


def prepare_manifest(directory, manifest, profile):
    worker.validate_manifest(manifest, profile)
    files = {}
    for item in manifest["inputs"]:
        data = worker.read_file(directory, item["path"])
        if worker.digest(data) != item["sha256"]:
            raise ValueError(f"Input hash mismatch: {item['path']}")
        files[item["path"]] = base64.b64encode(data).decode("ascii")
    return {"profile": profile, "manifest": manifest, "files": files}


def describe(package):
    manifest = package["manifest"]
    return {
        "version": worker.JOB_VERSION,
        "profile": package["profile"],
        "manifest_sha256": worker.digest(worker.canonical(manifest)),
        "resources": manifest["resources"],
        "outputs": manifest["outputs"],
    }


def verify_receipt(receipt, package):
    prepared = describe(package)
    if receipt["version"] != worker.RESULT_VERSION or any(
        receipt[field] != prepared[field] for field in ("manifest_sha256", "resources", "profile")
    ):
        raise RuntimeError("Worker receipt does not identify the prepared job")
    available = [item["path"] for item in receipt["artifacts"]]
    available += receipt["unavailable_outputs"]
    if sorted(available) != sorted(prepared["outputs"]):
        raise RuntimeError("Worker receipt does not cover the declared outputs")
    for item in receipt["artifacts"] + list(receipt["logs"].values()):
        if item is None:
            continue
        data = base64.b64decode(item["base64"], validate=True)
        if len(data) != item["size_bytes"] or worker.digest(data) != item["sha256"]:
            raise RuntimeError("Worker receipt contains an invalid artifact or log digest")


def run(package, ssh_alias=None):
    profile = package["profile"]
    if profile == "local":
        command = [sys.executable, "-I", "-B", "-"]
    elif profile == "ssh" and ssh_alias and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", ssh_alias):
        command = [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", ssh_alias, "python3", "-I", "-B", "-",
        ]
    else:
        raise ValueError("Choose local or configure an approved SSH alias for the SSH profile")

    source = Path(worker.__file__).read_bytes()
    request = worker.canonical(package).decode("ascii")
    launcher = source + f"\ndispatch({request!r})\n".encode("ascii")
    try:
        result = subprocess.run(
            command, input=launcher, capture_output=True, check=True,
            timeout=package["manifest"]["resources"]["wall_time_seconds"] + 25,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("The worker returned no verified receipt. Execution state is unknown.") from None
    try:
        envelope = json.loads(result.stdout)
        if "error" in envelope:
            raise RuntimeError(envelope["error"])
        receipt = envelope["receipt"]
        verify_receipt(receipt, package)
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("The worker returned an invalid receipt. Execution state is unknown.") from None
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--profile", choices=("local", "ssh"), default="local")
    args = parser.parse_args()
    try:
        package = prepare(args.root, args.manifest, args.profile)
        receipt = describe(package) if args.action == "prepare" else run(package, os.getenv(SSH_ALIAS))
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(receipt, indent=2))
    if args.action == "run" and receipt["status"] != "succeeded":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
