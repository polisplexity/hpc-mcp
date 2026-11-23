"""Validate and execute a bounded Python job on a trusted Linux profile."""

import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import uuid


JOB_VERSION = "polisplexity.hpc.job.v1"
RESULT_VERSION = "polisplexity.hpc.result.v1"
MAX_FILE_BYTES = 256 * 1024
MAX_FILES = 8
PROFILES = {"local": (4, 512, 30), "ssh": (1, 128, 15), "slurm": (4, 512, 30)}
PATH_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(data):
    return sha256(data).hexdigest()


def checked_path(name):
    if not isinstance(name, str) or not all(PATH_SEGMENT.fullmatch(part) for part in name.split("/")):
        raise ValueError("Use relative POSIX paths with plain file names")
    if len(name) > 240:
        raise ValueError("A job path exceeds 240 characters")
    return PurePosixPath(name)


def require_keys(value, keys):
    if not isinstance(value, dict) or value.keys() != keys:
        raise ValueError("Expected exactly these fields: " + ", ".join(sorted(keys)))


def validate_manifest(manifest, profile="local"):
    require_keys(manifest, {"version", "runtime", "entrypoint", "argv", "inputs", "outputs", "resources"})
    if manifest["version"] != JOB_VERSION or manifest["runtime"] != "python3":
        raise ValueError("Expected job v1 with the python3 runtime")
    entrypoint = checked_path(manifest["entrypoint"])
    argv = manifest["argv"]
    if not isinstance(argv, list) or len(argv) > 32 or any(
        not isinstance(arg, str) or "\0" in arg or len(arg) > 1024 for arg in argv
    ):
        raise ValueError("argv must contain at most 32 bounded strings")

    inputs, outputs = manifest["inputs"], manifest["outputs"]
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_FILES:
        raise ValueError("Declare between one and eight input files")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= MAX_FILES:
        raise ValueError("Declare between one and eight expected output files")
    input_paths = []
    for item in inputs:
        require_keys(item, {"path", "sha256"})
        input_paths.append(checked_path(item["path"]))
        if not isinstance(item["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", item["sha256"]):
            raise ValueError("Input digests must be lowercase SHA-256 strings")
    output_paths = [checked_path(name) for name in outputs]
    if entrypoint not in input_paths or entrypoint.suffix != ".py":
        raise ValueError("The Python entrypoint must also be a hashed input")
    paths = input_paths + output_paths
    if len(paths) != len(set(paths)) or any(parent in paths for path in paths for parent in path.parents):
        raise ValueError("Input and output paths must be distinct files")
    if any(path.parts[0] in {"stdout", "stderr"} for path in paths):
        raise ValueError("The worker reserves stdout and stderr")

    resources = manifest["resources"]
    require_keys(resources, {"cpus", "memory_mib", "wall_time_seconds"})
    keys = ("cpus", "memory_mib", "wall_time_seconds")
    for key, minimum, maximum in zip(keys, (1, 64, 1), PROFILES[profile]):
        if type(resources[key]) is not int or not minimum <= resources[key] <= maximum:
            raise ValueError(f"{key} must be an integer between {minimum} and {maximum} for the selected profile")


def read_file(root, name):
    path = root / checked_path(name)
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError(f"Expected a regular file inside the workspace: {name}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds the profile size limit: {name}")
    return data


def artifact(root, name):
    try:
        data = read_file(root, name)
    except (OSError, RuntimeError, ValueError):
        return None
    return {
        "path": name,
        "size_bytes": len(data),
        "sha256": digest(data),
        "base64": base64.b64encode(data).decode("ascii"),
    }


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def execute(manifest, files, profile, job_id=None):
    if sys.platform != "linux":
        raise ValueError("The direct worker requires Linux")
    import resource

    validate_manifest(manifest, profile)
    slurm_id = os.getenv("SLURM_JOB_ID", "") if profile == "slurm" else None
    if slurm_id is not None and not re.fullmatch(r"[1-9][0-9]*", slurm_id):
        raise ValueError("A Slurm worker requires its native job ID before launch")
    require_keys(files, {item["path"] for item in manifest["inputs"]})
    limits = manifest["resources"]
    available_cpus = sorted(os.sched_getaffinity(0))
    if len(available_cpus) < limits["cpus"]:
        raise ValueError("Requested CPU count exceeds the worker's visible affinity")

    def apply_limits():
        os.sched_setaffinity(0, available_cpus[:limits["cpus"]])
        resource.setrlimit(resource.RLIMIT_AS, (limits["memory_mib"] << 20,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits["wall_time_seconds"],) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES,) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    with TemporaryDirectory(prefix="polisplexity-hpc-") as directory:
        root = Path(directory).resolve()
        for item in manifest["inputs"]:
            name = item["path"]
            data = base64.b64decode(files[name], validate=True)
            if len(data) > MAX_FILE_BYTES or digest(data) != item["sha256"]:
                raise ValueError(f"Input digest or size mismatch: {name}")
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        started_at = timestamp()
        timed_out = False
        with (root / "stdout").open("wb") as stdout, (root / "stderr").open("wb") as stderr:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", manifest["entrypoint"], *manifest["argv"]],
                cwd=root,
                env={"LANG": "C.UTF-8"},
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                preexec_fn=apply_limits,
            )
            try:
                process.wait(timeout=limits["wall_time_seconds"])
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Reap children that stayed in the job's process group before reading outputs.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        finished_at = timestamp()
        artifacts, unavailable = [], []
        for name in manifest["outputs"]:
            item = artifact(root, name)
            if item is None:
                unavailable.append(name)
            else:
                artifacts.append(item)
        if timed_out:
            status = "timed_out"
        elif process.returncode:
            status = "failed"
        elif unavailable:
            status = "missing_outputs"
        else:
            status = "succeeded"
        return {
            "version": RESULT_VERSION,
            "job_id": job_id or str(uuid.uuid4()),
            "manifest_sha256": digest(canonical(manifest)),
            "profile": profile,
            "native_id": slurm_id or str(process.pid),
            "runtime_version": ".".join(map(str, sys.version_info[:3])),
            "started_at": started_at,
            "finished_at": finished_at,
            "resources": limits,
            "status": status,
            "exit_code": process.returncode,
            "artifacts": artifacts,
            "unavailable_outputs": unavailable,
            "logs": {name: artifact(root, name) for name in ("stdout", "stderr")},
        }


def dispatch(request):
    try:
        body = json.loads(request)
        print(json.dumps({"receipt": execute(body["manifest"], body["files"], body["profile"])}))
    except ValueError as error:
        print(json.dumps({"error": str(error)}))
    except (OSError, KeyError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({"error": "The worker produced no verified receipt. Execution state is unknown."}))
