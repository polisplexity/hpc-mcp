"""Stdio MCP for the fixed CPU admission fixture."""

import os
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from run_cpu_pilot import run_cpu_fixture


server = FastMCP("Polisplexity HPC CPU fixture")


@server.tool()
def run_cpu_probe(target: Literal["local", "cimat"]) -> dict[str, Any]:
    """Run the fixed integer CPU probe on local or on the configured CIMAT target."""
    return run_cpu_fixture(target, os.getenv("POLISPLEXITY_HPC_SSH_PROFILE"))


if __name__ == "__main__":
    server.run()
