# Compare copper temperatures with an agent and HPC MCP

The pilot compares the same 131,072-atom periodic copper crystal at initial
temperatures of 300, 600, and 900 K. Each run uses the Foiles EAM potential,
two MPI ranks, and 140 steps of 2 fs. LAMMPS records temperature, energy
and pressure at steps 0, 70 and 140. [Copper model and prior benchmark](README.md)

## Recipe to result

The operator stages one trusted recipe named `copper-nve-v1`. The
recipe and its approved input files live in `recipes/copper-nve-v1/`
under the configured job workspace. The descriptor pins each input
hash, the worker resources, and the integer range for `temperature_k`.

1. `hpc_slurm_preflight` checks the configured Slurm profile.
   `hpc_list_recipes` reports the available recipe, bounds and resource request.
2. `hpc_prepare_recipe` validates parameters, renders the existing job
   manifest, verifies the approved inputs, and returns its content-addressed path.
3. `hpc_slurm_submit` validates the manifest again. A repeated UUID with the
   same manifest resolves to the original allocation.
4. `hpc_slurm_status` returns terminal accounting and the verified receipt.
   `hpc_slurm_read_json` returns a declared JSON object with its artifact digest.

## CIMAT results

Hermes Agent with Claude Sonnet 4.6 discovered the single recipe, prepared
three manifests and completed the comparison through HPC MCP. The final
temperatures are the samples at step 140, rounded to three decimals.

| Initial temperature (K) | Native Slurm job ID | Temperature at step 140 (K) |
|---:|---:|---:|
| 300 | 1 | 161.774 |
| 600 | 2 | 317.395 |
| 900 | 3 | 468.340 |

The agent issued four submit calls for the three UUIDs. Its repeated 300 K
submission returned native job ID 1. Independent Slurm accounting showed
one completed allocation per UUID, with two CPUs and exit code 0:0 each.
All three thermodynamic reports agreed with separately executed native
references. [Agent trace](evidence/cimat-hermes-copper-sweep-20261124.jsonl) · [Verified record](evidence/cimat-hermes-copper-sweep-20261124.json)

## Reproduce

For an end-to-end command that builds the full image, runs Hermes and
verifies the comparison, follow the [release installation](../../INSTALL.md).
The steps below describe how to connect the fixture to an existing profile.

Build the base [copper image](README.md#reproduce) from a committed checkout,
then build the recipe overlay.

```sh
revision=$(git rev-parse HEAD)
image=polisplexity-hpc/mpi-sweep:local
git archive "$revision" hpc_mcp cases/mpi-copper/docker/Dockerfile.sweep \
  cases/mpi-copper/run.py cases/mpi-copper/in.copper tools/audit_copper_sweep.py |
  docker build --file cases/mpi-copper/docker/Dockerfile.sweep \
    --label "org.opencontainers.image.revision=$revision" --tag "$image" -
```

Use an isolated profile with a configured model and the [Hermes recorder
setup](CANCELLATION.md#reproduce). Choose two physical cores on one node.
Configure the recorder to wrap the following backend command and capture
its stderr separately. Replace the UUID arguments with three fresh UUIDs.

```sh
POLISPLEXITY_SLURM_TEST_CPUS=2 POLISPLEXITY_SLURM_TEST_CPUSET="$cpu_ids" \
  bash cases/portable-python/docker/check.sh "$image" /opt/polis-venv/bin/python \
  -m tools.audit_copper_sweep "$id_300" "$id_600" "$id_900"
```

Expose the six tools above in the profile's `include` list. Ask Hermes
to check the profile, discover the recipe and prepare and run the three
temperatures with their UUIDs. Ask it to repeat the exact 300 K submission
before submitting the other two. After success, use the JSON read tool to
report the native job ID, final temperature to three decimals, and artifact
digest for each temperature. Capture one JSON object with a `runs`
array and a `retry` object. Each result has `temperature_k`, `native_id`,
`final_temperature_k` and `artifact_sha256`. The retry object has the
repeated request's `temperature_k` and `native_id`.

The audit process emits `SWEEP_AUDIT` followed by a JSON record from
Slurm accounting. Run the same container command with `--native` in
place of the UUIDs to produce the reference results. To verify a fresh run,
place the UUIDs keyed by temperature string under `request_ids`, the audit
object under `audit`, and the native comparison under `native_reference`.
Pass that record, the trace, and the agent answer to the verifier. The
checked-in record includes the structured answer.

```sh
stem=cases/mpi-copper/evidence/cimat-hermes-copper-sweep-20261124
python3 -m tools.verify_agent_copper_sweep \
  --trace "$stem.jsonl" --answer "$stem.json" --record "$stem.json"
```
