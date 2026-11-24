#!/bin/sh
set -eu

cat >/tmp/polis-mpi-debian.sources <<'APT'
Types: deb
URIs: http://snapshot.debian.org/archive/debian/20261123T180000Z/
Suites: forky
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Check-Valid-Until: no
APT
mkdir /tmp/polis-mpi-empty-sources
apt_snapshot() {
    apt-get -o Dir::Etc::sourcelist=/tmp/polis-mpi-debian.sources \
        -o Dir::Etc::sourceparts=/tmp/polis-mpi-empty-sources \
        -o Acquire::Retries=1 -o Acquire::http::Timeout=25 "$@"
}

apt_snapshot -qq update
if [ "$#" -eq 0 ]; then
    set -- gcc libc6-dev libopenmpi-dev libssl-dev openmpi-bin
fi
DEBIAN_FRONTEND=noninteractive apt_snapshot install -y -qq --no-install-recommends "$@"
rm -f /tmp/polis-mpi-debian.sources
rmdir /tmp/polis-mpi-empty-sources
apt-get clean
rm -rf /var/lib/apt/lists/*
