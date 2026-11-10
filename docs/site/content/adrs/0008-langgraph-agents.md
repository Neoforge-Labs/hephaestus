---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0008-langgraph-agents.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0008. LangGraph as the agent runtime"
---

# 0008. LangGraph as the agent runtime

## Status

Accepted. Date: 2026-11-04.

## Context

Karani and future products run agents that need checkpointing, tool use, budgets and human approval. Writing an agent runtime is not where NeoForge has an edge.

## Decision

`ai.agents` uses LangGraph as the runtime. Hephaestus supplies the Postgres checkpointer, tool registry, budget ceilings, human-approval interrupts and tracing. The module is rebuilt from Karani, not copied from DataQRL's LangGraph orchestration, which stays DataQRL's.

## Consequences

We get a maintained runtime and put our work into the wrapper that enforces budgets, approvals and tracing. We track LangGraph's API changes. `ai.agents` is Tier 3 and enters as experimental on demand.
