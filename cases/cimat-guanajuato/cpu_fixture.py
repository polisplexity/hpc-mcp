"""Fixed, dependency-free CPU workload for the CIMAT connectivity pilot."""

import json


LIMIT = 100_000


if __name__ == "__main__":
    print(json.dumps({"limit": LIMIT, "sum_of_squares": sum(i * i for i in range(1, LIMIT + 1))}))
