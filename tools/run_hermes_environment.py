"""Exercise and verify the managed SSH environment workflow with Hermes."""

import argparse
import base64
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

from hpc_mcp import client, environments, worker
from tools.run_hermes_copper_sweep import make_profile
from tools.verify_agent_receipt import claims_with_fields, exchanges, require


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/ssh-environment"
TOOLS = ["hpc_environment_probe", "hpc_environment_prepare", "hpc_environment_run_batch"]
MANIFESTS = [f"orders-{index}/job.json" for index in (1, 2, 3)]
CLAIMS = {"installation_id", "installed", "reused", "partitions"}


def fixture(workspace):
    (workspace / "environments").mkdir(parents=True)
    shutil.copyfile(CASE / "duckdb.json", workspace / "environments/duckdb.json")
    for index, name in enumerate(MANIFESTS, start=1):
        manifest = workspace / name
        folder = manifest.parent
        folder.mkdir()
        shutil.copyfile(CASE / "aggregate.py", folder / "aggregate.py")
        values = (str((row * index * 17) % 97 + 1) for row in range(index * 1000))
        (folder / "orders.csv").write_bytes(("units\n" + "\n".join(values) + "\n").encode("ascii"))
        manifest.write_bytes(worker.canonical({
            "version": worker.JOB_VERSION, "runtime": "python3", "entrypoint": "aggregate.py", "argv": [],
            "inputs": [{"path": file, "sha256": worker.digest((folder / file).read_bytes())}
                       for file in ("aggregate.py", "orders.csv")],
            "outputs": ["summary.json"], "resources": {"cpus": 1, "memory_mib": 128, "wall_time_seconds": 15},
        }))


def expected(workspace, manifest):
    with (workspace / manifest).with_name("orders.csv").open(newline="", encoding="ascii") as stream:
        values = [int(row["units"]) for row in csv.DictReader(stream)]
    return {"rows": len(values), "total_units": sum(values), "max_units": max(values), "duckdb": "1.4.5"}


def verify(trace, claims, workspace):
    calls = exchanges(trace)
    names = [name for name, _, _ in calls]
    require(names == [TOOLS[0], TOOLS[1], TOOLS[2], TOOLS[1], TOOLS[2]],
            "Expected probe, prepare, run, re-prepare, and repeat")
    probe, install, first, reuse, second = [reply for _, _, reply in calls]
    package = {"duckdb": "1.4.5"}
    require(probe["target"] == "ssh" and probe["private_environment_root_ready"]
            and probe["venv_module"] and "python3" in probe["commands_on_path"]
            and {"name": "duckdb", "packages": package, "state": "needs_preparation"}
            in probe["approved_environments"], "The agent did not start from an unprepared SSH environment")
    install_id = install["installation_id"]
    require(str(UUID(install_id)) == install_id, "Missing installation identity")
    require(install["status"] == "installed" and reuse == {**install, "status": "reused"}
            and install["packages"] == package and install["name"] == "duckdb",
            "Repeat did not reuse the verified installation")
    require(all(args == {"environment": "duckdb"} for _, args, _ in (calls[1], calls[3])),
            "Unexpected environment selection")
    require(all(args == {"environment": "duckdb", "manifests": MANIFESTS} for _, args, _ in (calls[2], calls[4])),
            "Unexpected batch arguments")
    batches = []
    job_ids = set()
    for batch in (first, second):
        require(batch["installation_id"] == install_id and batch["environment_id"] == install["environment_id"]
                and batch["parallel_jobs"] == 1 and batch["name"] == "duckdb", "Batch environment mismatch")
        rows = []
        for manifest, job in zip(MANIFESTS, batch["receipts"], strict=True):
            client.verify_receipt(job, client.prepare(workspace, manifest, "ssh"))
            require(job["manifest"] == manifest and job["status"] == "succeeded" and job["exit_code"] == 0
                    and job["native_id"].isdecimal() and job["job_id"] not in job_ids,
                    "An SSH job failed or its receipt was repeated")
            job_ids.add(job["job_id"])
            artifact, = job["artifacts"]
            value = expected(workspace, manifest)
            require(json.loads(base64.b64decode(artifact["base64"])) == value
                    and job["json_outputs"] == {"summary.json": value},
                    "The retrieved artifact disagrees with the independent CSV calculation")
            rows.append({"manifest": manifest, "total_units": value["total_units"], "sha256": artifact["sha256"]})
        batches.append(rows)
    require(batches[0] == batches[1], "The repeated batch changed the verified result")
    require(claims == {"installation_id": install_id, "installed": True, "reused": True, "partitions": batches[0]},
            "The agent answer differs from the verified results")
    return {"tool_calls": names, "installation_id": install_id, "jobs": len(job_ids),
            "partition_results": batches[0]}


def prompt():
    return (
        "Validate the approved DuckDB batch using only the Polisplexity HPC MCP tools. "
        "Call hpc_environment_probe to check that environment 'duckdb' needs preparation. "
        "Call hpc_environment_prepare with environment duckdb; confirm its status is installed. "
        "Then call hpc_environment_run_batch for duckdb with these three manifests in this order: "
        + ", ".join(MANIFESTS) + ". Read each summary.json in json_outputs and the artifact sha256. "
        "Call hpc_environment_prepare for duckdb again; confirm reused and the same installation_id. "
        "Repeat the same hpc_environment_run_batch and confirm the three results match. "
        "Return exactly one JSON object with keys installation_id, installed, reused, partitions. "
        "Use boolean installed and reused, and a list of three partitions with keys manifest, total_units, sha256. "
        "Use values from the actual tool responses. If anything fails, report the failure."
    )


def run(args):
    if not os.getenv(client.SSH_ALIAS) or not os.getenv(environments.ENV_ROOT):
        raise ValueError(f"Configure {client.SSH_ALIAS} and {environments.ENV_ROOT}")
    hermes = shutil.which(args.hermes)
    if not hermes:
        raise ValueError("Hermes is not on PATH. Supply its executable with --hermes.")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    version = subprocess.check_output([hermes, "--version"], text=True, timeout=20).splitlines()[0]
    with TemporaryDirectory(prefix="hpc-hermes-environment-") as temporary:
        temp = Path(temporary)
        workspace = temp / "workspace"
        fixture(workspace)
        backend = ["env", f"PYTHONPATH={ROOT}", f"{client.JOB_ROOT}={workspace}",
                   f"{client.SSH_ALIAS}={os.environ[client.SSH_ALIAS]}",
                   f"{environments.ENV_ROOT}={os.environ[environments.ENV_ROOT]}",
                   sys.executable, "-m", "hpc_mcp.server"]
        profile = temp / "profile"
        model = make_profile(profile, args.hermes_home, output, backend, tools=TOOLS, tool_timeout=135)
        env = {**os.environ, "HERMES_HOME": str(profile)}
        with (output / "agent.txt").open("wb") as answer, (output / "hermes.stderr").open("wb") as error:
            subprocess.run(
                [hermes, "chat", "--ignore-rules", "--quiet", "--max-turns", "16", "--source", "tool",
                 "--toolsets", "polisplexity_hpc", "--query", prompt()],
                cwd=temp, env=env, stdin=subprocess.DEVNULL, stdout=answer, stderr=error,
                check=True, timeout=300,
            )
        claims = claims_with_fields(output / "agent.txt", CLAIMS)
        verification = verify(output / "mcp.jsonl", claims, workspace)
    record = {"source_revision": revision, "hermes": version.split(" · ")[0],
              "model": model, "agent_answer": claims, "verified": verification}
    (output / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record["verified"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New directory for evidence, or an existing run to verify")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", type=Path, default=Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")))
    args = parser.parse_args()
    try:
        if args.verify_only:
            record = json.loads((args.output / "record.json").read_bytes())
            with TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                fixture(workspace)
                result = verify(args.output / "mcp.jsonl", record["agent_answer"], workspace)
            require(result == record["verified"], "Verification differs from the recorded result")
        else:
            result = run(args)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
