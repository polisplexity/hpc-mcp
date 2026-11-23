"""Compare the portable job against a native reference and actual MCP calls."""

import argparse
import asyncio
import base64
from hashlib import sha256
import json
from math import isqrt
import os
from pathlib import Path
from random import Random
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hpc_mcp.client import JOB_ROOT, SSH_ALIAS


REPO = Path(__file__).resolve().parents[1]
CASE = REPO / "cases" / "portable-python"


def load(path):
    return json.loads(path.read_bytes())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def schema(name):
    document = load(REPO / "schemas" / (name + "-v1.json"))
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document, format_checker=Draft202012Validator.FORMAT_CHECKER)


def reference(directory):
    parameters = load(directory / "parameters.json")
    rng = Random(parameters["seed"])
    expected = []
    for _ in range(parameters["windows"]):
        start = rng.randrange(2, parameters["max_start"] + 1)
        count = sum(
            all(value % divisor for divisor in range(2, isqrt(value) + 1))
            for value in range(start, start + parameters["width"])
        )
        expected.append({"count": count, "start": start})
    output = directory / "native.json"
    subprocess.run(
        [sys.executable, "-I", "-B", "program.py", "parameters.json", output.name],
        cwd=directory, check=True, timeout=10,
    )
    observed = output.read_bytes()
    check(json.loads(observed) == {"windows": expected}, "Native sieve differs from trial division")
    return observed


def write_manifest(directory, name, manifest):
    (directory / name).write_text(json.dumps(manifest), encoding="utf-8")


def alternate(directory):
    source = b"""import json
from pathlib import Path
from statistics import pvariance
from sys import argv

values = json.loads(Path(argv[1]).read_text())
Path(argv[2]).write_bytes(f"{pvariance(values)}\\n".encode())
"""
    samples = b"[2, 4, 6, 8]\n"
    (directory / "another.py").write_bytes(source)
    (directory / "sample.json").write_bytes(samples)
    write_manifest(directory, "another.json", {
        **load(directory / "job.json"),
        "entrypoint": "another.py",
        "argv": ["sample.json", "variance.txt"],
        "inputs": [
            {"path": "another.py", "sha256": sha256(source).hexdigest()},
            {"path": "sample.json", "sha256": sha256(samples).hexdigest()},
        ],
        "outputs": ["variance.txt"],
    })


def timeout_case(directory, manifest):
    source = b"from time import sleep\nsleep(3)\n"
    (directory / "sleep.py").write_bytes(source)
    write_manifest(directory, "timeout.json", {
        **manifest,
        "entrypoint": "sleep.py",
        "argv": [],
        "inputs": [{"path": "sleep.py", "sha256": sha256(source).hexdigest()}],
        "resources": {**manifest["resources"], "wall_time_seconds": 1},
    })


async def call(session, tool, name, profile, reject=False):
    result = await session.call_tool(tool, {"manifest": name, "profile": profile})
    check(bool(result.isError) == reject, f"Unexpected MCP outcome for {tool} {name} ({profile})")
    if reject:
        return
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def verified_artifact(receipt, reference_bytes):
    [item] = receipt["artifacts"]
    check(base64.b64decode(item["base64"], validate=True) == reference_bytes, "Artifact bytes differ")
    check(item["sha256"] == sha256(reference_bytes).hexdigest(), "Artifact SHA-256 differs")


async def compare(directory, ssh_alias):
    manifest = load(directory / "job.json")
    schema("job").validate(manifest)
    receipt_schema = schema("result")
    native = reference(directory)
    for variant, mode in (("fail.json", "fail"), ("skip.json", "skip")):
        write_manifest(directory, variant, {**manifest, "argv": [*manifest["argv"], "--mode", mode]})
    write_manifest(directory, "changed.json", {
        **manifest, "inputs": [manifest["inputs"][0], {"path": "parameters.json", "sha256": "0" * 64}],
    })
    write_manifest(directory, "over-budget.json", {
        **manifest, "resources": {**manifest["resources"], "cpus": 5},
    })
    write_manifest(directory, "over-ssh-budget.json", {
        **manifest, "resources": {**manifest["resources"], "cpus": 2},
    })
    alternate(directory)
    timeout_case(directory, manifest)
    env = {**os.environ, JOB_ROOT: str(directory)}
    env.pop(SSH_ALIAS, None)
    if ssh_alias:
        env[SSH_ALIAS] = ssh_alias
    config = StdioServerParameters(command=sys.executable, args=["-m", "hpc_mcp.server"], env=env)
    report = {
        "transport": "stdio",
        "reference": {"method": "native program verified by trial division", "output": json.loads(native)},
        "runs": [],
    }
    async with stdio_client(config) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            check(names == {"hpc_prepare", "hpc_run"}, "Unexpected MCP tools")
            for profile in ("local", "ssh") if ssh_alias else ("local",):
                direct = subprocess.run(
                    [sys.executable, "-m", "hpc_mcp.client", "run", "--root", str(directory),
                     "--manifest", "job.json", "--profile", profile],
                    check=True, capture_output=True, env=env, timeout=45,
                )
                direct_receipt = json.loads(direct.stdout)
                receipt_schema.validate(direct_receipt)
                verified_artifact(direct_receipt, native)
                preflight = await call(session, "hpc_prepare", "job.json", profile)
                accepted = await call(session, "hpc_run", "job.json", profile)
                receipt_schema.validate(accepted)
                verified_artifact(accepted, native)
                check(
                    preflight["manifest_sha256"] == accepted["manifest_sha256"] == direct_receipt["manifest_sha256"],
                    "Preflight, CLI and MCP identified different jobs",
                )
                for result in (accepted, direct_receipt):
                    check(result["status"] == "succeeded" and result["exit_code"] == 0, "Successful job failed")
                negative = {}
                for name, status, code in (("fail.json", "failed", 7), ("skip.json", "missing_outputs", 0)):
                    failed = await call(session, "hpc_run", name, profile)
                    receipt_schema.validate(failed)
                    check(failed["status"] == status and failed["exit_code"] == code, "Native outcome was lost")
                    check(failed["unavailable_outputs"] == ["result.json"], "Missing output was misclassified")
                    negative[status] = failed
                timed_out = await call(session, "hpc_run", "timeout.json", profile)
                receipt_schema.validate(timed_out)
                check(timed_out["status"] == "timed_out" and timed_out["exit_code"] == -9, "Timeout was lost")
                negative["timed_out"] = timed_out
                rejected = ["changed.json", "over-budget.json", "../job.json"]
                if profile == "ssh":
                    rejected.append("over-ssh-budget.json")
                for name in rejected:
                    await call(session, "hpc_run", name, profile, reject=True)
                fresh = await call(session, "hpc_run", "another.json", profile)
                receipt_schema.validate(fresh)
                check(fresh["status"] == "succeeded" and fresh["exit_code"] == 0, "New entrypoint failed")
                verified_artifact(fresh, b"5\n")
                report["runs"].append({
                    "profile": profile, "cli": direct_receipt, "mcp": accepted,
                    "negative": negative, "pre_launch_rejections": rejected, "new_entrypoint": fresh,
                })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-profile", help="Approved local SSH alias")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="hpc-contract-check-") as workspace:
        directory = Path(workspace)
        for name in ("program.py", "parameters.json", "job.json"):
            shutil.copyfile(CASE / name, directory / name)
        report = json.dumps(asyncio.run(compare(directory, args.ssh_profile)), indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")


if __name__ == "__main__":
    main()
