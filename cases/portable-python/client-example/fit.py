"""Fit a straight line to synthetic observations with exact arithmetic."""

from fractions import Fraction
import json
from pathlib import Path
import sys


def main():
    points = json.loads(Path(sys.argv[1]).read_bytes())
    mean_x = Fraction(sum(x for x, _ in points), len(points))
    mean_y = Fraction(sum(y for _, y in points), len(points))
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in points)
    variance = sum((x - mean_x) ** 2 for x, _ in points)
    slope = covariance / variance
    intercept = mean_y - slope * mean_x
    result = {"intercept": str(intercept), "observations": len(points), "slope": str(slope)}
    Path(sys.argv[2]).write_bytes(
        (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


if __name__ == "__main__":
    main()
