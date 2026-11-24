"""Verify agent-issued MCP cancellation against an independent container audit."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from hpc_mcp.worker import canonical, digest
from tools.verify_agent_receipt import claims_with_fields, exchanges, require


MANIFEST = "mpi-copper-cancel.json"
CLAIMS = {"state", "native_state", "native_id", "native_exit_code"}
PREPARE = "hpc_prepare"
SUBMIT = "hpc_slurm_submit"
STATUS = "hpc_slurm_status"
CANCEL = "hpc_slurm_cancel"


def verify(trace, answer, run):
    audit = run["audit"]
    request_id = run["request_id"]
    unknown_id = run["unknown_request_id"]
    require(str(UUID(request_id)) == request_id and str(UUID(unknown_id)) == unknown_id
            and request_id != unknown_id and audit["request_id"] == request_id,
            "The agent and audit job identities differ")
    calls = exchanges(trace, allow_tool_errors=True)
    names = [name for name, _, _ in calls]
    require(names[:2] == [PREPARE, SUBMIT] and STATUS in names[2:]
            and set(names[2:]) == {STATUS, CANCEL}, "Missing agent tool actions")
    (_, prep_args, prepared), (_, submit_args, submitted), *operations = calls
    require(prep_args == {"manifest": MANIFEST, "profile": "slurm"}, "Unexpected preparation")
    require(submit_args == {"manifest": MANIFEST, "request_id": request_id}, "Unexpected submission")
    require(audit["manifest"]["argv"] == ["2", "32", "500", "50"]
            and audit["manifest"]["resources"] == {"cpus": 2, "memory_mib": 512, "wall_time_seconds": 30},
            "The agent did not prepare the bounded two-rank copper job")
    require(prepared["manifest_sha256"] == digest(canonical(audit["manifest"])), "Prepared manifest changed")
    require(submitted["job_id"] == request_id and submitted["state"] == "submitted",
            "Missing acknowledged Slurm allocation")
    native_id = submitted["native_id"]
    require(isinstance(native_id, str) and native_id.isascii() and native_id.isdecimal(), "Invalid allocation ID")

    cancel_indices = [index for index, (name, _, _) in enumerate(operations) if name == CANCEL]
    require(len(cancel_indices) == 3, "Require cancellation, terminal retry, and unknown-UUID probe")
    first, retry, unknown = cancel_indices
    require(unknown == len(operations) - 1, "Unknown UUID probe must be the last MCP action")
    require(operations[unknown][1] == {"request_id": unknown_id}
            and "Unknown Slurm request ID" in operations[unknown][2].get("tool_error", ""),
            "The unknown UUID was not rejected")
    for _, args, response in operations[:unknown]:
        require(args == {"request_id": request_id} and response["job_id"] == request_id
                and response["native_id"] == native_id, "Operation targeted a different allocation")
    require(any(reply["native_state"] == "RUNNING" for _, _, reply in operations[:first]
                if reply.get("native_state")), "No running state before the agent cancelled")
    confirmed = [reply for name, _, reply in operations[first + 1:retry] if name == STATUS
                 and (reply["state"], reply.get("native_state")) == ("cancelled", "CANCELLED")]
    require(confirmed, "Agent never checked terminal cancellation")
    terminal = confirmed[-1]
    require(operations[retry][2] == terminal, "Retry did not return the same terminal state")
    require(claims_with_fields(answer, CLAIMS) == {key: terminal[key] for key in CLAIMS},
            "Agent's final claims do not match Slurm evidence")

    running = audit["running"]
    require(running and running["queue"] == [native_id, "RUNNING"]
            and sum(process["process"] == "lmp" for process in running["processes"].values()) == 2,
            "Independent observer did not see two live LAMMPS ranks on the allocation")
    require(audit["final_queue"] == [] and audit["remaining_processes"] == {},
            "The allocation or MPI processes remained after cancellation")
    require(audit["cancel_acknowledged"] and not audit["worker_receipt_written"] and "receipt" not in terminal,
            "Cancellation did not acknowledge the request or wrongly supplied a worker receipt")
    (row,) = audit["accounting"]
    require(row[0] == native_id and row[1].split()[0] == "CANCELLED"
            and row[2:] == ["2", terminal["native_exit_code"]], "Native Slurm accounting disagrees")
    return {
        "request_id": request_id, "native_id": native_id, "native_state": row[1].split()[0],
        "native_exit_code": row[3], "mpi_ranks_observed": 2, "mpi_processes_remaining": 0,
        "tool_calls": names, "terminal_retry_matches": True, "unknown_request_rejected": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--answer", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.trace, args.answer, json.loads(args.run.read_bytes()))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Agent cancellation evidence rejected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
