"""Run and verify the copper MCP sweep using the operator's Docker and Hermes."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from tools.verify_agent_copper_sweep import CLAIMS_FIELDS, TEMPERATURES, verify
from tools.verify_agent_receipt import claims_with_fields


ROOT = Path(__file__).resolve().parents[1]
TOOLS = [
    "hpc_slurm_preflight", "hpc_list_recipes", "hpc_prepare_recipe",
    "hpc_slurm_submit", "hpc_slurm_status", "hpc_slurm_read_json",
]


def make_profile(path, source, output, backend, *, tools=TOOLS, tool_timeout=20, trace_options=()):
    import yaml

    existing = yaml.safe_load((source / "config.yaml").read_text(encoding="utf-8"))
    if not isinstance(existing, dict) or not existing.get("model"):
        raise ValueError("The selected Hermes configuration must have a model")
    config = {key: existing[key] for key in ("model", "provider", "providers", "custom_providers") if key in existing}
    config.update({
        "mcp_discovery_timeout": 45,
        "tools": {"tool_search": {"enabled": "off"}},
        "mcp_servers": {"polisplexity_hpc": {
            "command": sys.executable,
            "args": [str(ROOT / "tools/trace_mcp.py"), "--trace", str(output / "mcp.jsonl"),
                     "--backend-stderr", str(output / "backend.stderr"), *trace_options, "--", *backend],
            "connect_timeout": 45, "timeout": tool_timeout,
            "tools": {"include": tools, "resources": False, "prompts": False},
        }},
    })
    path.mkdir(mode=0o700)
    (path / "config.yaml").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    credentials = source / ".env"
    if credentials.is_file():
        destination = path / ".env"
        destination.touch(mode=0o600, exist_ok=False)
        shutil.copyfile(credentials, destination)
    model = existing["model"]
    return model.get("default") if isinstance(model, dict) else model


def prompt(requests):
    ids = ", ".join(f"{temperature} K={request}" for temperature, request in requests.items())
    return (
        "Compare the relaxation of the same copper crystal at 300, 600, and 900 K in an authorized Docker pilot. "
        "Use only the HPC MCP tools. Check hpc_slurm_preflight and discover the recipe with hpc_list_recipes. "
        "Prepare one job per temperature via hpc_prepare_recipe using its integer temperature_k parameter. "
        f"Use the manifest path returned for each temperature and these job UUIDs: {ids}. "
        "Submit 300 K first, then deliberately repeat that exact hpc_slurm_submit once. Compare native_id. "
        "Then submit 600 K and 900 K with their own manifests and UUIDs. "
        "Poll hpc_slurm_status until each job succeeds, with at most 16 status calls total. "
        "Read the copper-result.json artifact for each using hpc_slurm_read_json. Use the last thermo sample. "
        "Return exactly one JSON object with keys runs and retry. Each runs item has integer temperature_k, "
        "string native_id, numeric final_temperature_k rounded to 3 decimals, and artifact_sha256 from the read call. "
        "Retry has integer temperature_k=300 and string native_id from the repeated submission. "
        "If required evidence is unavailable, report it as unavailable. Do not use shell commands or fabricate evidence."
    )


def run(args, output):
    engine, docker_version = subprocess.check_output(
        ["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}} {{.Server.Version}}"],
        text=True, timeout=15,
    ).split()
    if engine != "linux/amd64":
        raise ValueError("The Docker engine must be linux/amd64")
    revision = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, timeout=10).strip()
    image_id, image_revision = subprocess.check_output([
        "docker", "image", "inspect", "--format",
        '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}', args.image,
    ], text=True, timeout=15).split()
    if image_revision != revision:
        raise ValueError("Build the sweep image from the current checkout with build-sweep.sh")
    hermes_version = subprocess.check_output([args.hermes, "--version"], text=True, timeout=20).splitlines()[0]
    requests = {temperature: str(uuid4()) for temperature in TEMPERATURES}
    backend = [
        "env", "POLISPLEXITY_SLURM_TEST_CPUS=2", f"POLISPLEXITY_SLURM_TEST_CPUSET={args.cpu_ids}",
        f"POLISPLEXITY_SLURM_TEST_SUBNET={args.subnet or ''}", "bash",
        str(ROOT / "cases/portable-python/docker/check.sh"), args.image,
        "/opt/polis-venv/bin/python", "-m", "tools.audit_copper_sweep",
    ]
    with TemporaryDirectory(prefix="hpc-hermes-sweep-") as temporary:
        working = Path(temporary)
        model = make_profile(working / "profile", args.hermes_home, output, [*backend, *requests.values()])
        env = {**os.environ, "HERMES_HOME": str(working / "profile")}
        with (output / "agent.txt").open("wb") as answer, (output / "hermes.stderr").open("wb") as error:
            subprocess.run(
                [args.hermes, "chat", "--ignore-rules", "--quiet", "--max-turns", "28", "--source", "tool",
                 "--toolsets", "polisplexity_hpc", "--query", prompt(requests)],
                cwd=working, env=env, stdin=subprocess.DEVNULL, stdout=answer, stderr=error,
                check=True, timeout=210,
            )
    lines = (output / "backend.stderr").read_text(encoding="utf-8", errors="replace").splitlines()
    audits = [json.loads(line.removeprefix("SWEEP_AUDIT ")) for line in lines if line.startswith("SWEEP_AUDIT ")]
    answer = claims_with_fields(output / "agent.txt", CLAIMS_FIELDS)
    if len(audits) != 1 or len(audits[0].get("accounting") or []) != 3:
        raise ValueError("Expected independent Slurm accounting for three allocations")
    with (output / "native.json").open("wb") as native, (output / "native.stderr").open("wb") as error:
        subprocess.run([*backend, "--native"], stdin=subprocess.DEVNULL, stdout=native, stderr=error,
                       check=True, timeout=180)
    record = {
        "source_revision": revision, "docker_image_id": image_id,
        "docker_version": docker_version, "hermes_version": hermes_version, "model": model,
        "request_ids": requests, "audit": audits[0],
        "native_reference": json.loads((output / "native.json").read_bytes()),
        "agent_answer": answer,
    }
    record["verified"] = verify(output / "mcp.jsonl", output / "agent.txt", record)
    (output / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["verified"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-ids", required=True, help="Two comma-separated CPU IDs on the Docker host")
    parser.add_argument("--subnet", type=ipaddress.IPv4Network,
                        help="An available IPv4 CIDR for the test's internal Docker network")
    parser.add_argument("--output", required=True, type=Path, help="A new directory for the trace and results")
    parser.add_argument("--image", default="polisplexity-hpc/mpi-sweep:local")
    parser.add_argument("--hermes", default="hermes", help="Hermes CLI executable or absolute path")
    parser.add_argument("--hermes-home", type=Path,
                        default=Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")),
                        help="Source Hermes profile with configured model and API credentials")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+,[0-9]+", args.cpu_ids) or len(set(map(int, args.cpu_ids.split(",")))) != 2:
        parser.error("--cpu-ids must name two distinct logical CPU IDs")
    args.hermes = shutil.which(args.hermes)
    if not args.hermes:
        parser.error("Hermes is not on PATH. Supply its executable with --hermes.")
    args.hermes = str(Path(args.hermes).absolute())
    output = args.output.resolve()
    try:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        run(args, output)
    except (ImportError, OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Sweep failed: {error}\nInspect the run files in {output}\n")


if __name__ == "__main__":
    main()
