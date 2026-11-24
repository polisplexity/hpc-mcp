#!/bin/sh
set -eu

test_cpus=${POLISPLEXITY_SLURM_TEST_CPUS:-1}
case "$test_cpus" in
    1|2|3|4) ;;
    *) echo "Set a test CPU count between 1 and 4" >&2; exit 2 ;;
esac

wait_for() {
    log=$1
    shift
    attempt=0
    until timeout 3 "$@" >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 20 ]; then
            tail -n 30 "$log" >&2
            return 1
        fi
        sleep 1
    done
}

install -d -o munge -g munge -m 0755 /run/munge
install -d -o mysql -g mysql -m 0755 /run/mysqld
install -d -o slurm -g slurm -m 0755 /var/spool/slurmctld /var/log/slurm
install -d -m 0755 /var/spool/slurmd /etc/slurm
install -d -o polis-lab -g polis-lab -m 0700 /home/polis-lab/hpc-state
(umask 077; head -c 1024 /dev/urandom >/etc/munge/munge.key)
chown munge:munge /etc/munge/munge.key
runuser -u munge -- /usr/sbin/munged --origin=127.0.0.1

/usr/sbin/mariadbd --user=mysql --skip-networking --innodb-buffer-pool-size=64M \
    --performance-schema=OFF --max-connections=25 >/var/log/slurm/mariadb.log 2>&1 &
wait_for /var/log/slurm/mariadb.log mariadb-admin ping --silent
mariadb <<'SQL'
CREATE DATABASE pilot_accounting;
CREATE USER 'slurm'@'localhost' IDENTIFIED VIA unix_socket;
GRANT ALL ON pilot_accounting.* TO 'slurm'@'localhost';
SQL

printf 'CgroupPlugin=disabled\n' >/etc/slurm/cgroup.conf
cat >/etc/slurm/slurmdbd.conf <<'DBD'
AuthType=auth/munge
DbdHost=polis-slurm
DbdAddr=127.0.0.1
SlurmUser=slurm
LogFile=/var/log/slurm/slurmdbd.log
PidFile=/run/slurmdbd.pid
StorageType=accounting_storage/mysql
StorageHost=localhost
StorageUser=slurm
StorageLoc=pilot_accounting
DBD
chown slurm:slurm /etc/slurm/slurmdbd.conf
chmod 0600 /etc/slurm/slurmdbd.conf

cat >/etc/slurm/slurm.conf <<'SLURM'
ClusterName=polis-docker
SlurmctldHost=polis-slurm(127.0.0.1)
SlurmUser=slurm
AuthType=auth/munge
CredType=cred/munge
StateSaveLocation=/var/spool/slurmctld
SlurmdSpoolDir=/var/spool/slurmd
SlurmctldPidFile=/run/slurmctld.pid
SlurmdPidFile=/run/slurmd.pid
SlurmctldLogFile=/var/log/slurm/slurmctld.log
SlurmdLogFile=/var/log/slurm/slurmd.log
ProctrackType=proctrack/linuxproc
TaskPlugin=task/none
MpiDefault=none
ReturnToService=2
SelectType=select/cons_tres
SelectTypeParameters=CR_CPU_Memory
AccountingStorageType=accounting_storage/slurmdbd
AccountingStorageHost=127.0.0.1
AccountingStorageEnforce=associations
JobAcctGatherType=jobacct_gather/linux
SlurmdParameters=config_overrides
SLURM
printf 'NodeName=polis-slurm NodeAddr=127.0.0.1 CPUs=%s RealMemory=512 State=UNKNOWN\n' "$test_cpus" >>/etc/slurm/slurm.conf
printf 'PartitionName=pilot Nodes=polis-slurm Default=YES MaxTime=00:02:00 State=UP\n' >>/etc/slurm/slurm.conf

/usr/sbin/slurmdbd || { tail -n 30 /var/log/slurm/slurmdbd.log >&2; exit 1; }
wait_for /var/log/slurm/slurmdbd.log sacctmgr -n list cluster
sacctmgr -i add cluster polis-docker >&2
sacctmgr -i add account polis-pilot Description=Pilot Organization=Polisplexity >&2
sacctmgr -i add user polis-lab Account=polis-pilot >&2
/usr/sbin/slurmctld || { tail -n 30 /var/log/slurm/slurmctld.log >&2; exit 1; }
/usr/sbin/slurmd -N polis-slurm || { tail -n 30 /var/log/slurm/slurmd.log >&2; exit 1; }
wait_for /var/log/slurm/slurmd.log sh -c 'sinfo --noheader --format=%t | grep -qx idle'

exec runuser -u polis-lab -- env \
    POLISPLEXITY_HPC_JOB_ROOT=/opt/polisplexity/hpc-mcp/cases/portable-python \
    POLISPLEXITY_HPC_SLURM_STATE=/home/polis-lab/hpc-state \
    POLISPLEXITY_HPC_SLURM_PARTITION=pilot \
    POLISPLEXITY_HPC_SLURM_ACCOUNT=polis-pilot \
    "$@"
