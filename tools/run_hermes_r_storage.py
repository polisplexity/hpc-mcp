"""Seed, run and verify the SSH-resident R dataset and artifact acceptance case."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from hpc_mcp import client, environments, worker
from tools.run_hermes_copper_sweep import make_profile
from tools.run_hermes_r import CASE, ENVIRONMENT, MANIFEST, OUTPUT, fixture as r_fixture, reference
from tools.run_hermes_environment import TOOLS as ENVIRONMENT_TOOLS
from tools.verify_agent_receipt import claims_with_fields, exchanges, require


ROOT = Path(__file__).resolve().parents[1]
DATASET = "orders-large.csv"
REPEATS = 8192
TOOLS = [*ENVIRONMENT_TOOLS, "hpc_verify_artifact"]
CLAIMS = {"reference", "sha256", "size_bytes", "verified"}


def dataset():
    header, rows = (CASE / "orders.csv").read_text(encoding="ascii").split("\n", 1)
    prefix = (header + "\n").encode("ascii")
    records = rows.encode("ascii")
    checksum = hashlib.sha256(prefix)
    for _ in range(REPEATS):
        checksum.update(records)
    return {"path": "orders.csv", "source": DATASET,
            "size_bytes": len(prefix) + REPEATS * len(records), "sha256": checksum.hexdigest()}, prefix, records


def fixture(workspace):
    r_fixture(workspace)
    manifest = workspace / MANIFEST
    job = json.loads(manifest.read_bytes())
    job["inputs"][1] = dataset()[0]
    job["output_mode"] = "reference"
    manifest.write_bytes(worker.canonical(job))
    (workspace / "orders.csv").unlink()


def remote_call(source, *arguments):
    root = os.getenv(environments.DATA_ROOT)
    if not root:
        raise ValueError(f"Configure {environments.DATA_ROOT}")
    command = client.ssh_python(os.getenv(client.SSH_ALIAS))
    launch = f"\nmain({root!r}, {arguments!r})\n"
    response = subprocess.run(command, input=source + launch, text=True, capture_output=True, check=True, timeout=25)
    return json.loads(response.stdout)


def seed():
    meta, header, rows = dataset()
    source = r"""
import hashlib, json, os
from pathlib import Path

def main(root_value, args):
    name, header, rows, repeats = args
    root = Path(root_value)
    if not root.is_absolute() or root.resolve() != root or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError("Use a private account directory")
    folder = root / "datasets"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink():
        raise ValueError("Use a regular dataset directory")
    path = folder / name
    with path.open("xb") as stream:
        stream.write(header)
        for _ in range(repeats):
            stream.write(rows)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
"""
    observed = remote_call(source, DATASET, header, rows, REPEATS)
    require(observed == {key: meta[key] for key in ("size_bytes", "sha256")}, "Seeded node CSV differs from the fixture")
    return {**observed, "source": DATASET}


def audit(verified):
    source = r"""
import csv, hashlib, json
from pathlib import Path

def main(root_value, args):
    name, checksum = args
    root = Path(root_value)
    table = root / "datasets" / name
    regions = {}
    count = 0
    with table.open(newline="", encoding="ascii") as stream:
        for row in csv.DictReader(stream):
            region = regions.setdefault(row["region"], {"units": 0, "revenue_cents": 0})
            units = int(row["units"])
            region["units"] += units
            region["revenue_cents"] += units * int(row["unit_price_cents"])
            count += 1
    payload = (root / "objects" / checksum).read_bytes()
    saved = json.loads(payload)
    independent = {"rows": count, "regions": regions,
                   "total_revenue_cents": sum(item["revenue_cents"] for item in regions.values())}
    assert all(saved[k] == v for k, v in independent.items())
    print(json.dumps({"rows": count, "summary": saved,
                      "input_size_bytes": table.stat().st_size, "input_sha256": hashlib.sha256(table.read_bytes()).hexdigest(),
                      "input_mtime_epoch": table.stat().st_mtime,
                      "output_size_bytes": len(payload), "output_sha256": hashlib.sha256(payload).hexdigest()}))
"""
    return remote_call(source, DATASET, verified["artifact"]["sha256"])


def check_audit(observed, verified):
    version = verified["r_version"]
    small = reference(CASE, version)
    expected = {"r_version": version, "rows": small["rows"] * REPEATS,
                "total_revenue_cents": small["total_revenue_cents"] * REPEATS,
                "regions": {name: {key: value * REPEATS for key, value in values.items()}
                            for name, values in small["regions"].items()}}
    require(observed["summary"] == expected and observed["rows"] == expected["rows"],
            "Stored R output differs from the independent dataset totals")
    require(observed["input_size_bytes"] == verified["input"]["size_bytes"]
            and observed["input_sha256"] == verified["input"]["sha256"]
            and observed["input_mtime_epoch"] < datetime.fromisoformat(verified["started_at"]).timestamp(),
            "The matching node dataset must predate the R job")
    require(observed["output_size_bytes"] == verified["artifact"]["size_bytes"]
            and observed["output_sha256"] == verified["artifact"]["sha256"], "The saved file differs from its reference")


def verify(trace, claims, workspace):
    calls = exchanges(trace)
    names = [name for name, _, _ in calls]
    require(names == TOOLS, "Expected the agent to probe, prepare, run and verify")
    probe, prepared, batch, checked = [reply for _, _, reply in calls]
    lock = environments.environment_lock(workspace, ENVIRONMENT)
    require(probe["target"] == "ssh"
            and any(item.get("approved_image") == lock["image"] for item in probe["approved_environments"]),
            "The agent did not discover the approved environment")
    environment_id = prepared["environment_id"]
    require(calls[1][1] == {"environment": ENVIRONMENT} and calls[2][1] == {
        "environment": ENVIRONMENT, "manifests": [MANIFEST], "expected_environment_id": environment_id,
    } and batch["environment_id"] == environment_id, "The agent ran a different environment or manifest")
    require(prepared["r_version"] == lock["r_version"] and prepared["route"] == batch["route"],
            "The job runtime differed from the approved environment")
    result, = batch["results"]
    receipt = result["receipt"]
    package = client.prepare(workspace, MANIFEST, environments.R_PROFILE)
    expected_input = dataset()[0]
    require(set(package["files"]) == {"summarize.R"} and expected_input["size_bytes"] > worker.MAX_FILE_BYTES,
            "The job uploaded the dataset or used an undersized fixture")
    client.verify_receipt(receipt, package)
    require(receipt["status"] == "succeeded" and receipt["exit_code"] == 0
            and result["remote_inputs"] == [expected_input] and result["json_outputs"] == {},
            "The job did not complete with the pinned dataset and reference-only output")
    artifact, = receipt["artifacts"]
    supplied = {key: artifact[key] for key in ("reference", "size_bytes", "sha256")}
    require(artifact["path"] == OUTPUT and calls[3][1] == {"reference": supplied["reference"]}
            and checked == claims == {**supplied, "verified": True}, "The reference was not verified through MCP")
    return {"tool_calls": names, "input": expected_input, "script_sha256": worker.digest((CASE / "summarize.R").read_bytes()),
            "artifact": artifact, "route": batch["route"], "r_version": receipt["runtime_version"],
            "native_id": receipt["native_id"], "started_at": receipt["started_at"]}


def run(args, workspace):
    for key in (client.SSH_ALIAS, environments.ENV_ROOT, environments.DATA_ROOT):
        if not os.getenv(key):
            raise ValueError(f"Configure {key}")
    hermes = shutil.which(args.hermes)
    if not hermes:
        raise ValueError("Specify an available Hermes executable")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    backend = ["env", f"PYTHONPATH={ROOT}", f"{client.JOB_ROOT}={workspace}",
               *(f"{key}={os.environ[key]}" for key in (client.SSH_ALIAS, environments.ENV_ROOT, environments.DATA_ROOT)),
               sys.executable, "-m", "hpc_mcp.server"]
    profile = workspace.parent / "profile"
    model = make_profile(profile, args.hermes_home, output, backend, tools=TOOLS, tool_timeout=260)
    prompt = (
        "Use only HPC MCP to run job.json with its approved R environment on CIMAT. The CSV already resides on the node. "
        "Call hpc_environment_probe, then hpc_environment_prepare for the approved R environment discovered. "
        "Call hpc_environment_run_batch with manifests [\"job.json\"] and its expected_environment_id. "
        "Read the resulting summary.json artifact reference from the receipt. "
        "Call hpc_verify_artifact with that exact reference. Return one JSON object with reference, sha256, size_bytes, "
        "and verified using the observed verification. If any step fails, report the observed error."
    )
    with (output / "agent.txt").open("wb") as answer, (output / "hermes.stderr").open("wb") as error:
        subprocess.run(
            [hermes, "chat", "--ignore-rules", "--quiet", "--max-turns", "14", "--source", "tool",
             "--toolsets", "polisplexity_hpc", "--query", prompt], cwd=workspace.parent,
            env={**os.environ, "HERMES_HOME": str(profile)}, stdin=subprocess.DEVNULL,
            stdout=answer, stderr=error, check=True, timeout=360,
        )
    claims = claims_with_fields(output / "agent.txt", CLAIMS)
    checked = verify(output / "mcp.jsonl", claims, workspace)
    observed = audit(checked)
    check_audit(observed, checked)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    version = subprocess.check_output([hermes, "--version"], text=True, timeout=20).splitlines()[0].split(" · ")[0]
    record = {"source_revision": revision, "hermes": version, "model": model, "agent_answer": claims,
              "verified": checked, "native_audit": observed}
    (output / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--seed-dataset", action="store_true")
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", type=Path, default=Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")))
    args = parser.parse_args()
    try:
        if args.seed_dataset:
            print(json.dumps(seed(), indent=2))
            return
        if args.output is None:
            parser.error("Supply --output for running or verifying the acceptance case")
        with TemporaryDirectory(prefix="hpc-hermes-r-storage-") as temporary:
            workspace = Path(temporary) / "workspace"
            fixture(workspace)
            if args.verify_only:
                record = json.loads((args.output / "record.json").read_bytes())
                checked = verify(args.output / "mcp.jsonl", record["agent_answer"], workspace)
                require(checked == record["verified"], "Verification differs from the saved record")
                check_audit(record["native_audit"], checked)
            else:
                checked = run(args, workspace)
        print(json.dumps(checked, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
