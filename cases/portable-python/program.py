"""Count primes in reproducible, seeded sample windows."""

import argparse
import json
from math import isqrt
from pathlib import Path
from random import Random


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("compute", "fail", "skip"), default="compute")
    args = parser.parse_args()
    if args.mode == "fail":
        return 7
    if args.mode == "skip":
        return 0
    settings = json.loads(args.input.read_text(encoding="utf-8"))
    rng = Random(settings["seed"])
    windows = [
        rng.randrange(2, settings["max_start"] + 1)
        for _ in range(settings["windows"])
    ]
    width = settings["width"]
    limit = max(windows) + width
    prime = bytearray(b"\x01" * limit)
    prime[:2] = b"\0\0"
    for candidate in range(2, isqrt(limit - 1) + 1):
        if prime[candidate]:
            for multiple in range(candidate * candidate, limit, candidate):
                prime[multiple] = 0
    result = {"windows": [{"start": start, "count": sum(prime[start:start + width])} for start in windows]}
    args.output.write_bytes((json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
