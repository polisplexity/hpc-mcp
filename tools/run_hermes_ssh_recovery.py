"""Drop a real submit response and recover the detached R job in another Hermes session."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from hpc_mcp import client, environments, worker
from hpc_mcp.ssh_jobs import REQUEST_LABEL
from tools.run_hermes_r import ENVIRONMENT, MANIFEST
from tools.run_hermes_r_download import FETCH_TOOLS, OUTPUT, fixture, invoke, reference_output
from tools.verify_agent_receipt import exchanges, require


ROOT = Path(__file__).resolve().parents[1]
SUBMIT = "hpc_ssh_submit"
STATUS = "hpc_ssh_status"
FIRST_TOOLS = ["hpc_environment_probe", "hpc_environment_prepare", SUBMIT]
SECOND_TOOLS = [SUBMIT, STATUS, *FETCH_TOOLS]
FIRST_FIELDS = {"request_id", "acknowledged"}
SECOND_FIELDS = {"job_id", "native_id", "reference", "sha256", "size_bytes", "verified"}


@contextmanager
def docker_events(output, job_id):
    # Start an independent native observer before either MCP session opens.
    source = f"""
import subprocess, sys
cmd = ["docker", "--host", "unix:///var/run/docker.sock", "events", "--since", "1m",
       "--filter", "type=container", "--filter", {f"label={REQUEST_LABEL}={job_id}"!r}, "--format", "{{{{json .}}}}"]
p = subprocess.Popen(cmd)
try:
    sys.stdin.buffer.read(1)
finally:
    p.terminate()
    p.wait(timeout=5)
"""
    command = [*client.ssh_python(os.environ[client.SSH_ALIAS])[:-1], shlex.join(["-c", source])]
    with (output / "docker.jsonl").open("wb") as events, (output / "docker.stderr").open("wb") as error:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=error)
        try:
            yield
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
    require(process.returncode == 0, "The Docker event observer did not finish cleanly")


def audit_events(output, job_id):
    audit = []
    for line in (output / "docker.jsonl").read_bytes().splitlines():
        event = json.loads(line)
        actor = event["Actor"]
        require(actor["Attributes"].get(REQUEST_LABEL) == job_id, "Docker event belongs to a different request")
        result = {"request_id": job_id, "native_id": actor["ID"], "event": event["Action"], "time_ns": event["timeNano"]}
        if event["Action"] == "die":
            result["exit_code"] = int(actor["Attributes"]["exitCode"])
        audit.append(result)
    return audit


def verify(output, record, workspace):
    job_id = record["request_id"]
    require(str(UUID(job_id)) == job_id, "Invalid request ID")
    first = exchanges(output / "submit" / "mcp.jsonl", allow_drop=True)
    second = exchanges(output / "recover" / "mcp.jsonl")
    require([name for name, _, _ in first] == FIRST_TOOLS, "Missing first Hermes probe, prepare or submit")
    require(second and second[0][0] == SUBMIT and second[-2][0] == FETCH_TOOLS[0] and second[-1][0] == FETCH_TOOLS[1]
            and second[1:-2] and all(name == STATUS for name, _, _ in second[1:-2]),
            "The recovery session must retry, inspect the original job and download its artifact")
    prepared = first[1][2]
    expected_args = {"environment": ENVIRONMENT, "manifest": MANIFEST, "request_id": job_id,
                     "expected_environment_id": prepared["environment_id"]}
    dropped = first[2][2]["dropped_response"]
    native_id = dropped["native_id"]
    require(first[2][1] == second[0][1] == expected_args and dropped["state"] == "submitted"
            and dropped["job_id"] == job_id and re.fullmatch(r"[a-f0-9]{64}", native_id),
            "The dropped reply did not identify a started Docker job or the request changed")
    require(record["submit_answer"] == {"request_id": job_id, "acknowledged": False}, "The first agent claimed an acknowledgment")
    for name, args, state in second[:-2]:
        require(state["job_id"] == job_id and state["native_id"] == native_id
                and state["manifest_sha256"] == dropped["manifest_sha256"]
                and state["environment_id"] == dropped["environment_id"], "Recovery returned a different native execution")
        if name == STATUS:
            require(args == {"request_id": job_id}, "Status used a different request ID")
    final = second[-3][2]
    receipt = final["receipt"]
    package = client.prepare(workspace, MANIFEST, environments.R_PROFILE)
    client.verify_receipt(receipt, package)
    require(final["native_state"] == "exited" and final["native_exit_code"] == 0 and final["state"] == "succeeded"
            and receipt["native_id"] == native_id and receipt["job_id"] == job_id
            and receipt["status"] == "succeeded" and receipt["exit_code"] == 0,
            "The original execution did not exit successfully")
    artifact, = receipt["artifacts"]
    expected = reference_output()
    sha = expected["sha256"]
    ref = worker.ARTIFACT_REFERENCE + sha
    file_meta = {"sha256": sha, "size_bytes": expected["size_bytes"]}
    require(artifact == {**file_meta, "path": OUTPUT, "reference": ref}, "The R output differs from the reference")
    checked = {**file_meta, "reference": ref, "verified": True}
    require(second[-2][1] == second[-1][1] == {"reference": ref} and second[-2][2] == checked
            and second[-1][2] == {**checked, "filename": sha} and record["downloaded_file"] == file_meta,
            "Recovery did not retrieve the expected file")
    require(record["recover_answer"] == {**checked, "job_id": job_id, "native_id": native_id},
            "The second agent's answer differs from recovered evidence")
    events = record["docker_events"]
    require(all(item["native_id"] == native_id and item["request_id"] == job_id for item in events),
            "Docker observed multiple container identities")
    lifecycle = [item["event"] for item in events if item["event"] in {"create", "start", "die", "destroy", "restart"}]
    require(lifecycle == ["create", "start", "die", "destroy"]
            and [item["exit_code"] for item in events if item["event"] == "die"] == [0],
            "Docker did not observe exactly one create, one start and one successful exit")
    return {"request_id": job_id, "native_id": native_id, "starts": 1, "artifact": artifact}


def run(args, output):
    for key in (client.SSH_ALIAS, environments.ENV_ROOT, environments.DATA_ROOT):
        if not os.getenv(key):
            raise ValueError(f"Configure {key}")
    hermes = shutil.which(args.hermes)
    if not hermes:
        raise ValueError("Specify an available Hermes executable")
    job_id = str(uuid4())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    download = output / "download"
    download.mkdir(mode=0o700)
    launcher = [sys.executable, "-m", "hpc_mcp.server"]
    profile_env = [f"{key}={os.environ[key]}" for key in (client.SSH_ALIAS, environments.ENV_ROOT, environments.DATA_ROOT)]
    with docker_events(output, job_id):
        with TemporaryDirectory(prefix="hpc-submit-") as directory:
            temp = Path(directory)
            workspace = temp / "workspace"
            fixture(workspace)
            backend = ["env", f"PYTHONPATH={ROOT}", f"{client.JOB_ROOT}={workspace}", *profile_env, *launcher]
            model, submitted = invoke(
                hermes, args.hermes_home, output / "submit", temp, backend, FIRST_TOOLS,
                f"Use only HPC MCP. Probe the authorized SSH node and prepare its approved Docker R environment. "
                f"Call hpc_ssh_submit exactly once for job.json with request_id {job_id} and the prepared environment ID. "
                "The connection will close while returning the reply. After an error do not retry. "
                "Return one JSON object with request_id (the supplied string) and acknowledged (boolean indicating whether you received the submit reply).",
                FIRST_FIELDS, trace_options=("--drop-response-to", SUBMIT),
            )
        calls = exchanges(output / "submit" / "mcp.jsonl", allow_drop=True)
        dropped = calls[-1][2]["dropped_response"]
        require(dropped["state"] == "submitted", "The connection was cut without a confirmed Docker start")
        expected_id = calls[1][2]["environment_id"]
        env_name = calls[1][1]["environment"]
        with TemporaryDirectory(prefix="hpc-recover-") as directory:
            temp = Path(directory)
            workspace = temp / "workspace"
            fixture(workspace)
            backend = ["env", f"PYTHONPATH={ROOT}", f"{client.JOB_ROOT}={workspace}", *profile_env,
                       f"{environments.DOWNLOAD_ROOT}={download}", *launcher]
            _, recovered = invoke(
                hermes, args.hermes_home, output / "recover", temp, backend, SECOND_TOOLS,
                f"Use only HPC MCP. The previous client lost its acknowledgment. Retry hpc_ssh_submit once for manifest job.json, "
                f"environment {env_name}, request_id {job_id}, expected_environment_id {expected_id}. "
                "Then call hpc_ssh_status for the same request at least once and until succeeded. "
                "Read the result artifact reference, verify via hpc_verify_artifact, then use hpc_fetch_artifact to download. "
                "Return exactly one JSON object with job_id, native_id, reference, sha256, size_bytes and verified from the actual results.",
                SECOND_FIELDS,
            )
            disk = (download / recovered["sha256"]).read_bytes()
            record = {"request_id": job_id, "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip(),
                "model": model, "submit_answer": submitted, "recover_answer": recovered,
                "downloaded_file": {"size_bytes": len(disk), "sha256": hashlib.sha256(disk).hexdigest()}}
    record["docker_events"] = audit_events(output, job_id)
    with TemporaryDirectory(prefix="hpc-replay-") as directory:
        workspace = Path(directory) / "workspace"
        fixture(workspace)
        result = verify(output, record, workspace)
    record["verified"] = result
    (output / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return result


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
                result = verify(output, record, workspace)
            require(result == record["verified"], "The replay differs from the recorded recovery")
        else:
            result = run(args, output)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
