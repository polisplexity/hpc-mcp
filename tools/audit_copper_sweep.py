"""Install one copper recipe and observe the agent's three Slurm allocations."""

import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import sleep
from uuid import UUID

from hpc_mcp.client import JOB_ROOT
from hpc_mcp.recipes import VERSION
from hpc_mcp.slurm import SlurmProfile, observed
from hpc_mcp.worker import JOB_VERSION, digest
from tools.check_mpi_copper import CASE, POTENTIAL


RECIPE = "copper-nve-v1"
TEMPERATURES = (300, 600, 900)
OUTPUT = "copper-result.json"


def install_recipe(root):
    directory = root / "recipes" / RECIPE
    directory.mkdir(parents=True)
    sources = [CASE / name for name in ("run.py", "pin.py", "in.copper")] + [POTENTIAL]
    inputs = []
    for source in sources:
        shutil.copyfile(source, directory / source.name)
        inputs.append({"path": source.name, "sha256": digest(source.read_bytes())})
    spec = {
        "version": VERSION, "recipe": RECIPE, "profile": "slurm",
        "description": "Relax 131,072 copper atoms for 140 steps using two MPI ranks.",
        "parameters": {"temperature_k": {"minimum": 300, "maximum": 900}},
        "job": {
            "version": JOB_VERSION, "runtime": "python3", "entrypoint": "run.py",
            "argv": ["2", "32", "140", "70", "temperature", {"parameter": "temperature_k"}],
            "inputs": inputs, "outputs": [OUTPUT],
            "resources": {"cpus": 2, "memory_mib": 512, "wall_time_seconds": 30},
        },
    }
    (directory / "recipe.json").write_text(json.dumps(spec), encoding="utf-8")
    return directory, spec


def native_compare(directory):
    references = {}
    for temperature in TEMPERATURES:
        subprocess.run(
            [sys.executable, "-I", "-B", "run.py", "2", "32", "140", "70", "temperature", str(temperature)],
            cwd=directory, check=True, timeout=30,
        )
        references[str(temperature)] = json.loads((directory / OUTPUT).read_bytes())
    print(json.dumps(references, indent=2))


def accounting(job_names):
    return observed([
        "sacct", "--noheader", "--parsable2", "--allocations", f"--user={os.getuid()}",
        f"--name={','.join(job_names)}", f"--starttime={(date.today() - timedelta(days=1)).isoformat()}",
        "--format=JobIDRaw,JobName%80,State%40,AllocCPUS,ExitCode",
    ])


def audit(root, spec, requests, profile):
    names = [f"polishpc-{request.hex}" for request in requests]
    receipts = [profile.location / str(request) / "receipt.json" for request in requests]
    env = {**os.environ, JOB_ROOT: str(root)}
    rows = None
    with subprocess.Popen([sys.executable, "-m", "hpc_mcp.server"], env=env) as server:
        while server.poll() is None:
            if all(path.is_file() for path in receipts):
                rows = accounting(names)
                if rows and {row[1] for row in rows if row[2] == "COMPLETED"} == set(names):
                    break
            sleep(1)
        if server.poll() is not None or rows is None:
            rows = accounting(names)
        record = {"recipe": spec, "accounting": rows, "slurm_version": profile.preflight()["version"]}
        print(f"SWEEP_AUDIT {json.dumps(record, sort_keys=True)}", file=sys.stderr, flush=True)
        return server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_ids", nargs="*", type=UUID)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if args.native and args.request_ids or not args.native and len(set(args.request_ids)) != len(TEMPERATURES):
        parser.error("Supply three distinct request UUIDs or use --native")
    profile = SlurmProfile.configured()
    with TemporaryDirectory(prefix="copper-sweep-", dir=profile.location) as workspace:
        root = Path(workspace)
        directory, spec = install_recipe(root)
        if args.native:
            native_compare(directory)
            return 0
        return audit(root, spec, args.request_ids, profile)


if __name__ == "__main__":
    raise SystemExit(main())
