# 0010. HCP Terraform for Terraform state

## Status

Accepted. Date: 2026-11-04.

## Context

The same app must go to production from one Terraform stack, and state must be remote and locked.

## Decision

Terraform state is stored in HCP Terraform's free tier. Modules stay OpenTofu-compatible.

## Consequences

State is remote and locked on HCP Terraform's free tier. We depend on that tier's limits and terms.
