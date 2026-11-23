"""Check the CPU fixture through an actual MCP stdio connection."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from run_cpu_pilot import run_cpu_fixture


async def check(profile):
    args = [str(Path(__file__).with_name("fixture_mcp.py"))]
    env = {**os.environ}
    if profile:
        env["POLISPLEXITY_HPC_SSH_PROFILE"] = profile
    else:
        env.pop("POLISPLEXITY_HPC_SSH_PROFILE", None)
    config = StdioServerParameters(command=sys.executable, args=args, env=env)
    report = {"transport": "stdio", "runs": []}
    async with stdio_client(config) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            report["tools"] = [tool.name for tool in (await session.list_tools()).tools]
            unexpected = await session.call_tool("run_cpu_probe", {"target": "unauthorized"})
            if not unexpected.isError:
                raise ValueError("MCP allowed an out-of-scope target")
            report["invalid_target_rejected"] = True
            targets = ["local", "cimat"] if profile else ["local"]
            for target in targets:
                direct = run_cpu_fixture(target, profile)
                result = await session.call_tool("run_cpu_probe", {"target": target})
                if result.isError:
                    raise RuntimeError("MCP fixture failed")
                observed = result.structuredContent
                if observed is None and len(result.content) == 1 and result.content[0].type == "text":
                    observed = json.loads(result.content[0].text)
                if not isinstance(observed, dict):
                    raise ValueError("MCP fixture returned no JSON object")
                for key in ("target", "result", "fixture_sha256", "output_sha256"):
                    if observed[key] != direct[key]:
                        raise ValueError(f"MCP parity failed for {target}: {key}")
                report["runs"].append(observed)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-profile")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = json.dumps(asyncio.run(check(args.ssh_profile)), indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")


if __name__ == "__main__":
    main()
