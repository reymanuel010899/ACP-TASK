"""AgentTrust local-dev agent runner.

A managed-subprocess supervisor that owns an agent's identity (a stable
per-agent ``keys-dir``) and its process lifecycle, so the console can Create ->
Deploy -> Manage real ``agents.provider`` processes without a terminal. See
``docs/plans/2026-07-23-002-feat-agent-runtime-lifecycle-plan.md``.

Local-dev only: binds to localhost, spawns template-controlled executables with
validated arguments, and is NOT hardened for production (no auth, no sandbox).
"""
