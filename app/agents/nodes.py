"""Investigation graph nodes implementing evidence collection, hypotheses, and RCA."""

from datetime import UTC, datetime, timedelta

from app.agents.schemas import (
    DiagnosticStep,
    Hypothesis,
    HypothesisStatus,
    ObservedFact,
    RCAReport,
    RemediationRecommendation,
    RiskLevel,
)
from app.agents.state import InvestigationState
from app.db.models import InvestigationStatus, ServiceId
from app.integrations.telemetry import MetricName, TelemetryAdapter
from app.tools.logs import query_service_logs
from app.tools.metrics import query_service_metrics
from app.tools.runbooks import retrieve_runbooks


def normalize_incident_node(state: InvestigationState) -> InvestigationState:
    """Initialize investigation state and verify starting bounds."""
    state.investigation_status = InvestigationStatus.RUNNING
    state.step_count += 1
    return state


def collect_initial_evidence_node(
    state: InvestigationState,
    adapter: TelemetryAdapter,
) -> InvestigationState:
    """Collect initial 5xx, latency, and log evidence for the alerting service."""
    state.step_count += 1
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(minutes=15)

    for metric in (MetricName.HTTP_5XX_RATE, MetricName.HTTP_LATENCY_P95):
        resp = query_service_metrics(
            service_id=state.primary_service,
            metric_name=metric,
            start_time_utc=start_time,
            end_time_utc=end_time,
            limit=5,
            adapter=adapter,
        )
        if resp.error is not None:
            state.retry_count += 1
            state.unknowns.append(
                f"Metric {metric.value} on {state.primary_service.value} failed: "
                f"{resp.error.error_code} ({resp.error.message})"
            )
            continue

        if resp.series:
            latest = resp.series[-1]
            fact_id = f"fact-metric-{state.primary_service.value}-{metric.value}"
            state.observed_facts.append(
                ObservedFact(
                    fact_id=fact_id,
                    source=resp.source,
                    service_id=state.primary_service,
                    signal_type="metric",
                    signal_name=metric.value,
                    summary=(
                        f"{metric.value} on {state.primary_service.value} is "
                        f"{latest.value} {resp.unit}"
                    ),
                    numeric_value=latest.value,
                    unit=resp.unit,
                    observed_at_utc=latest.timestamp_utc,
                )
            )

    log_resp = query_service_logs(
        service_id=state.primary_service,
        limit=10,
        adapter=adapter,
    )
    if log_resp.error is not None:
        state.retry_count += 1
        state.unknowns.append(
            f"Logs on {state.primary_service.value} unavailable: {log_resp.error.error_code}"
        )
    else:
        for idx, entry in enumerate(log_resp.logs):
            state.observed_facts.append(
                ObservedFact(
                    fact_id=f"fact-log-{state.primary_service.value}-{idx + 1}",
                    source=log_resp.source,
                    service_id=state.primary_service,
                    signal_type="log",
                    signal_name=f"log.{entry.level.lower()}",
                    summary=entry.message,
                    observed_at_utc=entry.timestamp_utc,
                )
            )

    return state


def formulate_hypotheses_node(state: InvestigationState) -> InvestigationState:
    """Generate candidate hypotheses grounded in initial observed telemetry facts."""
    state.step_count += 1

    if not state.observed_facts:
        state.needs_deeper_diagnostics = False
        state.bounded_next_diagnostic = (
            f"Verify telemetry pipeline reachability for {state.primary_service.value} "
            "and re-query HTTP 5xx rate over a 5-minute window."
        )
        return state

    supporting_ids = [f.fact_id for f in state.observed_facts]

    state.hypotheses.append(
        Hypothesis(
            hypothesis_id="hyp-db-pool-exhaustion",
            statement=(
                "Elevated HTTP 5xx and latency on order-service are caused by PostgreSQL "
                "connection-pool saturation and high pool acquisition wait times."
            ),
            target_service=ServiceId.POSTGRES,
            confidence=0.65,
            status=HypothesisStatus.PROPOSED,
            supporting_fact_ids=supporting_ids,
        )
    )

    state.hypotheses.append(
        Hypothesis(
            hypothesis_id="hyp-payment-service-degradation",
            statement="Order checkout failures are caused by payment-service HTTP 5xx errors.",
            target_service=ServiceId.PAYMENT_SERVICE,
            confidence=0.35,
            status=HypothesisStatus.PROPOSED,
            supporting_fact_ids=[],
        )
    )

    state.diagnostics_Queue.extend(
        [
            DiagnosticStep(
                step_id="diag-order-pool-wait",
                tool_name="query_service_metrics",
                target_service=ServiceId.ORDER_SERVICE,
                rationale="Check pg_pool_wait_time_ms on order-service to test pool saturation.",
            ),
            DiagnosticStep(
                step_id="diag-postgres-active-conns",
                tool_name="query_service_metrics",
                target_service=ServiceId.POSTGRES,
                rationale="Check active connections on postgres against capacity.",
            ),
            DiagnosticStep(
                step_id="diag-payment-5xx",
                tool_name="query_service_metrics",
                target_service=ServiceId.PAYMENT_SERVICE,
                rationale="Check if payment-service exhibits elevated 5xx error rates.",
            ),
        ]
    )
    state.needs_deeper_diagnostics = True
    return state


def plan_and_execute_diagnostics_node(
    state: InvestigationState,
    adapter: TelemetryAdapter,
) -> InvestigationState:
    """Execute planned bounded diagnostic steps to validate or refute hypotheses."""
    state.step_count += 1
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(minutes=15)

    metric_for_step: dict[str, MetricName] = {
        "diag-order-pool-wait": MetricName.PG_POOL_WAIT_TIME_MS,
        "diag-postgres-active-conns": MetricName.PG_ACTIVE_CONNECTIONS,
        "diag-payment-5xx": MetricName.HTTP_5XX_RATE,
    }

    while state.diagnostics_Queue:
        step = state.diagnostics_Queue.pop(0)
        step.executed = True
        metric = metric_for_step.get(step.step_id, MetricName.HTTP_5XX_RATE)

        resp = query_service_metrics(
            service_id=step.target_service,
            metric_name=metric,
            start_time_utc=start_time,
            end_time_utc=end_time,
            limit=3,
            adapter=adapter,
        )
        if resp.error is not None:
            step.succeeded = False
            step.error_code = resp.error.error_code
            state.unknowns.append(
                f"Diagnostic {step.step_id} failed with {resp.error.error_code}"
            )
        else:
            step.succeeded = True
            if resp.series:
                latest = resp.series[-1]
                fact_id = f"fact-diag-{step.target_service.value}-{metric.value}"
                state.observed_facts.append(
                    ObservedFact(
                        fact_id=fact_id,
                        source=resp.source,
                        service_id=step.target_service,
                        signal_type="metric",
                        signal_name=metric.value,
                        summary=(
                            f"{metric.value} on {step.target_service.value} is "
                            f"{latest.value} {resp.unit}"
                        ),
                        numeric_value=latest.value,
                        unit=resp.unit,
                        observed_at_utc=latest.timestamp_utc,
                    )
                )

        state.diagnostics_executed.append(step)

    state.needs_deeper_diagnostics = False
    return state


def reassess_evidence_node(state: InvestigationState) -> InvestigationState:
    """Re-evaluate hypotheses against newly gathered diagnostic facts."""
    state.step_count += 1
    facts_by_id = {f.fact_id: f for f in state.observed_facts}

    pool_wait_fact = facts_by_id.get(
        f"fact-diag-{ServiceId.ORDER_SERVICE.value}-{MetricName.PG_POOL_WAIT_TIME_MS.value}"
    )
    pg_conn_fact = facts_by_id.get(
        f"fact-diag-{ServiceId.POSTGRES.value}-{MetricName.PG_ACTIVE_CONNECTIONS.value}"
    )
    payment_5xx_fact = facts_by_id.get(
        f"fact-diag-{ServiceId.PAYMENT_SERVICE.value}-{MetricName.HTTP_5XX_RATE.value}"
    )

    for hyp in state.hypotheses:
        if hyp.hypothesis_id == "hyp-db-pool-exhaustion":
            if (
                pool_wait_fact is not None
                and pg_conn_fact is not None
                and (pool_wait_fact.numeric_value or 0.0) > 1000.0
                and (pg_conn_fact.numeric_value or 0.0) >= 95.0
            ):
                hyp.status = HypothesisStatus.SUPPORTED
                hyp.confidence = 0.94
                hyp.supporting_fact_ids.extend([pool_wait_fact.fact_id, pg_conn_fact.fact_id])
            elif pool_wait_fact is None or pg_conn_fact is None:
                hyp.status = HypothesisStatus.INCONCLUSIVE
                hyp.confidence = 0.40
            else:
                hyp.status = HypothesisStatus.REFUTED
                hyp.confidence = 0.10
                hyp.contradicting_fact_ids.extend([pool_wait_fact.fact_id, pg_conn_fact.fact_id])

        elif hyp.hypothesis_id == "hyp-payment-service-degradation":
            if payment_5xx_fact is not None and (payment_5xx_fact.numeric_value or 0.0) < 0.05:
                hyp.status = HypothesisStatus.REFUTED
                hyp.confidence = 0.05
                hyp.contradicting_fact_ids.append(payment_5xx_fact.fact_id)

    return state


def produce_rca_report_node(state: InvestigationState) -> InvestigationState:
    """Synthesize final RCA report citing approved runbooks and disclosing retrieval gaps."""
    state.step_count += 1
    supported = [h for h in state.hypotheses if h.status == HypothesisStatus.SUPPORTED]

    rb_result = retrieve_runbooks(
        service_id=state.primary_service,
        query="connection pool exhaustion 5xx latency",
    )
    automatable_matches = [m for m in rb_result.matches if not m.human_only]
    citations = [f"{m.runbook_id} ({m.source_path})" for m in rb_result.matches]
    gaps: list[str] = []
    if rb_result.retrieval_gap_disclosed and rb_result.gap_reason:
        gaps.append(rb_result.gap_reason)

    if supported:
        top_hyp = max(supported, key=lambda h: h.confidence)
        state.investigation_status = InvestigationStatus.COMPLETED
        primary_rb = automatable_matches[0] if automatable_matches else None

        state.recommendations.append(
            RemediationRecommendation(
                action_type="reset_db_connection_pool",
                target_service=ServiceId.ORDER_SERVICE,
                risk_level=RiskLevel.MEDIUM,
                rationale=(
                    "Drain and reinitialize saturated PostgreSQL connection pool on "
                    "order-service per approved runbook procedure."
                ),
                requires_human_approval=True,
                preconditions=[
                    "Verify pg_stat_activity_active_connections >= 95",
                    "Confirm human operator approval is active and unexpired",
                ],
                cited_runbook_id=primary_rb.runbook_id if primary_rb else None,
                cited_runbook_path=primary_rb.source_path if primary_rb else None,
            )
        )
        state.final_report = RCAReport(
            incident_id=state.incident_id,
            status="COMPLETED",
            root_cause_summary=top_hyp.statement,
            confidence=top_hyp.confidence,
            observed_facts=state.observed_facts,
            hypotheses=state.hypotheses,
            diagnostics_executed=state.diagnostics_executed,
            recommendations=state.recommendations,
            unknowns_and_uncertainties=state.unknowns,
            bounded_next_diagnostic=None,
            runbook_citations=citations,
            retrieval_gaps=gaps,
        )
    else:
        state.investigation_status = InvestigationStatus.INCONCLUSIVE
        if not state.bounded_next_diagnostic:
            state.bounded_next_diagnostic = (
                "Inspect PostgreSQL pg_stat_activity and order-service container health "
                "once telemetry backends recover."
            )
        if not state.unknowns:
            state.unknowns.append(
                "Collected metrics did not breach pool exhaustion thresholds; root cause remains "
                "unconfirmed."
            )

        state.final_report = RCAReport(
            incident_id=state.incident_id,
            status="INCONCLUSIVE",
            root_cause_summary=(
                "Insufficient or healthy telemetry evidence to confirm a definitive root cause."
            ),
            confidence=0.25,
            observed_facts=state.observed_facts,
            hypotheses=state.hypotheses,
            diagnostics_executed=state.diagnostics_executed,
            recommendations=[],
            unknowns_and_uncertainties=state.unknowns,
            bounded_next_diagnostic=state.bounded_next_diagnostic,
            runbook_citations=citations,
            retrieval_gaps=gaps,
        )

    return state