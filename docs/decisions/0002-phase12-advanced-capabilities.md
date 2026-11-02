# ADR 0002: Phase 12 Post-MVP Advanced Capabilities Evaluation

- **Status:** Evaluated & Deferred Post-MVP Baseline
- **Date:** 2026-11-02
- **Deciders:** Rasool, Mohammad

## Context
With the OpsPilot MVP (Phases 0–11) complete and verified, Phase 12 requires evaluating advanced capabilities and defining rationale, risk reviews, and measurable acceptance criteria before any production expansion.

## Evaluated Capabilities & Acceptance Criteria

| Capability | Rationale | Risk Review | Measurable Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **1. Historical Similar-Incident Retrieval (Vector RAG)** | Accelerate triage when recurring failure modes match past resolved incidents. | Stale historical root causes could bias current RCA if not re-verified against live telemetry. | Retrieval precision `@3 >= 0.85` on labeled benchmark; zero claims accepted without fresh metric confirmation. |
| **2. Parallel Read-Only Diagnostics** | Reduce investigation latency when querying multiple downstream services. | Concurrent queries could amplify load on degraded telemetry backends. | Enforce semaphore limit (`max_concurrency <= 3`) and reduce p95 RCA duration by `>= 30%` without timeout spikes. |
| **3. Canary Remediation & Automated Rollback** | Limit blast radius by applying actions to a single replica before full rollout. | Partial state divergence if canary verification window is too short. | 100% automatic rollback within 60s when canary 5xx rate exceeds baseline by `> 1%`. |
| **4. Cost & Token Budget Enforcement** | Bound token consumption and latency per incident investigation. | Premature truncation could halt complex multi-hop investigations. | Hard cap of `<= $0.05` or `15,000` tokens per incident while maintaining RCA accuracy `>= 0.90`. |