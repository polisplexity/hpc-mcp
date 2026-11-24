"""Verify the portable client example against actual MCP calls and an agent answer."""

import argparse
import base64
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

from hpc_mcp.client import describe, prepare, verify_receipt
from hpc_mcp.worker import digest


ROOT = Path(__file__).resolve().parents[1] / "cases" / "portable-python"
MANIFEST = "client-example/job.json"
UNAVAILABLE = {"state": "unavailable", "native_id": "", "artifact_sha256": "", "exit_code": -1}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def native_reference():
    case = ROOT / "client-example"
    points = json.loads((case / "points.json").read_bytes())
    count = len(points)
    sx, sy = sum(x for x, _ in points), sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    slope = Fraction(count * sxy - sx * sy, count * sxx - sx * sx)
    expected = {"intercept": str((sy - sx * slope) / count), "observations": count, "slope": str(slope)}
    with TemporaryDirectory() as directory:
        output = Path(directory) / "fit-result.json"
        subprocess.run(
            [sys.executable, "-I", "-B", str(case / "fit.py"), str(case / "points.json"), str(output)],
            check=True, timeout=10,
        )
        data = output.read_bytes()
    require(json.loads(data) == expected, "The native result disagrees with the normal equations")
    return expected, data


def claims_with_fields(path, fields):
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    candidates = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            item, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.keys() == fields:
            candidates.append(item)
    require(len(candidates) == 1, "Expected exactly one structured agent answer")
    return candidates[0]


def final_claims(path):
    claims = claims_with_fields(path, UNAVAILABLE.keys())
    require(type(claims["exit_code"]) is int, "The submitted exit code must be an integer")
    return claims


def exchanges(path, *, allow_tool_errors=False):
    calls = {}
    replies = {}
    for line in path.read_bytes().splitlines():
        event = json.loads(line)
        require(isinstance(event, dict), "Expected a trace event object")
        if "request" in event:
            request = event["request"]
            require(request["method"] == "tools/call", "Expected an MCP tool call")
            call_id = request["id"]
            require(call_id not in calls, "Repeated JSON-RPC request ID")
            calls[call_id] = request["params"]
        elif "response" in event:
            response = event["response"]
            call_id = response["id"]
            require(call_id in calls and call_id not in replies, "Unmatched JSON-RPC response")
            result = response.get("result")
            require("error" not in response and isinstance(result, dict), "MCP returned an error")
            if allow_tool_errors and result.get("isError"):
                replies[call_id] = {"tool_error": "\n".join(
                    item["text"] for item in result["content"] if item["type"] == "text"
                )}
                continue
            require(not result.get("isError"), "MCP returned a tool error")
            structured = result.get("structuredContent")
            replies[call_id] = structured if structured is not None else json.loads(result["content"][0]["text"])
        else:
            raise ValueError("Unknown trace event")
    require(calls.keys() == replies.keys(), "Some MCP calls have no response")
    return [(call["name"], call["arguments"], replies[call_id]) for call_id, call in calls.items()]


def verify(trace, answer, request_id, unavailable=False):
    calls = exchanges(trace)
    if unavailable:
        require(not calls, "The unavailable configuration unexpectedly dispatched a tool")
        require(final_claims(answer) == UNAVAILABLE, "The agent did not report the missing receipt")
        return {"request_id": request_id, "outcome": "unavailable", "tool_calls": []}

    names = [name for name, _, _ in calls]
    require(names[:2] == ["hpc_prepare", "hpc_slurm_submit"] and names[2:]
            and set(names[2:]) == {"hpc_slurm_status"}, "Missing prepare, submit or status tool evidence")
    (_, prepare_args, prepared), (_, submit_args, submitted), *statuses = calls
    require(prepare_args == {"manifest": MANIFEST, "profile": "slurm"}, "Unexpected preparation arguments")
    require(submit_args == {"manifest": MANIFEST, "request_id": request_id}, "Unexpected submission arguments")
    package = prepare(ROOT, MANIFEST, "slurm")
    require(prepared == describe(package), "The prepared manifest differs from the fixture")
    require(submitted["job_id"] == request_id and submitted["state"] == "submitted",
            "No actual scheduler submission was acknowledged")
    native_id = submitted["native_id"]
    require(isinstance(native_id, str) and native_id.isascii() and native_id.isdecimal(),
            "The scheduler did not supply a native ID")
    for _, args, observed in statuses:
        require(args == {"request_id": request_id} and observed["job_id"] == request_id,
                "Status queried a different job")
        require(observed["native_id"] == native_id, "Status reported a different native job")
    terminal = statuses[-1][2]
    require(terminal["state"] == "succeeded" and terminal["native_state"] == "COMPLETED"
            and terminal["native_exit_code"] == "0:0", "No successful terminal Slurm record")
    receipt = terminal["receipt"]
    verify_receipt(receipt, package)
    require(receipt["job_id"] == request_id and receipt["native_id"] == native_id
            and receipt["status"] == "succeeded" and receipt["exit_code"] == 0,
            "The worker receipt disagrees with the scheduler")
    artifact, = receipt["artifacts"]
    reference, data = native_reference()
    require(base64.b64decode(artifact["base64"], validate=True) == data, "Artifact bytes differ from the native run")
    claims = final_claims(answer)
    require(claims == {"state": "succeeded", "native_id": native_id, "exit_code": 0,
                       "artifact_sha256": digest(data)}, "The agent answer differs from verified tool evidence")
    return {
        "request_id": request_id, "outcome": "succeeded", "tool_calls": names,
        "manifest_sha256": receipt["manifest_sha256"],
        "scheduler": {"native_id": native_id, "state": terminal["native_state"], "exit_code": "0:0"},
        "artifact": {"path": artifact["path"], "sha256": artifact["sha256"], "value": reference},
        "final_claims": claims,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--answer", required=True, type=Path)
    parser.add_argument("--request-id", required=True, type=UUID)
    parser.add_argument("--expect-unavailable", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.trace, args.answer, str(args.request_id), args.expect_unavailable)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Agent receipt rejected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
