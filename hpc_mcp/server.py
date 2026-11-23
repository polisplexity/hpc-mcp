"""Stdio entry point for the portable job contract."""

import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import JOB_ROOT, SSH_ALIAS, describe, prepare, run
from .slurm import SlurmProfile


server = FastMCP("Polisplexity HPC MCP")
DirectProfile = Literal["local", "ssh"]
Profile = Literal["local", "ssh", "slurm"]


def prepare_from_workspace(manifest: str, profile: str):
    root = os.getenv(JOB_ROOT)
    if not root:
        raise ValueError("Set POLISPLEXITY_HPC_JOB_ROOT to a trusted job workspace")
    return prepare(Path(root), manifest, profile)


@server.tool()
def hpc_prepare(manifest: str, profile: Profile = "local") -> dict[str, Any]:
    """Validate a manifest under the configured workspace and report its identity and limits."""
    return describe(prepare_from_workspace(manifest, profile))


@server.tool()
def hpc_run(manifest: str, profile: DirectProfile = "local") -> dict[str, Any]:
    """Execute a trusted workspace job synchronously and return its receipt and artifact bytes."""
    return run(prepare_from_workspace(manifest, profile), os.getenv(SSH_ALIAS))


@server.tool()
def hpc_slurm_preflight() -> dict[str, Any]:
    """Inspect the authorized Slurm profile and its configured partition."""
    return SlurmProfile.configured().preflight()


@server.tool()
def hpc_slurm_submit(manifest: str, request_id: str) -> dict[str, Any]:
    """Queue a trusted workspace job. Reuse the same UUID to reconcile an interrupted submit."""
    profile = SlurmProfile.configured()
    return profile.submit(prepare_from_workspace(manifest, "slurm"), request_id)


@server.tool()
def hpc_slurm_status(request_id: str) -> dict[str, Any]:
    """Find a submitted job by its request UUID and return verified results when available."""
    return SlurmProfile.configured().status(request_id)


if __name__ == "__main__":
    server.run()
