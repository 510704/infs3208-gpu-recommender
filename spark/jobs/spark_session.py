"""SparkSession bootstrap shared by every notebook.

The environment knobs (master, driver host, shuffle partitions) are the same in
all six notebooks; keeping them here means one place to change when the cluster
topology moves (local -> Spark standalone -> Dataproc).
"""

import os

from pyspark.sql import SparkSession


def get_spark(app_name: str) -> SparkSession:
    """Return the project's Spark session with the standard configuration."""
    os.environ.setdefault('PYSPARK_SUBMIT_ARGS', '--driver-memory 2g pyspark-shell')
    return (
        SparkSession.builder
        .appName(app_name)
        .master(os.environ.get('SPARK_MASTER', 'local[*]'))
        # docker-compose sets SPARK_DRIVER_HOST=jupyter explicitly (the driver
        # runs in that container). Anywhere else - a local shell, Cloud Shell -
        # that name does not resolve and Spark fails with a Py4JJavaError, so
        # the fallback is localhost rather than "jupyter".
        .config('spark.driver.host', os.environ.get('SPARK_DRIVER_HOST', 'localhost'))
        .config('spark.hadoop.fs.permissions.umask-mode', '000')
        .config('spark.sql.shuffle.partitions', '8')
        .getOrCreate()
    )
