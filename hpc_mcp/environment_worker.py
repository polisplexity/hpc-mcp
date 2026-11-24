"""Self-contained Linux environment operations sent over the existing SSH connection."""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
from uuid import uuid4


COMMANDS = (
    "python3", "pip3", "gcc", "g++", "gfortran", "make", "cmake", "git", "R", "Rscript", "julia",
    "mpirun", "mpicc", "mpifort", "docker", "podman", "apptainer", "singularity",
    "sbatch", "sinfo", "srun", "qsub", "qstat", "bsub", "modulecmd", "lmod",
    "conda", "micromamba", "spack", "nvidia-smi", "rocminfo", "rsync", "sftp", "quota",
)


def private_root(value):
    if not value:
        raise ValueError("The operator must configure a private SSH environment directory")
    root = Path(value)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("The SSH environment directory must exist at an absolute, non-symlink path")
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or not os.access(root, os.W_OK | os.X_OK):
        raise ValueError("The SSH environment directory must be private and writable by the account")
    return root


def fingerprint(lock):
    base = {
        "format": 1, "lock": lock, "platform": platform.machine(),
        "python": platform.python_version(), "base": str(Path(sys.executable).resolve()),
    }
    return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


def ready(directory):
    marker = directory / "ready.json"
    if directory.is_symlink() or marker.is_symlink() or not (directory / "bin/python").is_file():
        return None
    if not marker.is_file():
        return None
    receipt = json.loads(marker.read_bytes())
    if receipt.get("environment_id") != directory.name or not receipt.get("installation_id"):
        raise ValueError("The environment readiness record is invalid")
    return receipt


@contextmanager
def account_lock(root):
    import fcntl

    descriptor = os.open(root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "r+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This account already has an environment operation running. Retry after it finishes.") from None
        yield


def command_output(command, timeout, *, cwd=None, env=None):
    result = subprocess.run(
        command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
        timeout=timeout, check=True, text=True,
    )
    return result.stdout.strip()


def inventory(root_value, locks, r_runtime):
    try:
        root = private_root(root_value)
    except ValueError:
        root = None
    cpu_ids = os.sched_getaffinity(0)
    cores = set()
    for cpu in cpu_ids:
        topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        try:
            cores.add(tuple((topology / file).read_text().strip() for file in ("physical_package_id", "core_id")))
        except OSError:
            cores.clear()
            break
    mem_kib = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                   if line.startswith("MemTotal:"))
    home = Path.home()
    tool_names = [name for name in COMMANDS if shutil.which(name)]
    docker = None
    if "docker" in tool_names:
        try:
            docker = command_output(["docker", "version", "--format", "{{.Server.Version}}"], 4)
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "target": "ssh",
        "os": platform.freedesktop_os_release().get("PRETTY_NAME", "Linux"),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "visible_hardware": {
            "logical_cpus_in_affinity": len(cpu_ids), "physical_cores_in_affinity": len(cores) or None,
            "system_ram_mib": mem_kib // 1024,
        },
        "account_allocation": "unverified",
        "commands_on_path": tool_names,
        "docker_server_version": docker,
        "compute_device_nodes": {
            "nvidia": Path("/dev/nvidiactl").exists(), "amd": Path("/dev/kfd").exists(),
            "rdma": bool(list(Path("/dev/infiniband").glob("uverbs*"))),
        },
        "storage": {
            "home_writable": os.access(home, os.W_OK | os.X_OK),
            "home_filesystem_free_mib": shutil.disk_usage(home).free // (1024 * 1024),
            "scratch_configured": bool(os.getenv("SCRATCH")),
            "account_quota": "unverified",
        },
        "venv_module": importlib.util.find_spec("venv") is not None,
        "private_environment_root_ready": root is not None,
        "approved_environments": [
            r_runtime.probe(name, lock) if "r_version" in lock else
            {"name": name, "packages": {item["name"]: item["version"] for item in lock["packages"]},
             "state": "ready" if root and ready(root / fingerprint(lock)) else "needs_preparation"}
            for name, lock in locks.items()
        ],
    }


def check_versions(python, packages):
    code = ("import importlib.metadata as m, json, sys;"
            "print(json.dumps({name: m.version(name) for name in sys.argv[1:]}))")
    try:
        versions = json.loads(command_output([python, "-I", "-B", "-c", code, *packages], 8))
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError("Unable to verify installed package metadata for this environment") from None
    if versions != packages:
        raise ValueError("Installed versions differ from the approved lock")


def install(directory, lock):
    if directory.is_symlink():
        raise ValueError("An environment directory cannot be a symlink")
    if directory.exists():
        # A partial installation has no readiness marker. Rebuild it at its final venv path.
        shutil.rmtree(directory)
    directory.mkdir(mode=0o700)
    python = directory / "bin/python"
    lockfile = directory / "requirements.lock"
    lockfile.write_text("".join(
        f'{item["name"]}=={item["version"]} ' + " ".join(f"--hash=sha256:{value}" for value in item["sha256"]) + "\n"
        for item in lock["packages"]
    ), encoding="ascii")
    try:
        command_output([sys.executable, "-I", "-B", "-m", "venv", str(directory)], 25)
        command_output([
            python, "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check",
            "--no-input", "install", "--require-hashes", "--only-binary=:all:", "--no-deps",
            "--no-cache-dir", "--index-url", "https://pypi.org/simple", "--retries", "1", "--timeout", "10",
            "-r", lockfile,
        ], 60, cwd=directory, env={"LANG": "C.UTF-8", "PIP_CONFIG_FILE": os.devnull})
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Venv creation or locked wheel installation failed. Check Python and PyPI connectivity.") from None


def python_operation(root, body, execute_job):
    lock = body["lock"]
    directory = root / fingerprint(lock)
    versions = {item["name"]: item["version"] for item in lock["packages"]}
    python = directory / "bin/python"
    record = ready(directory)
    if body["action"] == "prepare":
        if record is None:
            install(directory, lock)
        check_versions(python, versions)
        if record is None:
            record = {"environment_id": directory.name, "installation_id": str(uuid4())}
            temporary = directory / "ready.tmp"
            temporary.write_text(json.dumps(record), encoding="ascii")
            temporary.replace(directory / "ready.json")
            status = "installed"
        else:
            status = "reused"
        return {**record, "status": status, "packages": versions}
    if record is None:
        raise ValueError("Prepare this approved environment before running the batch")
    if body["expected_environment_id"] not in (None, record["environment_id"]):
        raise ValueError("The environment changed since preparation")
    check_versions(python, versions)
    receipts = [
        execute_job(job["manifest"], job["files"], body["profile"], python_executable=python)
        for job in body["jobs"]
    ]
    return {**record, "parallel_jobs": 1, "receipts": receipts}


def r_operation(body, execute_job, execute_native, r_runtime, storage_factory):
    preparing = body["action"] == "prepare"
    selected = r_runtime.select(body["lock"], allow_pull=preparing)
    if preparing:
        return selected
    if body["expected_environment_id"] != selected["environment_id"]:
        raise ValueError("The R environment changed since preparation")
    receipts = []
    for job in body["jobs"]:
        manifest = job["manifest"]
        distinct_storage = "output_mode" in manifest or any("source" in item for item in manifest["inputs"])
        storage = storage_factory(body["data_root"]) if distinct_storage else None
        receipts.append(r_runtime.run(selected, job, execute_job, execute_native, storage))
    return {**selected, "parallel_jobs": 1, "receipts": receipts}


def environment_dispatch(request, execute_job, execute_native, r_runtime, storage_factory):
    try:
        body = json.loads(request)
        action = body["action"]
        if action == "probe":
            result = inventory(body["root"], body["locks"], r_runtime)
        elif action == "verify_artifact":
            result = storage_factory(body["data_root"]).verify(body["reference"])
        elif action in ("prepare", "batch"):
            root = private_root(body["root"])
            with account_lock(root):
                if "r_version" in body["lock"]:
                    result = r_operation(body, execute_job, execute_native, r_runtime, storage_factory)
                else:
                    result = python_operation(root, body, execute_job)
            result["name"] = body["name"]
        else:
            raise ValueError("Unknown environment action")
        print(json.dumps({"result": result}))
    except ValueError as error:
        print(json.dumps({"error": str(error)}))
    except (OSError, KeyError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({"error": "The SSH environment operation returned no verified result"}))
