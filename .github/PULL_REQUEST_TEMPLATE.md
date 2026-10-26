## Summary
<!-- Concise description of what this PR changes and why -->

## Ownership
- **Accountable Owner:** `Rasool / Mohammad / Shared`
- **Affected Components:**

## Contract & Architecture Impact
- [ ] No breaking shared contract changes
- [ ] Shared contract change documented in `docs/integration-contracts.md` and coordinated

## Database & Migration Impact
- [ ] No database schema changes
- [ ] Includes Alembic migration tested for upgrade and idempotency

## Infrastructure & Configuration Impact
- [ ] No container/CI/monitoring configuration changes
- [ ] Container, healthcheck, or `.env.example` changes updated and validated

## Security Review
- [ ] Zero secrets, tokens, or private URLs committed
- [ ] Inputs/tools remain bounded and policy checks remain independent of LLM outputs

## Verification & Actual Test Results
<!-- Paste actual commands run and terminal results below -->
```text
ruff check app tests
mypy app tests
pytest -v
```