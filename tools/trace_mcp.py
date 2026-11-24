"""Relay a stdio MCP connection and record its tool requests and responses."""

import argparse
from contextlib import suppress
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread


def message(line):
    try:
        value = json.loads(line)
    except (UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def trace_stdio(command, destination):
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as trace:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        pending = set()
        lock = Lock()

        def record(event):
            trace.write(json.dumps(event) + "\n")
            trace.flush()

        def forward_input():
            try:
                for line in sys.stdin.buffer:
                    if child.poll() is not None:
                        break
                    request = message(line)
                    request_id = request.get("id")
                    if request.get("method") == "tools/call" and type(request_id) in (int, str):
                        with lock:
                            pending.add(request_id)
                            record({"request": request})
                    child.stdin.write(line)
                    child.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                with suppress(BrokenPipeError):
                    child.stdin.close()

        Thread(target=forward_input, daemon=True).start()
        try:
            for line in child.stdout:
                response = message(line)
                response_id = response.get("id")
                with lock:
                    if (type(response_id) in (int, str) and response_id in pending
                            and ("result" in response or "error" in response)):
                        pending.remove(response_id)
                        record({"response": response})
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
        finally:
            child.stdout.close()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        return child.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide the MCP launch command after --")
    sys.exit(trace_stdio(command, args.trace))


if __name__ == "__main__":
    main()
