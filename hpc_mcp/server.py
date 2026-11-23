"""Stdio entry point for the portable job contract."""

import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import JOB_ROOT, SSH_ALIAS, describe, prepare, run


server = FastMCP("Polisplexity HPC MCP")
Profile = Literal["local", "ssh"]


def prepare_from_workspace(manifest: str, profile: Profile):
    root = os.getenv(JOB_ROOT)
    if not root:
        raise ValueError("Set POLISPLEXITY_HPC_JOB_ROOT to a trusted job workspace")
    return prepare(Path(root), manifest, profile)


@server.tool()
def hpc_prepare(manifest: str, profile: Profile = "local") -> dict[str, Any]:
    """Validate a manifest under the configured workspace and report its identity and limits."""
    return describe(prepare_from_workspace(manifest, profile))


@server.tool()
def hpc_run(manifest: str, profile: Profile = "local") -> dict[str, Any]:
    """Execute a trusted workspace job synchronously and return its receipt and artifact bytes."""
    return run(prepare_from_workspace(manifest, profile), os.getenv(SSH_ALIAS))


if __name__ == "__main__":
    server.run()
