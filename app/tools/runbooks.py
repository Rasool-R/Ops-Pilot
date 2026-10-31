"""Bounded Runbook RAG retrieval tool with source attribution and injection defense."""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.db.models import ServiceId

DEFAULT_RUNBOOKS_DIR = Path(__file__).resolve().parents[2] / "runbooks"
MAX_SNIPPET_CHARS = 800

_RUNBOOK_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+authorized", re.IGNORECASE),
    re.compile(r"bypass\s+policy", re.IGNORECASE),
    re.compile(r"requires_human_approval\s*=\s*false", re.IGNORECASE),
    re.compile(r"execute\s+shell", re.IGNORECASE),
)


class RunbookSnippet(BaseModel):
    """Source-attributed, sanitized runbook entry returned by the RAG tool."""

    runbook_id: str
    title: str
    source_path: str
    target_services: list[str] = Field(default_factory=list)
    human_only: bool = False
    relevance_score: float = Field(ge=0.0, le=1.0)
    sanitized_excerpt: str


class RunbookRetrievalResponse(BaseModel):
    """Structured output of a bounded runbook search including gap disclosure."""

    service_id: ServiceId
    query: str
    matches: list[RunbookSnippet] = Field(default_factory=list)
    retrieval_gap_disclosed: bool = False
    gap_reason: str | None = None


def sanitize_runbook_text(raw_text: str) -> str:
    """Neutralize prompt-injection or policy-bypass strings in untrusted runbook text."""
    cleaned = raw_text
    for pattern in _RUNBOOK_INJECTION_PATTERNS:
        cleaned = pattern.sub("[REDACTED_UNTRUSTED_RUNBOOK_DIRECTIVE]", cleaned)

    if len(cleaned) > MAX_SNIPPET_CHARS:
        return cleaned[:MAX_SNIPPET_CHARS] + "...[TRUNCATED]"
    return cleaned


def _parse_runbook_file(file_path: Path) -> tuple[str, str, list[str], bool, str]:
    """Extract metadata headers and body text from a markdown runbook file."""
    content = file_path.read_text(encoding="utf-8")
    runbook_id = file_path.stem.upper()
    title = file_path.stem
    targets: list[str] = []
    human_only = False

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# Runbook ID:"):
            runbook_id = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("## Title:"):
            title = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("## Target Services:"):
            raw_targets = stripped.split(":", 1)[1].strip()
            targets = [t.strip().lower() for t in raw_targets.split(",") if t.strip()]
        elif stripped.startswith("## Automation Policy:"):
            policy_val = stripped.split(":", 1)[1].strip().upper()
            human_only = "HUMAN_ONLY" in policy_val

    return runbook_id, title, targets, human_only, content


def retrieve_runbooks(
    service_id: ServiceId,
    query: str,
    runbooks_dir: Path | None = None,
    top_k: int = 3,
) -> RunbookRetrievalResponse:
    """Search approved markdown runbooks with source attribution and gap disclosure."""
    active_dir = runbooks_dir or DEFAULT_RUNBOOKS_DIR
    bounded_k = max(1, min(top_k, 5))
    query_terms = {
        tok.lower()
        for tok in re.findall(r"[a-zA-Z0-9_\-]+", query)
        if len(tok) >= 3
    }

    if not active_dir.exists():
        return RunbookRetrievalResponse(
            service_id=service_id,
            query=query,
            matches=[],
            retrieval_gap_disclosed=True,
            gap_reason=f"Runbooks directory '{active_dir.name}' is missing or empty.",
        )

    candidates: list[RunbookSnippet] = []
    for md_file in sorted(active_dir.glob("*.md")):
        rb_id, title, targets, human_only, body = _parse_runbook_file(md_file)
        body_lower = body.lower()

        service_match = service_id.value.lower() in targets
        matched_terms = sum(1 for term in query_terms if term in body_lower)

        if not service_match and matched_terms == 0:
            continue

        term_ratio = (matched_terms / len(query_terms)) if query_terms else 0.0
        raw_score = (0.5 if service_match else 0.0) + (0.5 * term_ratio)
        score = round(min(1.0, raw_score), 2)

        if score < 0.25:
            continue

        candidates.append(
            RunbookSnippet(
                runbook_id=rb_id,
                title=title,
                source_path=f"runbooks/{md_file.name}",
                target_services=targets,
                human_only=human_only,
                relevance_score=score,
                sanitized_excerpt=sanitize_runbook_text(body),
            )
        )

    candidates.sort(key=lambda item: item.relevance_score, reverse=True)
    top_matches = candidates[:bounded_k]

    if not top_matches:
        return RunbookRetrievalResponse(
            service_id=service_id,
            query=query,
            matches=[],
            retrieval_gap_disclosed=True,
            gap_reason=(
                f"No approved runbook matched service '{service_id.value}' "
                f"and query '{query}'."
            ),
        )

    return RunbookRetrievalResponse(
        service_id=service_id,
        query=query,
        matches=top_matches,
        retrieval_gap_disclosed=False,
        gap_reason=None,
    )