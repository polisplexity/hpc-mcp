"""Verify that two fresh Hermes sessions can save and fetch a large R artifact."""

import argparse
import csv
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
from tools.run_hermes_r import CASE, ENVIRONMENT, MANIFEST
from tools.run_hermes_environment import TOOLS as SAVE_TOOLS
from tools.run_hermes_r_storage import REPEATS, dataset, fixture as storage_fixture
from tools.verify_agent_receipt import claims_with_fields, exchanges, require


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "enrich-orders.R"
OUTPUT = "orders-with-revenue.csv"
FETCH_TOOLS = ["hpc_verify_artifact", "hpc_fetch_artifact"]
SAVE_FIELDS = {"reference", "sha256", "size_bytes"}
FETCH_FIELDS = SAVE_FIELDS | {"filename", "verified"}


def fixture(workspace):
    storage_fixture(workspace)
    path = workspace / MANIFEST
    job = json.loads(path.read_bytes())
    script = (CASE / SCRIPT).read_bytes()
    (workspace / SCRIPT).write_bytes(script)
    (workspace / "summarize.R").unlink()
    job.update(entrypoint=SCRIPT, argv=["orders.csv", OUTPUT], outputs=[OUTPUT])
    job["inputs"][0] = {"path": SCRIPT, "sha256": worker.digest(script)}
    path.write_bytes(worker.canonical(job))


def reference_output():
    header = b"region,units,unit_price_cents,revenue_cents\n"
    with (CASE / "orders.csv").open(newline="", encoding="ascii") as stream:
        rows = list(csv.DictReader(stream))
    lines = "".join(f'{row["region"]},{row["units"]},{row["unit_price_cents"]},'
                    f'{int(row["units"]) * int(row["unit_price_cents"])}\n' for row in rows).encode("ascii")
    checksum = hashlib.sha256(header)
    for _ in range(REPEATS):
        checksum.update(lines)
    return {"rows": len(rows) * REPEATS, "size_bytes": len(header) + len(lines) * REPEATS,
            "sha256": checksum.hexdigest()}


def verify(output, saved_claims, fetched_claims, workspace):
    save = exchanges(output / "save" / "mcp.jsonl")
    fetch = exchanges(output / "fetch" / "mcp.jsonl")
    require([name for name, _, _ in save] == SAVE_TOOLS and [name for name, _, _ in fetch] == FETCH_TOOLS,
            "Expected independent save and fetch tool sequences")
    probe, prepared, batch = [reply for _, _, reply in save]
    lock = environments.environment_lock(workspace, ENVIRONMENT)
    require(probe["target"] == "ssh"
            and any(item.get("approved_image") == lock["image"] for item in probe["approved_environments"]),
            "The agent did not inspect the authorized R environment")
    require(save[1][1] == {"environment": ENVIRONMENT} and save[2][1] == {
        "environment": ENVIRONMENT, "expected_environment_id": prepared["environment_id"], "manifests": [MANIFEST],
    } and batch["environment_id"] == prepared["environment_id"], "The agent selected a different environment")
    result, = batch["results"]
    receipt = result["receipt"]
    package = client.prepare(workspace, MANIFEST, environments.R_PROFILE)
    client.verify_receipt(receipt, package)
    require(receipt["status"] == "succeeded" and receipt["exit_code"] == 0
            and receipt["runtime_version"] == lock["r_version"] and result["manifest"] == MANIFEST
            and result["remote_inputs"] == [dataset()[0]] and not result["json_outputs"],
            "R did not complete the reference-only job on the node dataset")
    artifact, = receipt["artifacts"]
    expected = reference_output()
    require(expected["size_bytes"] > worker.MAX_FILE_BYTES and artifact == {
        "path": OUTPUT, "size_bytes": expected["size_bytes"], "sha256": expected["sha256"],
        "reference": worker.ARTIFACT_REFERENCE + expected["sha256"],
    }, "The stored artifact differs from the independently generated CSV")
    require(saved_claims == {key: artifact[key] for key in SAVE_FIELDS}, "The save claim differs from its receipt")
    require(all(args == {"reference": artifact["reference"]} for _, args, _ in fetch),
            "The second session used a different reference")
    checked, downloaded = [reply for _, _, reply in fetch]
    require(checked == {**saved_claims, "verified": True}
            and downloaded == fetched_claims == {**checked, "filename": expected["sha256"]},
            "The second session did not verify and retrieve the saved artifact")
    return {"artifact": artifact, "filename": downloaded["filename"], "rows": expected["rows"],
            "native_id": receipt["native_id"], "r_version": receipt["runtime_version"], "route": batch["route"]}


def invoke(hermes, source, output, temp, backend, tools, prompt, fields):
    output.mkdir(mode=0o700)
    profile = temp / "profile"
    model = make_profile(profile, source, output, backend, tools=tools, tool_timeout=260)
    with (output / "agent.txt").open("wb") as answer, (output / "hermes.stderr").open("wb") as error:
        subprocess.run(
            [hermes, "chat", "--ignore-rules", "--quiet", "--max-turns", "14", "--source", "tool",
             "--toolsets", "polisplexity_hpc", "--query", prompt],
            cwd=temp, env={**os.environ, "HERMES_HOME": str(profile)}, stdin=subprocess.DEVNULL,
            stdout=answer, stderr=error, check=True, timeout=360,
        )
    return model, claims_with_fields(output / "agent.txt", fields)


def run(args, output):
    for key in (client.SSH_ALIAS, environments.ENV_ROOT, environments.DATA_ROOT):
        if not os.getenv(key):
            raise ValueError(f"Configure {key}")
    hermes = shutil.which(args.hermes)
    if not hermes:
        raise ValueError("Specify an available Hermes executable")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    download = output / "download"
    download.mkdir(mode=0o700)
    backend = [f"PYTHONPATH={ROOT}", *(f"{key}={os.environ[key]}" for key in (client.SSH_ALIAS, environments.DATA_ROOT))]
    launch = [sys.executable, "-m", "hpc_mcp.server"]
    with TemporaryDirectory(prefix="hpc-hermes-save-") as directory:
        temp = Path(directory)
        workspace = temp / "workspace"
        fixture(workspace)
        save_backend = ["env", *backend, f"{client.JOB_ROOT}={workspace}",
                        f"{environments.ENV_ROOT}={os.environ[environments.ENV_ROOT]}", *launch]
        model, saved = invoke(
            hermes, args.hermes_home, output / "save", temp, save_backend, SAVE_TOOLS,
            'Use only HPC MCP. Probe the approved SSH target, prepare its R environment, and run job.json '
            'with manifests ["job.json"] and the expected_environment_id from prepare. From the successful '
            'receipt return one JSON object with reference, sha256, and size_bytes for orders-with-revenue.csv.',
            SAVE_FIELDS,
        )
    require(saved["size_bytes"] > worker.MAX_FILE_BYTES, "The save session did not produce a large artifact")
    with TemporaryDirectory(prefix="hpc-hermes-fetch-") as directory:
        temp = Path(directory)
        fetch_backend = ["env", "-u", client.JOB_ROOT, "-u", environments.ENV_ROOT, *backend,
                         f"{environments.DOWNLOAD_ROOT}={download}", *launch]
        _, fetched = invoke(
            hermes, args.hermes_home, output / "fetch", temp, fetch_backend, FETCH_TOOLS,
            f'Use only HPC MCP to recover the actual artifact {saved["reference"]} from the SSH target. '
            'First call hpc_verify_artifact, then call hpc_fetch_artifact with that exact reference to save it '
            'in the client download directory. Return one JSON object with reference, sha256, size_bytes, '
            'filename, and boolean verified from the tool result.',
            FETCH_FIELDS,
        )
    with TemporaryDirectory(prefix="hpc-hermes-verify-") as directory:
        workspace = Path(directory) / "workspace"
        fixture(workspace)
        details = verify(output, saved, fetched, workspace)
    recovered = (download / details["filename"]).read_bytes()
    disk = {"size_bytes": len(recovered), "sha256": hashlib.sha256(recovered).hexdigest()}
    require(disk == {key: details["artifact"][key] for key in disk}, "The recovered file bytes differ from the source")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    version = subprocess.check_output([hermes, "--version"], text=True, timeout=20).splitlines()[0].split(" · ")[0]
    record = {"source_revision": revision, "hermes": version, "model": model, "save_answer": saved,
              "fetch_answer": fetched, "verified": details, "downloaded_file": disk}
    (output / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", type=Path, default=Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")))
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if args.verify_only:
            record = json.loads((output / "record.json").read_bytes())
            with TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                fixture(workspace)
                details = verify(output, record["save_answer"], record["fetch_answer"], workspace)
            require(details == record["verified"] and record["downloaded_file"] == {
                key: details["artifact"][key] for key in ("size_bytes", "sha256")
            }, "The public record differs from the verified traces")
        else:
            details = run(args, output)
        print(json.dumps(details, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
