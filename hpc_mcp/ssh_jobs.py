"""Reconcile a detached R job against its durable intent and Docker state."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from uuid import UUID


REQUEST_LABEL = "org.polisplexity.hpc.request"
SCOPE_LABEL = "org.polisplexity.hpc.scope"


def read_record(path):
    return json.loads(path.read_bytes())


def job_directory(parent, name):
    path = parent / name
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("The job state directory must be private")
    return path


class SSHJobs:
    def __init__(self, runtime, storage, stage, receipt, persist):
        self.runtime = runtime
        self.storage = storage
        self.stage = stage
        self.receipt = receipt
        self.persist = persist
        self.scope = sha256(str(storage.root).encode()).hexdigest()[:16]

    def name(self, job_id):
        return f"polisplexity-hpc-job-{self.scope}-{UUID(job_id).hex}"

    def snapshot(self, job_id, intent, native_id=None, state="unknown"):
        return {"job_id": job_id, "native_id": native_id, "state": state,
                "manifest_sha256": intent["manifest_sha256"], "environment_id": intent["environment_id"]}

    def inspect(self, job_id, intent, native_id):
        try:
            container = json.loads(self.runtime.docker_output(
                "container", "inspect", "--format", "{{json .}}", native_id or self.name(job_id),
            ))
        except ValueError:
            return None
        labels = container["Config"]["Labels"]
        if (not re.fullmatch(r"[a-f0-9]{64}", container["Id"])
                or (native_id and container["Id"] != native_id)
                or container["Name"] != "/" + self.name(job_id)
                or container["Image"] != intent["image_id"]
                or labels.get(REQUEST_LABEL) != job_id or labels.get(SCOPE_LABEL) != self.scope
                or container["RestartCount"] != 0):
            return None
        return container

    def cleanup(self, directory, result):
        work = directory / "work"
        if not work.exists() or work.is_symlink():
            return
        try:
            existing = self.runtime.docker_output("container", "ls", "--all", "--no-trunc", "--quiet",
                                                  "--filter", "id=" + result["native_id"])
            if existing:
                if existing != result["native_id"]:
                    return
                self.runtime.docker_output("container", "rm", result["native_id"])
            shutil.rmtree(work)
        except (OSError, ValueError):
            # A later status call can retry cleanup after the durable receipt is read.
            pass

    def observe(self, directory, intent):
        job_id = directory.name
        result_path = directory / "result.json"
        if result_path.is_file():
            result = read_record(result_path)
            self.cleanup(directory, result)
            return result
        ack = directory / "container.json"
        native_id = read_record(ack)["native_id"] if ack.is_file() else None
        result = self.snapshot(job_id, intent, native_id)
        observed = self.inspect(job_id, intent, native_id)
        if observed is None:
            return result
        state = observed["State"]
        result.update(native_id=observed["Id"], native_state=state["Status"])
        if state["Running"]:
            return {**result, "state": "active"}
        if state["Status"] != "exited" or state["StartedAt"].startswith("0001-"):
            return result
        exit_code = state["ExitCode"]
        receipt = self.receipt(
            directory / "work", intent["manifest"], "ssh-r", job_id, observed["Id"], intent["r_version"],
            state["StartedAt"], state["FinishedAt"], exit_code, False, self.storage.store,
        )
        result.update(state=receipt["status"], native_exit_code=exit_code, receipt=receipt)
        self.persist(result_path, result)
        self.cleanup(directory, result)
        return result

    def status(self, job_id):
        path = self.storage.root / "jobs" / job_id
        if path.resolve() != path or not (path / "intent.json").is_file():
            raise ValueError("Unknown SSH request ID in the configured storage profile")
        return self.observe(path, read_record(path / "intent.json"))

    def submit(self, job_id, body):
        job = body["job"]
        manifest = job["manifest"]
        if job["profile"] != "ssh-r" or manifest.get("output_mode") != "reference":
            raise ValueError("Detached SSH jobs require managed R with referenced outputs")
        identity = {
            "manifest_sha256": sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=True).encode()).hexdigest(),
            "name": body["name"],
            "environment_id": body["expected_environment_id"],
        }
        directory = job_directory(job_directory(self.storage.root, "jobs"), job_id)
        intent_path = directory / "intent.json"
        if intent_path.is_file():
            intent = read_record(intent_path)
            if any(intent[key] != value for key, value in identity.items()):
                raise ValueError("This request ID is bound to a different job or environment")
            return self.observe(directory, intent)
        selection = self.runtime.select(body["lock"])
        if selection["route"] != "docker" or selection["environment_id"] != identity["environment_id"]:
            raise ValueError("Prepare the approved Docker R environment before submitting")
        if self.runtime.docker_output("container", "ls", "--quiet", "--filter", f"label={SCOPE_LABEL}={self.scope}"):
            raise ValueError("This storage profile already has an active detached job")
        work = directory / "work"
        if work.exists():
            if work.is_symlink():
                raise ValueError("The job work directory must be private")
            shutil.rmtree(work)
        with TemporaryDirectory(prefix=".stage-", dir=directory) as staging:
            self.stage(Path(staging), manifest, job["files"], self.storage.stage, profile="ssh-r")
            Path(staging).rename(work)
        intent = {**identity, "manifest": manifest, "image_id": selection["image_id"],
                  "r_version": selection["r_version"]}
        # A retry after this point reconciles Docker state and never repeats container start.
        self.persist(intent_path, intent)
        try:
            native_id = self.runtime.create_container(
                selection, work, manifest, self.runtime.output_limit, self.name(job_id),
                labels=("--label", f"{REQUEST_LABEL}={job_id}", "--label", f"{SCOPE_LABEL}={self.scope}"), detached=True,
            )
            self.persist(directory / "container.json", {"native_id": native_id})
            if self.inspect(job_id, intent, native_id) is None:
                return self.snapshot(job_id, intent, native_id)
            self.runtime.docker_output("container", "start", native_id)
        except ValueError:
            return self.observe(directory, intent)
        return self.snapshot(job_id, intent, native_id, "submitted")
