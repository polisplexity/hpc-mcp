# Verify a Slurm job with Hermes Agent

Hermes Agent 0.18.2 with Claude Sonnet 4.6 completed this case on Slurm
26.05.5 in the CIMAT Docker test environment. With the default discovery
wait of 1.5 seconds, the first model request had no tools while the
container was starting. A 45-second discovery bound let Hermes load the
three HPC MCP tools before that request. The per-server `connect_timeout`
controls the connection separately.

## Run from an isolated Hermes profile

Build the image using the [Slurm recipe](SLURM.md#reproduce-from-a-clean-checkout),
or use an existing image for that recipe. Add this MCP entry to a test Hermes
profile with a configured model. Replace the checkout and trace paths with
absolute paths. The recorder creates the trace file, so choose a fresh path
for each run.

```yaml
mcp_discovery_timeout: 45
mcp_servers:
  polisplexity_hpc:
    command: python3
    args:
      - /path/to/hpc-mcp/tools/trace_mcp.py
      - --trace
      - /path/to/test/mcp.jsonl
      - --
      - bash
      - /path/to/hpc-mcp/cases/portable-python/docker/check.sh
      - polisplexity-hpc/slurm-test:local
      - /opt/polis-venv/bin/python
      - -m
      - hpc_mcp.server
    connect_timeout: 45
    timeout: 20
    tools:
      include: [hpc_prepare, hpc_slurm_submit, hpc_slurm_status]
      resources: false
      prompts: false
```

For an authorized SSH Docker host, wrap the remote launch command in the
recorder. Keep the SSH profile local and reserve the wrapped process's
stdout for MCP. See the [Hermes MCP configuration
reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference).

Generate one request UUID and use it for submission and polling. The example
assumes an isolated profile named `hpc-test`.

```sh
request_id=$(python3 -c 'from uuid import uuid4; print(uuid4())')
query=$(cat <<EOF
Use only the HPC MCP tools. Prepare client-example/job.json with profile slurm.
Submit the same manifest with request_id $request_id. Poll hpc_slurm_status
with that UUID until a terminal receipt arrives, using at most eight polls.
Return one JSON object with state, native_id, artifact_sha256 and exit_code
from the status and worker receipt. If a successful receipt is unavailable,
return {"state":"unavailable","native_id":"","artifact_sha256":"","exit_code":-1}.
Do not simulate tool exchanges or use shell commands.
EOF
)
hermes --profile hpc-test chat --ignore-rules --quiet --max-turns 10 --source tool \
  --toolsets polisplexity_hpc --query "$query" > agent-answer.txt
python3 -m tools.verify_agent_receipt --trace /path/to/test/mcp.jsonl \
  --answer agent-answer.txt --request-id "$request_id"
```

The verifier matches JSON-RPC responses to their requests. It requires one
acknowledged submit, terminal Slurm accounting for that UUID and native job
ID, and a worker receipt with matching artifact bytes. It executes the
fixture directly and checks the coefficients against the normal equations
before comparing the agent's final claims.

For the negative case, set `enabled: false` under the server entry, use a
new UUID and provide an empty trace file to the verifier. Pass
`--expect-unavailable` to require the unavailable answer and zero tool calls.

The [observations](evidence/hermes-agent-20261123.json) include the
disabled-server case and the rejected unsupported claim. The [MCP
trace](evidence/hermes-agent-mcp-20261123.jsonl) records the successful run.
