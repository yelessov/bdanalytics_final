# One image, several roles (namenode / datanode / hmaster / regionserver / thrift).
# Built on the official multi-arch Temurin JRE, so it runs natively on Apple Silicon
# (arm64) as well as Intel (amd64).  Each container runs ONE Java daemon.
FROM eclipse-temurin:11-jdk-jammy

ARG HADOOP_VERSION=3.3.6
ARG HBASE_VERSION=2.5.10
ARG APACHE_MIRROR=https://archive.apache.org/dist

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl procps netcat-openbsd \
 && rm -rf /var/lib/apt/lists/*

# Hadoop (HDFS daemons + hdfs CLI)
RUN curl -fsSL ${APACHE_MIRROR}/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz \
      | tar -xz -C /opt \
 && ln -s /opt/hadoop-${HADOOP_VERSION} /opt/hadoop \
 && rm -rf /opt/hadoop/share/doc

# HBase (hadoop3 build: HMaster, RegionServer, Thrift, shell, MapReduce tools)
RUN curl -fsSL ${APACHE_MIRROR}/hbase/${HBASE_VERSION}/hbase-${HBASE_VERSION}-hadoop3-bin.tar.gz \
      | tar -xz -C /opt \
 && ln -s /opt/hbase-${HBASE_VERSION}-hadoop3 /opt/hbase \
 && rm -rf /opt/hbase/docs

ENV HADOOP_HOME=/opt/hadoop \
    HADOOP_CONF_DIR=/opt/conf \
    HBASE_HOME=/opt/hbase \
    HBASE_CONF_DIR=/opt/conf \
    HBASE_MANAGES_ZK=false \
    HBASE_DISABLE_HADOOP_CLASSPATH_LOOKUP=true \
    PATH=/opt/hadoop/bin:/opt/hbase/bin:$PATH

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
