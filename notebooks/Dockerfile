# PySpark + MLlib notebook environment.
#
# PySpark is pinned to 3.5.1 to MATCH the `apache/spark:3.5.1` cluster declared
# in docker-compose.yml. A client/server version mismatch is the single most
# common cause of a notebook that silently refuses to connect to the cluster.
#
# Pin the base image to a dated tag (for example
# jupyter/scipy-notebook:2024-10-07) once you have confirmed one that works.
# An untagged reference is used here only because it always resolves.

FROM jupyter/scipy-notebook

USER root

# Spark needs a JRE. Pinned to 17 deliberately: Spark 3.5 supports Java 8/11/17
# but NOT Java 21, and `default-jre-headless` can resolve to 21 on newer bases.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openjdk-17-jre-headless \
      procps \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Notebooks are bind-mounted here by docker-compose.
WORKDIR /home/jovyan/work
