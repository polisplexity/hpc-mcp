"""Compare native Slurm and MCP runs on an authorized development allocation."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
from tempfile import TemporaryDirectory
import time
from uuid import UUID, uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from hpc_mcp.client import JOB_ROOT
from hpc_mcp.slurm import SlurmProfile, native, observed
from tools.check_portable_job import CASE, check, load, reference, schema, verified_artifact, write_manifest


FAULT_SERVER = """
import os
from hpc_mcp import server, slurm
original = slurm.native

def interrupt(command, **kwargs):
    if command[0] != "sbatch" or "--parsable" not in command:
        return original(command, **kwargs)
    if os.environ["HPC_TEST_INTERRUPT"] == "before_send":
        os._exit(86)
    response = original(command, **kwargs)
    os._exit(86 if response.returncode == 0 else 87)

slurm.native = interrupt
server.server.run()
"""
SILOGEN_REVISION = "a50091fd99cd71b5aae22b4c07c9b286766f2207"


@asynccontextmanager
async def connect(directory, interruption=None):
    env = {**os.environ, JOB_ROOT: str(directory)}
    args = ["-m", "hpc_mcp.server"]
    if interruption:
        args = ["-c", FAULT_SERVER]
        env["HPC_TEST_INTERRUPT"] = interruption
    config = StdioServerParameters(command=sys.executable, args=args, env=env)
    async with stdio_client(config) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


async def call(session, tool, arguments=None):
    result = await session.call_tool(tool, arguments or {})
    if result.isError:
        raise RuntimeError(f"{tool} MCP call failed: {result.content}")
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


async def terminal(session, request_id):
    for _ in range(45):
        result = await call(session, "hpc_slurm_status", {"request_id": request_id})
        if result["state"] in {"succeeded", "failed", "missing_outputs", "timed_out", "cancelled"}:
            return result
        await asyncio.sleep(1)
    raise RuntimeError(f"Slurm did not provide terminal evidence: {result}")


def wait_for_allocation(native_id):
    for _ in range(45):
        rows = observed([
            "sacct", "--noheader", "--parsable2", "--allocations", f"--jobs={native_id}",
            "--format=JobIDRaw,State%40,ExitCode",
        ])
        if rows and rows[0][1] == "COMPLETED":
            check(rows[0] == [native_id, "COMPLETED", "0:0"], "Unexpected native accounting row")
            return {"native_id": native_id, "state": "COMPLETED", "exit_code": "0:0"}
        time.sleep(1)
    raise RuntimeError(f"Native job {native_id} did not complete")


def native_reference(profile, root, expected):
    name = f"polishpc-native-{uuid4().hex}"
    args = [
        "sbatch", "--parsable", "--export=NIL", "--no-requeue", "--cpus-per-task=1", "--mem=128M",
        "--time=1", f"--partition={profile.partition}", f"--chdir={root}", f"--job-name={name}",
    ]
    if profile.account:
        args.append(f"--account={profile.account}")
    script = f"#!/bin/sh\nexec {shlex.quote(profile.python)} -I -B program.py parameters.json scheduled.json\n"
    result = native(args, data=script.encode())
    check(result.returncode == 0, f"Native submission failed: {result.stderr.decode().strip()}")
    native_id = result.stdout.decode().strip().split(";")[0]
    accounting = wait_for_allocation(native_id)
    check((root / "scheduled.json").read_bytes() == expected, "Native Slurm result differs")
    return {**accounting, "artifact_sha256": sha256(expected).hexdigest()}


async def silogen_reference(profile, directory, python, expected):
    program = shlex.quote(profile.python)
    (directory / "provider.sbatch").write_text(
        f"#!/bin/sh\nexec {program} -I -B program.py parameters.json provider-result.json\n",
        encoding="utf-8",
    )
    config = directory / "provider.json"
    config.write_text(json.dumps({
        "site": "development-slurm",
        "remote": {"host": "unused-local-placement", "project_root": str(directory)},
        "slurm": {"default_partition": profile.partition, "default_time": "00:01:00"},
        "file_access": {"mode": "rsync", "local_root": str(directory)},
        "limits": {"scheduler_min_interval_seconds": 1.0},
    }), encoding="utf-8")
    settings = StdioServerParameters(
        command=str(python), args=["-I", "-m", "hpc_mcp", "--placement", "local", "--config", str(config)],
    )
    async with stdio_client(settings) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            response = await session.call_tool("sbatch", {
                "script_path": "provider.sbatch", "partition": profile.partition, "account": profile.account,
                "time_limit": "00:01:00", "extra_directives": [
                    "--cpus-per-task=1", "--mem=128M", "--export=NIL", "--no-requeue", f"--chdir={directory}",
                ],
            })
            match = re.match(r"Submitted job ([1-9][0-9]*)\.", response.content[0].text)
            check(not response.isError and match, "Pinned Silogen sbatch returned no job ID")
            accounting = wait_for_allocation(match.group(1))
            result = await session.call_tool("read_file", {"path": "provider-result.json"})
            check(not result.isError and result.content[0].text.encode() == expected, "Silogen artifact differs")
    return {**accounting, "revision": SILOGEN_REVISION, "artifact_sha256": sha256(expected).hexdigest()}


def verify_single_allocation(request_id, native_id):
    job_name = f"polishpc-{UUID(request_id).hex}"
    rows = observed([
        "sacct", "--noheader", "--parsable2", "--allocations", f"--user={os.getuid()}",
        f"--name={job_name}", "--format=JobIDRaw,JobName%80",
    ])
    check(rows == [[native_id, job_name]], "Accounting did not show exactly one submitted job")
    return len(rows)


async def interrupted(directory, profile, action):
    request_id = str(uuid4())
    args = {"manifest": "job.json", "request_id": request_id}
    async with connect(directory, action) as session:
        try:
            await session.call_tool("hpc_slurm_submit", args)
        except McpError:
            pass
        else:
            raise RuntimeError("The interrupted MCP server returned an acknowledgement")
    saved = profile.location / request_id
    check((saved / "intent.json").is_file(), "Dispatch intent was not persisted")
    check(not (saved / "ack.json").exists(), "The test failed to interrupt the native acknowledgement")
    async with connect(directory) as session:
        if action == "before_send":
            retry = await call(session, "hpc_slurm_submit", args)
            check(retry["state"] == "unknown" and retry["native_id"] is None, "Ambiguous retry sent a job")
            return retry
        result = await terminal(session, request_id)
        check(result["job_id"] == request_id, "Fresh client recovered another request")
        repeated = await call(session, "hpc_slurm_submit", args)
        check(repeated["native_id"] == result["native_id"], "A retry changed the native job")
        return {**result, "accounting_allocations": verify_single_allocation(request_id, result["native_id"])}


async def concurrent_requests(directory, expected):
    shared_id = str(uuid4())
    other_id = str(uuid4())
    shared_args = {"manifest": "job.json", "request_id": shared_id}
    other_args = {"manifest": "job.json", "request_id": other_id}
    async with connect(directory) as first, connect(directory) as second:
        left, right = await asyncio.gather(
            call(first, "hpc_slurm_submit", shared_args),
            call(second, "hpc_slurm_submit", shared_args),
        )
        check(sum(response["state"] == "submitted" for response in (left, right)) == 1,
              "Only one client should receive a new submission acknowledgement")
        check(left["native_id"] and left["native_id"] == right["native_id"],
              "Simultaneous requests did not resolve to the same native job")
        other = await call(second, "hpc_slurm_submit", other_args)
        check(other["state"] == "submitted" and other["native_id"] != left["native_id"],
              "The same manifest under a distinct UUID did not receive a new allocation")
        conflict = await second.call_tool("hpc_slurm_submit", {"manifest": "fail.json", "request_id": shared_id})
        check(conflict.isError, "A request UUID was rebound to a different manifest")
        results = await asyncio.gather(terminal(first, shared_id), terminal(second, other_id))

    cases = {}
    for key, result in zip(("shared_request", "distinct_request"), results):
        check(result["state"] == "succeeded", "Concurrent test workload failed")
        verified_artifact(result["receipt"], expected)
        cases[key] = {
            "job_id": result["job_id"], "native_id": result["native_id"],
            "native_state": result["native_state"],
            "accounting_allocations": verify_single_allocation(result["job_id"], result["native_id"]),
            "artifact_sha256": result["receipt"]["artifacts"][0]["sha256"],
        }
    return {**cases, "clients": 2, "conflicting_manifest_rejected": True}


async def compare(profile, directory, silogen_python):
    expected = reference(directory)
    report = {"environment": "development Slurm", "native": native_reference(profile, directory, expected)}
    if silogen_python:
        report["silogen_mcp"] = await silogen_reference(profile, directory, silogen_python, expected)
    async with connect(directory) as session:
        report["preflight"] = await call(session, "hpc_slurm_preflight")
        check(report["preflight"]["partition_visible"], "Configured partition is unavailable")
        prepared = await call(session, "hpc_prepare", {"manifest": "job.json", "profile": "slurm"})
        manifest = load(directory / "job.json")
        write_manifest(directory, "fail.json", {**manifest, "argv": [*manifest["argv"], "--mode", "fail"]})
        expected_states = (("job.json", "succeeded", "0:0"), ("fail.json", "failed", "7:0"))
        for name, state, exit_code in expected_states:
            args = {"manifest": name, "request_id": str(uuid4())}
            accepted = await call(session, "hpc_slurm_submit", args)
            check(accepted["state"] == "submitted", "Slurm did not acknowledge submission")
            result = await terminal(session, args["request_id"])
            schema("result").validate(result["receipt"])
            check(result["state"] == state and result["native_exit_code"] == exit_code, "Native outcome changed")
            if state == "succeeded":
                verified_artifact(result["receipt"], expected)
                check(prepared["manifest_sha256"] == result["receipt"]["manifest_sha256"],
                      "Recovered manifest differs from the prepared job")
            report[state] = result
    report["accepted_before_disconnect"] = await interrupted(directory, profile, "after_accept")
    receipt = report["accepted_before_disconnect"]["receipt"]
    check(report["accepted_before_disconnect"]["state"] == "succeeded", "Interrupted job failed")
    verified_artifact(receipt, expected)
    report["no_evidence_of_acceptance"] = await interrupted(directory, profile, "before_send")
    report["concurrent_requests"] = await concurrent_requests(directory, expected)
    missing = "missing-" + uuid4().hex
    denials = {"partition": [f"--partition={missing}"]}
    if profile.account:
        denials["account"] = [f"--partition={profile.partition}", f"--account={missing}"]
    report["rejected_test_only"] = {}
    for reason, options in denials.items():
        denied = native(["sbatch", "--test-only", "--time=1", *options], data=b"#!/bin/sh\nexit 0\n")
        check(denied.returncode != 0 and f"invalid {reason}".encode() in denied.stderr.lower(),
              f"The scheduler did not explicitly reject the nonexistent {reason}")
        report["rejected_test_only"][reason] = {"native_exit_code": denied.returncode}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--silogen-python", type=Path, help="Isolated Python with the documented Silogen revision")
    args = parser.parse_args()
    profile = SlurmProfile.configured()
    # The workspace is adjacent to the configured state on the same shared filesystem.
    with TemporaryDirectory(prefix="portable-slurm-", dir=profile.location) as workspace:
        directory = Path(workspace)
        for name in ("job.json", "program.py", "parameters.json"):
            shutil.copyfile(CASE / name, directory / name)
        report = json.dumps(asyncio.run(compare(profile, directory, args.silogen_python)), indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")


if __name__ == "__main__":
    main()
