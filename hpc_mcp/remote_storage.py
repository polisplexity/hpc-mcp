"""Stage approved node data and retain addressed outputs in private SSH storage."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile


@contextmanager
def open_storage_file(root, path):
    # Walk relative to open directory descriptors so symlinks cannot redirect a read.
    with ExitStack() as stack:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(root, flags)
        stack.callback(os.close, directory)
        for part in path.parts[:-1]:
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Node storage references must identify regular files")
            yield stream, info.st_size


def hash_stream(stream, limit, destination=None):
    checksum = sha256()
    size = 0
    while block := stream.read(1024 * 1024):
        size += len(block)
        if size > limit:
            raise ValueError("File exceeds its declared or supported size")
        checksum.update(block)
        if destination is not None:
            destination.write(block)
    return size, checksum.hexdigest()


def publish_blob(directory, temporary, size, checksum):
    temporary.flush()
    os.fsync(temporary.fileno())
    try:
        os.link(temporary.name, directory / checksum)
    except FileExistsError:
        with open_storage_file(directory, Path(checksum)) as (existing, existing_size):
            if existing_size != size or hash_stream(existing, size) != (size, checksum):
                raise ValueError("Existing file failed integrity verification")
    else:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class RemoteStorage:
    def __init__(self, root, reference_prefix, output_limit):
        self.root = root
        self.reference_prefix = reference_prefix
        self.output_limit = output_limit

    def stage(self, item, destination):
        expected_size = item["size_bytes"]
        try:
            with open_storage_file(self.root, Path("datasets") / item["source"]) as (source, initial_size):
                if initial_size != expected_size:
                    raise ValueError("Node input size differs from the manifest")
                with destination.open("xb") as target:
                    size, checksum = hash_stream(source, expected_size, target)
        except OSError:
            raise ValueError("The declared node input could not be read or staged") from None
        if size != expected_size or checksum != item["sha256"]:
            raise ValueError("Node input size or digest differs from the manifest")

    def store(self, job_root, name):
        with ExitStack() as stack:
            try:
                source, expected_size = stack.enter_context(open_storage_file(job_root, Path(name)))
            except (OSError, ValueError):
                return None
            if expected_size > self.output_limit:
                return None
            objects = self.root / "objects"
            objects.mkdir(mode=0o700, exist_ok=True)
            if objects.is_symlink() or not objects.is_dir():
                raise ValueError("The artifact directory must be a regular directory")
            with NamedTemporaryFile(dir=objects, prefix=".staging-") as temporary:
                size, checksum = hash_stream(source, expected_size, temporary)
                if size != expected_size:
                    raise ValueError("Job output changed during storage")
                publish_blob(objects, temporary, size, checksum)
        return {"path": name, "size_bytes": size, "sha256": checksum,
                "reference": self.reference_prefix + checksum}

    def verify(self, reference, destination=None):
        checksum = reference.removeprefix(self.reference_prefix)
        if reference == checksum or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Use a valid HPC artifact reference")
        try:
            with open_storage_file(self.root, Path("objects") / checksum) as (stream, size):
                if size > self.output_limit or hash_stream(stream, size, destination) != (size, checksum):
                    raise ValueError("The stored artifact failed integrity verification")
        except OSError:
            raise ValueError("The referenced artifact is unavailable in this storage profile") from None
        return {"reference": reference, "sha256": checksum, "size_bytes": size, "verified": True}
