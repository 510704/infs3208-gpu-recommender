# Training image: runs the notebook pipeline (01 -> 03 -> 02) against the
# in-cluster Spark master. Reuses the apache/spark base so the driver has Java
# and a compatible pyspark; the notebooks are baked in because they ARE the
# training code (infra change, not an application-code change).
FROM apache/spark:3.5.1

USER root
# Pinned to the last releases that ship cp38 wheels: the base image's Python is
# 3.8, so unpinned pandas/numpy can resolve to versions with no wheel for it.
# `python3 -m pip` (not bare `pip`) is deliberate: the base's system pip has an
# old vendored `packaging` that crashes on legacy PyPI versions (e.g. pytz
# '2004d', pulled in by pandas). Upgrading pip and then calling it via
# `python3 -m pip` makes the resolution use a modern pip that skips those.
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir \
        "numpy<1.25" \
        "pandas<2.0" \
        nbconvert \
        jupyter_client \
        ipykernel \
        google-cloud-storage

COPY notebooks /work
COPY spark/jobs/*.py /jobs/

ENV PYSPARK_PYTHON=python3 \
    PYSPARK_DRIVER_PYTHON=python3 \
    PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip \
    JOBS_DIR=/jobs \
    DATA_DIR=/data

WORKDIR /work

# Sequential execution in one pod: the notebooks exchange curated/* files via
# DATA_DIR, which the Job backs with an emptyDir. Model artifacts are uploaded to
# the bucket by the notebooks themselves, so serving picks them up on rollout.
CMD ["bash", "-lc", "\
  jupyter nbconvert --to notebook --execute --allow-errors --ExecutePreprocessor.timeout=1800 --output-dir /tmp/out 01_features.ipynb && \
  jupyter nbconvert --to notebook --execute --allow-errors --ExecutePreprocessor.timeout=1800 --output-dir /tmp/out 03_gpu_catalog.ipynb && \
  jupyter nbconvert --to notebook --execute --allow-errors --ExecutePreprocessor.timeout=1800 --output-dir /tmp/out 02_models.ipynb"]
