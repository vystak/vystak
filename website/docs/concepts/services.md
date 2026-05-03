---
title: Services
sidebar_label: Services
---

# Services

Services are typed infrastructure dependencies — Postgres for sessions, Redis for cache, Qdrant for vectors.

Once `sessions` is configured (Postgres or SQLite), agents accumulate
state across turns. Long sessions can also enable
[compaction](./compaction) to keep prefill bounded.

*Detailed documentation coming soon.*
