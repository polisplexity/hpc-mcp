"""Select and run an approved R runtime on the SSH worker."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4


class DockerFailure(ValueError):
    """A safe diagnostic for a fixed Docker operation."""


class RRuntime:
    def __init__(self, file_limit):
        self.file_limit = file_limit
        self.docker = shutil.which("docker")
        self.rscript = shutil.which("Rscript")
        self.docker_env = {key: os.environ[key] for key in ("HOME", "PATH") if key in os.environ}

    def docker_args(self, *arguments):
        return [self.docker, "--host", "unix:///var/run/docker.sock", *arguments]

    def docker_output(self, *arguments, timeout=8):
        if not self.docker:
            raise ValueError("Docker is unavailable on the approved SSH target")
        try:
            result = subprocess.run(
                self.docker_args(*arguments), env=self.docker_env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout, check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise DockerFailure(f"Docker {arguments[0]} {arguments[1]} failed ({type(error).__name__})") from None
        return result.stdout.strip()

    def native_version(self):
        if self.rscript:
            try:
                result = subprocess.run(
                    [self.rscript, "--vanilla", "-e", "cat(as.character(getRversion()))"],
                    stdin=subprocess.DEVNULL, env={"LANG": "C.UTF-8"}, timeout=5, check=True,
                    capture_output=True, text=True,
                )
                version = result.stdout.strip()
                if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
                    return version
            except (OSError, subprocess.SubprocessError):
                pass
        return None

    def image_id(self, lock):
        if not self.docker:
            return None
        try:
            image = self.docker_output("image", "inspect", "--format", "{{.Id}} {{.Os}}/{{.Architecture}}", lock["image"])
        except DockerFailure:
            return None
        image_id, platform = image.split()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id) or platform != lock["platform"]:
            raise ValueError("The cached image does not match the approved Linux platform")
        return image_id

    def probe(self, name, lock):
        native = self.native_version()
        return {"name": name, "runtime": "rscript", "required_version": lock["r_version"],
                "native_rscript_detected": self.rscript is not None, "native_r_version": native,
                "native_compatible": native == lock["r_version"], "approved_image": lock["image"],
                "image_cached": self.image_id(lock) is not None}

    def select(self, lock, *, allow_pull=False):
        version = lock["r_version"]
        if self.native_version() == version:
            executable = Path(self.rscript).resolve(strict=True)
            binary = sha256(executable.read_bytes()).hexdigest()
            identity = sha256(f"rscript:{version}:{binary}".encode()).hexdigest()
            return {"runtime": "rscript", "r_version": version, "route": "native",
                    "environment_id": identity, "status": "reused"}

        image_id = self.image_id(lock)
        status = "reused"
        if image_id is None and allow_pull:
            try:
                self.docker_output("image", "pull", "--platform", lock["platform"], lock["image"], timeout=180)
            except DockerFailure:
                raise ValueError("Docker could not pull the approved image from its registry") from None
            image_id = self.image_id(lock)
            status = "pulled"
        if image_id is None:
            raise ValueError("Prepare a compatible native R installation or the approved Docker image first")
        identity = sha256(f'{lock["image"]}:{image_id}:{version}'.encode()).hexdigest()
        return {"runtime": "rscript", "r_version": version, "route": "docker",
                "environment_id": identity, "status": status, "image": lock["image"], "image_id": image_id}

    def launch_container(self, selection, root, manifest, stdout, stderr):
        import resource

        resources = manifest["resources"]
        memory = f'{resources["memory_mib"]}m'
        if "," in str(root):
            raise ValueError("The job directory cannot contain a comma in Docker mode")
        container = self.docker_output(
            "container", "create", "--pull=never", "--network=none", "--read-only",
            "--name", "polisplexity-hpc-r-" + uuid4().hex,
            "--label", "org.polisplexity.hpc.runtime=rscript",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
            "--cpus", str(resources["cpus"]), "--memory", memory, "--memory-swap", memory,
            "--pids-limit=32", "--ulimit", f"fsize={self.file_limit}:{self.file_limit}", "--ulimit", "core=0:0",
            "--log-driver=none", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
            "--mount", f"type=bind,source={root},target=/job", "--workdir", "/job", "--env", "HOME=/tmp",
            "--env", "OPENBLAS_NUM_THREADS=1", "--env", "OMP_NUM_THREADS=1",
            "--entrypoint", "Rscript", selection["image"], "--vanilla", manifest["entrypoint"], *manifest["argv"],
        )
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise RuntimeError("Docker did not return a container ID")

        def limit_logs():
            resource.setrlimit(resource.RLIMIT_FSIZE, (self.file_limit, self.file_limit))

        try:
            image_id = self.docker_output("container", "inspect", "--format", "{{.Image}}", container)
            if image_id != selection["image_id"]:
                raise ValueError("The job container does not match the selected image")
            try:
                result = subprocess.run(
                    self.docker_args("container", "start", "--attach", container), env=self.docker_env,
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    timeout=resources["wall_time_seconds"], preexec_fn=limit_logs,
                )
            except subprocess.TimeoutExpired:
                return -9, True, container
            native_exit = self.docker_output("container", "wait", container)
            if not native_exit.isdecimal() or int(native_exit) != result.returncode:
                raise ValueError("Docker attach and wait returned different execution results")
            return int(native_exit), False, container
        finally:
            self.docker_output("container", "rm", "--force", container, timeout=12)

    def run(self, selection, job, execute_job, execute_native, storage=None):
        def launch(root, manifest, stdout, stderr):
            if selection["route"] == "docker":
                return self.launch_container(selection, root, manifest, stdout, stderr)
            command = [self.rscript, "--vanilla", manifest["entrypoint"], *manifest["argv"]]
            return execute_native(command, root, manifest["resources"], stdout, stderr)

        return execute_job(job["manifest"], job["files"], job["profile"],
                           launcher=launch, runtime_version=selection["r_version"],
                           stage_input=storage.stage if storage else None,
                           store_output=storage.store if storage else None)
