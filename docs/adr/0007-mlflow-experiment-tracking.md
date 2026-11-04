# 0007. Self-hosted MLflow for experiment tracking

## Status

Accepted. Date: 2026-11-04.

## Context

Research projects (SAWA, NeoRx) repeat experiment plumbing, and results must re-run from their recorded config, data hash and seed. Experiment tracking is a commodity concern.

## Decision

Experiment tracking uses self-hosted MLflow. `lab.track` wraps it so every run records config, metrics, artifacts and dataset hashes, linked to its trace. A `mlflow` Compose fragment runs the tracking server on Postgres with artifacts in SeaweedFS.

## Consequences

We adopt rather than build a tracker (CLAUDE.md rule 8), and keep our effort on provenance and reproducibility. We run a server ourselves. The wrapper keeps MLflow behind our own interface so it can be swapped later.
