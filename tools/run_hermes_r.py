"""Run and verify the Hermes R acceptance case on an authorized SSH account."""

import argparse
import base64
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from hpc_mcp import client, environments, worker
from tools.run_hermes_copper_sweep import make_profile
from tools.run_hermes_environment import TOOLS
from tools.verify_agent_receipt import claims_with_fields, exchanges, require


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/ssh-r-environment"
ENVIRONMENT = "rocker-r"
MANIFEST = "job.json"
OUTPUT = "summary.json"
CLAIMS = {"route", "environment_id", "r_version", "total_revenue_cents", "artifact_sha256", "reused"}


def fixture(workspace):
    (workspace / "environments").mkdir(parents=True)
    shutil.copyfile(CASE / f"{ENVIRONMENT}.json", workspace / f"environments/{ENVIRONMENT}.json")
    names = ("summarize.R", "orders.csv")
    for name in names:
        shutil.copyfile(CASE / name, workspace / name)
    (workspace / MANIFEST).write_bytes(worker.canonical({
        "version": worker.JOB_VERSION, "runtime": "rscript", "entrypoint": names[0],
        "argv": [names[1], OUTPUT], "outputs": [OUTPUT],
        "inputs": [{"path": name, "sha256": worker.digest((workspace / name).read_bytes())} for name in names],
        "resources": {"cpus": 1, "memory_mib": 512, "wall_time_seconds": 15},
    }))


def reference(workspace, version):
    with (workspace / "orders.csv").open(newline="", encoding="ascii") as stream:
        data = list(csv.DictReader(stream))
    regions = {}
    for row in data:
        region = regions.setdefault(row["region"], {"units": 0, "revenue_cents": 0})
        units = int(row["units"])
        region["units"] += units
        region["revenue_cents"] += units * int(row["unit_price_cents"])
    return {"r_version": version, "rows": len(data), "regions": regions,
            "total_revenue_cents": sum(region["revenue_cents"] for region in regions.values())}


def verify(trace, claims, workspace):
    calls = exchanges(trace)
    names = [name for name, _, _ in calls]
    require(names == [TOOLS[0], TOOLS[1], TOOLS[2], TOOLS[1], TOOLS[2]],
            "Expected a probe and two prepare-and-run sequences")
    probe, prepared, first, reused, second = [reply for _, _, reply in calls]
    lock = environments.environment_lock(workspace, ENVIRONMENT)
    runtime, = [item for item in probe["approved_environments"] if item["name"] == ENVIRONMENT]
    require(probe["target"] == "ssh" and probe["private_environment_root_ready"]
            and runtime["runtime"] == "rscript" and runtime["approved_image"] == lock["image"],
            "The agent did not discover the approved R runtime over SSH")
    route = "native" if runtime["native_compatible"] else "docker"
    status = "pulled" if route == "docker" and not runtime["image_cached"] else "reused"
    environment_id = prepared["environment_id"]
    require(re.fullmatch(r"[a-f0-9]{64}", environment_id) and prepared["route"] == route
            and prepared["r_version"] == lock["r_version"] and prepared["status"] == status
            and reused == {**prepared, "status": "reused"}, "R environment selection or reuse did not match the probe")
    if route == "docker":
        require(prepared["image"] == lock["image"] and re.fullmatch(r"sha256:[a-f0-9]{64}", prepared["image_id"]),
                "The approved image identity was not observed")
    require(all(args == {"environment": ENVIRONMENT} for _, args, _ in (calls[1], calls[3])),
            "Unexpected R preparation arguments")
    require(all(args == {"environment": ENVIRONMENT, "manifests": [MANIFEST],
                         "expected_environment_id": environment_id} for _, args, _ in (calls[2], calls[4])),
            "The agent did not bind both jobs to the prepared environment")
    package = client.prepare(workspace, MANIFEST, environments.R_PROFILE)
    expected = reference(workspace, lock["r_version"])
    native_ids = []
    hashes = []
    for batch in (first, second):
        require({key: batch[key] for key in reused} == reused and batch["parallel_jobs"] == 1,
                "A job started with a different R environment")
        result, = batch["results"]
        receipt = result["receipt"]
        client.verify_receipt(receipt, package)
        require(result["manifest"] == MANIFEST and receipt["status"] == "succeeded" and receipt["exit_code"] == 0
                and receipt["runtime_version"] == expected["r_version"], "The R job failed")
        native_pattern = r"[a-f0-9]{64}" if route == "docker" else r"[1-9][0-9]*"
        require(re.fullmatch(native_pattern, receipt["native_id"]), "Missing native job identity")
        native_ids.append(receipt["native_id"])
        artifact, = receipt["artifacts"]
        require(json.loads(base64.b64decode(artifact["base64"], validate=True)) == expected
                and result["json_outputs"] == {OUTPUT: expected}, "The returned result differs from the reference")
        hashes.append(artifact["sha256"])
    require(hashes[0] == hashes[1] and len(set(native_ids)) == 2, "The repeat did not return a new run with identical output")
    require(claims == {"route": route, "environment_id": environment_id, "r_version": lock["r_version"],
                       "total_revenue_cents": expected["total_revenue_cents"], "artifact_sha256": hashes[0],
                       "reused": True}, "Agent answer differs from independently verified results")
    return {"tool_calls": names, "route": route, "initial_status": status, "environment_id": environment_id,
            "native_ids": native_ids, "image_id": prepared.get("image_id"), "artifact_sha256": hashes[0],
            "summary": expected}


def prompt():
    return (
        "Run the supplied R job job.json on the approved SSH target using only Polisplexity HPC MCP tools. "
        "Call hpc_environment_probe, read whether a compatible native Rscript exists and identify the approved R environment. "
        "Call hpc_environment_prepare for the approved environment. It will use compatible native R or the pinned Docker image. "
        "Call hpc_environment_run_batch for that environment with manifests [\"job.json\"] and expected_environment_id from prepare. "
        "Read the summary.json from json_outputs and the corresponding artifact sha256. "
        "Call prepare again for the same environment, verify reuse and run the job again with the same environment ID. "
        "Return exactly one JSON object with keys route, environment_id, r_version, total_revenue_cents, artifact_sha256, reused. "
        "Use the integer total and the observed runtime and hash. Report any failure with the observed evidence."
    )


def run(args, workspace):
    if not all(os.getenv(key) for key in (client.SSH_ALIAS, environments.ENV_ROOT)):
        raise ValueError(f"Set {client.SSH_ALIAS} and {environments.ENV_ROOT}")
    hermes = shutil.which(args.hermes)
    if not hermes:
        raise ValueError("Specify an available Hermes executable")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    version = subprocess.check_output([hermes, "--version"], text=True, timeout=20).splitlines()[0].split(" · ")[0]
    profile = workspace.parent / "profile"
    backend = ["env", f"PYTHONPATH={ROOT}", f"{client.JOB_ROOT}={workspace}",
               f"{client.SSH_ALIAS}={os.environ[client.SSH_ALIAS]}",
               f"{environments.ENV_ROOT}={os.environ[environments.ENV_ROOT]}",
               sys.executable, "-m", "hpc_mcp.server"]
    model = make_profile(profile, args.hermes_home, output, backend, tools=TOOLS, tool_timeout=260)
    with (output / "agent.txt").open("wb") as answer, (output / "hermes.stderr").open("wb") as error:
        subprocess.run(
            [hermes, "chat", "--ignore-rules", "--quiet", "--max-turns", "16", "--source", "tool",
             "--toolsets", "polisplexity_hpc", "--query", prompt()], cwd=workspace.parent,
            env={**os.environ, "HERMES_HOME": str(profile)}, stdin=subprocess.DEVNULL,
            stdout=answer, stderr=error, check=True, timeout=420,
        )
    claims = claims_with_fields(output / "agent.txt", CLAIMS)
    verified = verify(output / "mcp.jsonl", claims, workspace)
    record = {"source_revision": revision, "hermes": version, "model": model,
              "agent_answer": claims, "verified": verified}
    (output / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", type=Path, default=Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")))
    args = parser.parse_args()
    try:
        with TemporaryDirectory(prefix="hpc-hermes-r-") as temporary:
            workspace = Path(temporary) / "workspace"
            fixture(workspace)
            if args.verify_only:
                record = json.loads((args.output / "record.json").read_bytes())
                verified = verify(args.output / "mcp.jsonl", record["agent_answer"], workspace)
                require(verified == record["verified"], "Verification differs from the recorded result")
            else:
                verified = run(args, workspace)
        print(json.dumps(verified, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
