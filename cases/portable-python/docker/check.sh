#!/usr/bin/env bash
set -euo pipefail

image=polisplexity-hpc/slurm-test:local
if (( $# > 0 )); then
    image=$1
    shift
fi
stdin=()
if (( $# > 0 )); then
    stdin=(--interactive)
fi
read -r id </proc/sys/kernel/random/uuid
container="polisplexity-slurm-test-$id"
network="polisplexity-slurm-test-net-$id"
owner="org.polisplexity.slurm-test=$id"

docker network create --internal --driver bridge --label "$owner" "$network" >/dev/null
cleanup() {
    local status=$?
    trap - EXIT
    local active
    active=$(docker ps -q --filter "name=^/$container$" --filter "label=$owner") || status=1
    if [[ -n "$active" ]]; then
        docker stop --timeout 5 "$container" >/dev/null || status=1
    fi
    docker network rm "$network" >/dev/null || status=1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

timeout --foreground 180 docker run --rm --init "${stdin[@]}" --name "$container" --label "$owner" \
    --network "$network" --hostname polis-slurm --add-host polis-slurm:127.0.0.1 \
    --cpus 1 --memory 1g --memory-swap 1g --pids-limit 192 \
    --security-opt no-new-privileges --cap-drop NET_RAW "$image" "$@"
