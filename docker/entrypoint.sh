#!/usr/bin/env bash
# Start exactly one daemon in the foreground, chosen by the first argument.
set -euo pipefail
ROLE="${1:-}"

wait_for() {  # host port
  echo "[$ROLE] waiting for $1:$2 ..."
  until nc -z "$1" "$2" 2>/dev/null; do sleep 2; done
}

case "$ROLE" in
  namenode)
    if [ ! -d /data/hdfs/name/current ]; then
      echo "[namenode] formatting new HDFS namespace"
      hdfs namenode -format -force -nonInteractive -clusterId ucr-cluster
    fi
    exec hdfs namenode
    ;;
  datanode)
    wait_for namenode 9000
    exec hdfs datanode
    ;;
  hmaster)
    wait_for namenode 9000
    wait_for zookeeper 2181
    # wait until HDFS has left safe mode and a datanode is alive
    until hdfs dfsadmin -safemode get 2>/dev/null | grep -q OFF; do sleep 3; done
    hdfs dfs -mkdir -p /hbase /ucr /tmp && hdfs dfs -chmod 1777 /tmp
    exec hbase master start
    ;;
  regionserver)
    wait_for zookeeper 2181
    wait_for hmaster 16000
    exec hbase regionserver start
    ;;
  thrift)
    wait_for hmaster 16000
    exec hbase thrift start -p 9090
    ;;
  *)
    exec "$@"
    ;;
esac
