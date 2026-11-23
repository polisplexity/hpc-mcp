"""Run the same bounded fixture locally and through an authorized SSH profile."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import time


FIXTURE = Path(__file__).with_name("cpu_fixture.py")
EXPECTED_LIMIT = 100_000


def validate_result(result):
    n = EXPECTED_LIMIT
    expected = {"limit": n, "sum_of_squares": n * (n + 1) * (2 * n + 1) // 6}
    if result != expected:
        raise ValueError("Fixture output differs from the independent closed-form reference")


def run_cpu_fixture(target, ssh_profile=None):
    if target == "local":
        command = [sys.executable, "-I", "-B", "-"]
    elif target == "cimat" and ssh_profile and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", ssh_profile):
        command = [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", ssh_profile, "python3", "-I", "-B", "-",
        ]
    else:
        raise ValueError("Choose local or configure an approved SSH alias for CIMAT")

    source = FIXTURE.read_bytes()
    start = time.monotonic()
    result = subprocess.run(command, input=source, capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f"Fixture process exited with status {result.returncode}")
    output = json.loads(result.stdout)
    validate_result(output)
    return {
        "target": target,
        "fixture_sha256": sha256(source).hexdigest(),
        "output_sha256": sha256(result.stdout).hexdigest(),
        "result": output,
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-profile", help="Existing approved SSH alias, kept outside the repository")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    receipts = [run_cpu_fixture("local")]
    if args.ssh_profile:
        receipts.append(run_cpu_fixture("cimat", args.ssh_profile))
        if receipts[0]["output_sha256"] != receipts[1]["output_sha256"]:
            raise ValueError("Native local and CIMAT outputs differ at the byte level")
    report = json.dumps({"scope": "native fixed CPU fixture", "runs": receipts}, indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")


if __name__ == "__main__":
    main()
