"""Check Hermes recipe preparation, Slurm allocation identity and copper results."""

import argparse
import base64
import json
from pathlib import Path
from uuid import UUID

from hpc_mcp.client import verify_receipt
from hpc_mcp.worker import canonical, digest
from tools.verify_agent_receipt import claims_with_fields, exchanges, require


TEMPERATURES = ("300", "600", "900")
RECIPE = "copper-nve-v1"
OUTPUT = "copper-result.json"
CLAIMS_FIELDS = {"runs", "retry"}
TOLERANCES = {"temperature_k": 0.002, "potential_ev_per_atom": 1e-6,
              "total_ev_per_atom": 1e-6, "pressure_bar": 0.02}


def expected_manifest(spec, temperature):
    manifest = spec["job"]
    require(manifest["argv"] == ["2", "32", "140", "70", "temperature", {"parameter": "temperature_k"}]
            and manifest["outputs"] == [OUTPUT] and spec["profile"] == "slurm", "Unexpected copper recipe")
    return {**manifest, "argv": [*manifest["argv"][:-1], temperature]}


def reference_differences(artifact, native, temperature):
    require(artifact["lammps_version"] == native["lammps_version"], "The native comparison changed LAMMPS")
    for report in (artifact, native):
        require((report["atoms"], report["ranks"], report["pinned_cpus"], report["steps"]) == (131072, 2, 2, 140),
                "The simulation dimensions or MPI allocation changed")
        require([item["step"] for item in report["thermo"]] == [0, 70, 140], "Thermodynamic samples are missing")
        initial = report["thermo"][0]
        require(abs(initial["temperature_k"] - int(temperature)) <= TOLERANCES["temperature_k"],
                "Initial temperature differs from the recipe request")
        require(all(abs(row["total_ev_per_atom"] - initial["total_ev_per_atom"]) <= 2e-3
                    for row in report["thermo"]), "Total energy deviates from the initial NVE state")
    maxima = dict.fromkeys(TOLERANCES, 0.0)
    for observed, expected in zip(artifact["thermo"], native["thermo"], strict=True):
        for name, tolerance in TOLERANCES.items():
            gap = abs(observed[name] - expected[name])
            require(0 <= gap <= tolerance, f"{temperature} K differs from native for {name}")
            maxima[name] = max(maxima[name], gap)
    return maxima


def verify(trace, answer, record):
    requests = record["request_ids"]
    require(set(requests) == set(TEMPERATURES) and len(set(requests.values())) == 3, "Expected three unique UUIDs")
    inverse = {}
    for temperature, request in requests.items():
        require(str(UUID(request)) == request, "Expected a canonical request UUID")
        inverse[request] = temperature
    spec = record["audit"]["recipe"]
    require(spec["recipe"] == RECIPE and spec["parameters"] == {"temperature_k": {"minimum": 300, "maximum": 900}},
            "Unexpected recipe or parameter bounds")
    manifests = {temperature: expected_manifest(spec, temperature) for temperature in TEMPERATURES}
    prepared, submissions, native_ids, terminals, results = {}, {}, {}, {}, {}
    names = []
    for name, args, response in exchanges(trace):
        if name == "hpc_slurm_preflight":
            require(not args and response["partition_visible"] and response["account_configured"],
                    "Slurm preflight did not establish the test profile")
        elif name == "hpc_list_recipes":
            expected = {key: spec[key] for key in ("recipe", "description", "profile", "parameters")}
            require(not args and response["recipes"] == [{**expected, "resources": spec["job"]["resources"]}],
                    "The agent discovered a different recipe")
        elif name == "hpc_prepare_recipe":
            temperature = str(args["parameters"]["temperature_k"])
            require(args == {"recipe": RECIPE, "parameters": {"temperature_k": int(temperature)}}
                    and temperature not in prepared and "hpc_list_recipes" in names, "Unexpected preparation")
            identity = digest(canonical(manifests[temperature]))
            require(response["manifest_sha256"] == identity
                    and response["manifest"] == f"recipes/{RECIPE}/{identity}"
                    and response["parameters"] == args["parameters"]
                    and response["resources"] == spec["job"]["resources"]
                    and response["profile"] == "slurm", "Prepared manifest differs from the recipe")
            prepared[temperature] = response
        elif name in {"hpc_slurm_submit", "hpc_slurm_status", "hpc_slurm_read_json"}:
            request = args["request_id"]
            temperature = inverse[request]
            require(response["job_id"] == request, "The reply belongs to a different UUID")
            if name == "hpc_slurm_submit":
                require(args == {"request_id": request, "manifest": prepared[temperature]["manifest"]},
                        "Agent submitted a different manifest")
                native_id = response["native_id"]
                require(isinstance(native_id, str) and native_id.isascii() and native_id.isdecimal(),
                        "Slurm did not identify the allocation")
                if temperature not in native_ids:
                    require(response["state"] == "submitted", "The first submission must be acknowledged")
                    native_ids[temperature] = native_id
                require(native_ids[temperature] == native_id, "Repeating a UUID changed the Slurm job ID")
                submissions[temperature] = submissions.get(temperature, 0) + 1
                if temperature != "300":
                    require(submissions.get("300") == 2, "The agent must repeat 300 K before the other submissions")
            elif name == "hpc_slurm_status":
                require(args == {"request_id": request} and response["native_id"] == native_ids[temperature],
                        "Status targeted a different allocation")
                if response["state"] == "succeeded":
                    require(response["native_state"] == "COMPLETED" and response["native_exit_code"] == "0:0",
                            "Slurm did not record a successful completion")
                    receipt = response["receipt"]
                    verify_receipt(receipt, {"profile": "slurm", "manifest": manifests[temperature]})
                    require(receipt["job_id"] == request and receipt["native_id"] == native_ids[temperature]
                            and receipt["status"] == "succeeded" and receipt["exit_code"] == 0,
                            "Result receipt disagrees with the scheduler")
                    terminals[temperature] = receipt
            else:
                require(args == {"request_id": request, "path": OUTPUT} and temperature not in results,
                        "Unexpected JSON artifact retrieval")
                (artifact,) = terminals[temperature]["artifacts"]
                require(response["native_id"] == native_ids[temperature] and response["path"] == artifact["path"] == OUTPUT
                        and response["sha256"] == artifact["sha256"]
                        and response["data"] == json.loads(base64.b64decode(artifact["base64"], validate=True)),
                        "The JSON tool differs from the verified result receipt")
                results[temperature] = response
        else:
            raise ValueError(f"Unexpected agent tool: {name}")
        names.append(name)

    require("hpc_slurm_preflight" in names and submissions == {"300": 2, "600": 1, "900": 1}
            and set(results) == set(TEMPERATURES), "The agent did not complete the three runs and repeated submission")
    require(len(set(native_ids.values())) == 3, "Temperatures did not receive distinct allocations")
    expected_rows = [[native_ids[t], f"polishpc-{UUID(requests[t]).hex}", "COMPLETED", "2", "0:0"]
                     for t in TEMPERATURES]
    require(sorted(record["audit"]["accounting"]) == sorted(expected_rows),
            "Native accounting must show exactly one successful allocation per UUID")
    expected = []
    verified_runs = []
    for temperature in TEMPERATURES:
        artifact = results[temperature]["data"]
        native = record["native_reference"][temperature]
        differences = reference_differences(artifact, native, temperature)
        final = artifact["thermo"][-1]
        row = {"temperature_k": int(temperature), "native_id": native_ids[temperature],
               "final_temperature_k": round(final["temperature_k"], 3),
               "artifact_sha256": results[temperature]["sha256"]}
        expected.append(row)
        verified_runs.append({**row, "max_difference_from_native": differences})
    claims = claims_with_fields(answer, CLAIMS_FIELDS)
    retry = {"temperature_k": 300, "native_id": native_ids["300"]}
    require(sorted(claims["runs"], key=lambda row: row["temperature_k"]) == expected and claims["retry"] == retry,
            "Agent's final comparison differs from the verified results or repeated-submit response")
    return {"runs": verified_runs, "retry": retry, "slurm_allocations": len(expected_rows), "tool_calls": names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--answer", required=True, type=Path)
    parser.add_argument("--record", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.trace, args.answer, json.loads(args.record.read_bytes()))
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"Agent sweep evidence rejected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
