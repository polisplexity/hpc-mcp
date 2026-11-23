#!/bin/sh
set -eu

printf '#!/bin/sh\nexit 101\n' >/usr/sbin/policy-rc.d
chmod 0755 /usr/sbin/policy-rc.d

cat >/tmp/polis-debian.sources <<'APT'
Types: deb
URIs: http://snapshot.debian.org/archive/debian/20261123T180000Z/
Suites: forky
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Check-Valid-Until: no
APT
mkdir /tmp/polis-empty-sources
apt_snapshot() {
    apt-get -o Dir::Etc::sourcelist=/tmp/polis-debian.sources \
        -o Dir::Etc::sourceparts=/tmp/polis-empty-sources \
        -o Acquire::Retries=1 -o Acquire::http::Timeout=25 "$@"
}

slurm_version=26.05.5-1
apt_snapshot -qq update
DEBIAN_FRONTEND=noninteractive apt_snapshot install -y -qq --no-install-recommends \
    ca-certificates mariadb-server munge procps python3-venv \
    "slurm-client=$slurm_version" "slurmctld=$slurm_version" "slurmd=$slurm_version" \
    "slurmdbd=$slurm_version" "slurm-wlm-mysql-plugin=$slurm_version"
python3 -m venv /opt/polis-venv
/opt/polis-venv/bin/pip --disable-pip-version-check install --no-cache-dir \
    --constraint /tmp/python-constraints.txt --requirement /tmp/requirements-mcp.txt
rm -f /etc/munge/munge.key /tmp/polis-debian.sources
rmdir /tmp/polis-empty-sources
apt-get clean
rm -rf /var/lib/apt/lists/*
useradd --create-home --shell /bin/sh polis-lab
