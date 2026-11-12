# syntax=docker/dockerfile:1
# heph-mlflow: the official MLflow server plus the two drivers it lacks (the
# Postgres backend store needs psycopg2, the S3 artifact store needs boto3).
# DEV AND TEST ONLY. Maturity: experimental.
# Baked in here, not installed at container start, so booting the compose
# fragment puts no PyPI fetch on the critical path (see compose-boot.yml).
# Base is pinned by digest; the tag says what it refers to. To bump, resolve
# the new digest (docker buildx imagetools inspect <tag>) and change both.
# ghcr.io/mlflow/mlflow:v3.1.1
FROM ghcr.io/mlflow/mlflow@sha256:e8c9caf0615dd18a766091a3c37a41ecca2a00d663bc9a6d8b7417950d828114
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
    psycopg2-binary==2.9.10 boto3==1.38.46
