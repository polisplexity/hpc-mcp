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


class RemoteStorage:
    def __init__(self, root, reference_prefix, inline_limit):
        self.root = root
        self.reference_prefix = reference_prefix
        self.inline_limit = inline_limit

    def stage(self, item, destination):
        expected_size = item["size_bytes"]
        checksum = sha256()
        size = 0
        try:
            with open_storage_file(self.root, Path("datasets") / item["source"]) as (source, initial_size):
                if initial_size != expected_size:
                    raise ValueError("Node input size differs from the manifest")
                with destination.open("xb") as target:
                    while block := source.read(1024 * 1024):
                        size += len(block)
                        if size > expected_size:
                            raise ValueError("Node input changed while staging")
                        target.write(block)
                        checksum.update(block)
        except OSError:
            raise ValueError("The declared node input could not be read or staged") from None
        if size != expected_size or checksum.hexdigest() != item["sha256"]:
            raise ValueError("Node input size or digest differs from the manifest")

    def store(self, data, checksum):
        objects = self.root / "objects"
        objects.mkdir(mode=0o700, exist_ok=True)
        if objects.is_symlink() or not objects.is_dir():
            raise ValueError("The artifact directory must be a regular directory")
        reference = self.reference_prefix + checksum
        with NamedTemporaryFile(dir=objects, prefix=".staging-") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            try:
                os.link(temporary.name, objects / checksum)
            except FileExistsError:
                self.verify(reference)
            else:
                descriptor = os.open(objects, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        return reference

    def verify(self, reference):
        checksum = reference.removeprefix(self.reference_prefix)
        if reference == checksum or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Use a valid HPC artifact reference")
        try:
            with open_storage_file(self.root, Path("objects") / checksum) as (stream, size):
                data = stream.read(self.inline_limit + 1)
        except OSError:
            raise ValueError("The referenced artifact is unavailable in this storage profile") from None
        if len(data) != size or size > self.inline_limit or sha256(data).hexdigest() != checksum:
            raise ValueError("The stored artifact failed integrity verification")
        return {"reference": reference, "sha256": checksum, "size_bytes": size, "verified": True}
