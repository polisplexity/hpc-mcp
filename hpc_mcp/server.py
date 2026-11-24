"""Stdio entry point for the portable job contract."""

import base64
import json
import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import JOB_ROOT, SSH_ALIAS, describe, prepare, run
from . import recipes
from .slurm import SlurmProfile


server = FastMCP("Polisplexity HPC MCP")
DirectProfile = Literal["local", "ssh"]
Profile = Literal["local", "ssh", "slurm"]


def workspace():
    root = os.getenv(JOB_ROOT)
    if not root:
        raise ValueError("Set POLISPLEXITY_HPC_JOB_ROOT to a trusted job workspace")
    return Path(root).resolve(strict=True)


def prepare_from_workspace(manifest: str, profile: str):
    return prepare(workspace(), manifest, profile)


@server.tool()
def hpc_prepare(manifest: str, profile: Profile = "local") -> dict[str, Any]:
    """Validate a manifest under the configured workspace and report its identity and limits."""
    return describe(prepare_from_workspace(manifest, profile))


@server.tool()
def hpc_run(manifest: str, profile: DirectProfile = "local") -> dict[str, Any]:
    """Execute a trusted workspace job synchronously and return its receipt and artifact bytes."""
    return run(prepare_from_workspace(manifest, profile), os.getenv(SSH_ALIAS))


@server.tool()
def hpc_list_recipes() -> dict[str, Any]:
    """List operator-installed recipes, parameter bounds and resource requests."""
    return {"recipes": recipes.list_recipes(workspace())}


@server.tool()
def hpc_prepare_recipe(recipe: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Prepare an approved recipe from bounded parameters and return a manifest for submission."""
    return recipes.prepare_recipe(workspace(), recipe, parameters)


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


@server.tool()
def hpc_slurm_read_json(request_id: str, path: str) -> dict[str, Any]:
    """Read a declared JSON object from a completed Slurm job's verified result receipt."""
    status = SlurmProfile.configured().status(request_id)
    if status["state"] != "succeeded" or not path.endswith(".json"):
        raise ValueError("A successful job and a declared JSON artifact are required")
    receipt = status["receipt"]
    for artifact in receipt["artifacts"]:
        if artifact["path"] == path:
            value = json.loads(base64.b64decode(artifact["base64"], validate=True))
            if not isinstance(value, dict):
                raise ValueError("The JSON artifact must contain an object")
            return {
                "job_id": status["job_id"], "native_id": status["native_id"], "path": path,
                "sha256": artifact["sha256"], "data": value,
            }
    raise ValueError("The JSON artifact is absent from the receipt")


@server.tool()
def hpc_slurm_cancel(request_id: str) -> dict[str, Any]:
    """Request cancellation of a job registered by this profile's submit UUID.

    Poll status until Slurm reports a terminal outcome. An active or unknown
    response does not confirm cancellation. Reusing the UUID preserves the job.
    """
    return SlurmProfile.configured().cancel(request_id)


if __name__ == "__main__":
    server.run()
