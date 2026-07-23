"""Provider-neutral evidence normalization for public Showrun artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_IMPORT_BYTES = 2_000_000
MAX_ELAPSED_MS = 86_400_000
MAX_SOURCES = 20
MAX_REDACTIONS = 20
INPUT_PREVIEW_CHARS = 2_000
OUTPUT_PREVIEW_CHARS = 5_000
SENSITIVE_VALUES_REDACTION_NOTE = "Sensitive values removed locally."
ACTIVITY_STATUSES = frozenset({"", "started", "success", "failure", "retry"})


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    """One sanitized source cited by an execution event."""

    title: str
    url: str = ""
    domain: str = ""


def normalize_status(value: Any, *, default: str = "") -> str:
    """Normalize common provider states to the portable evidence contract."""

    normalized = str(value or "").lower()
    if not normalized:
        return default
    if normalized in {"completed", "complete"}:
        return "success"
    if normalized in {"error", "errored", "failed"}:
        return "failure"
    if normalized in {"in_progress", "queued", "running"}:
        return "started"
    return normalized if normalized in ACTIVITY_STATUSES else default


_HIDDEN_BLOCKS = re.compile(
    r"<(?:in-app-browser-context|environment_context|recommended_plugins)\b.*?</"
    r"(?:in-app-browser-context|environment_context|recommended_plugins)>",
    flags=re.DOTALL,
)
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*"
        r"([\"']?)[A-Za-z0-9._~+/=-]{8,}\2"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        flags=re.DOTALL,
    ),
)
_PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?<![\w])/(?:Users|home)/[^/\s\"']+(?:/[^\s\"']*)?"),
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s\"']+(?:\\[^\s\"']*)?"),
)
_SENSITIVE_KEY = re.compile(r"(?i).*(?:api[_-]?key|authorization|cookie|password|secret|token).*")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_DOMAIN_RE = re.compile(
    r"(?i)^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def redact_text(text: str) -> str:
    """Remove common credential and private-path shapes from public text."""

    redacted = _URL_RE.sub(
        lambda match: _safe_url(match.group(0))[0] or "[REDACTED URL]",
        text,
    )
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    for pattern in _PRIVATE_PATH_PATTERNS:
        redacted = pattern.sub("[LOCAL PATH]", redacted)
    return redacted


def _sanitize_structured(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]" if _SENSITIVE_KEY.fullmatch(str(key)) else _sanitize_structured(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_structured(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_structured(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def _preview_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError, ValueError:
        return str(value)


def safe_preview(
    value: Any,
    *,
    limit: int = INPUT_PREVIEW_CHARS,
) -> tuple[str, bool]:
    """Return a bounded public excerpt and whether local redaction changed it."""

    structured = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            structured = parsed
    raw = _HIDDEN_BLOCKS.sub("", _preview_text(structured)).strip()
    clean = _HIDDEN_BLOCKS.sub("", _preview_text(_sanitize_structured(structured))).strip()
    clean = redact_text(clean)
    return clean[:limit], clean != raw


def normalize_redactions(values: Any, *, evidence_redacted: bool = False) -> tuple[str, ...]:
    """Return stable, bounded public redaction notes."""

    if not isinstance(values, (list, tuple)):
        values = ()
    notes = list(
        dict.fromkeys(
            [
                redact_text(str(value).strip())[:160]
                for value in values
                if isinstance(value, str) and value.strip()
            ]
        )
    )
    if evidence_redacted:
        notes = [note for note in notes if note != SENSITIVE_VALUES_REDACTION_NOTE]
        notes = notes[: MAX_REDACTIONS - 1]
        notes.append(SENSITIVE_VALUES_REDACTION_NOTE)
    return tuple(notes[:MAX_REDACTIONS])


def _safe_url(raw: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(raw.strip())
    except ValueError:
        return "", ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "", ""
    port = f":{parsed.port}" if parsed.port else ""
    domain = parsed.hostname.lower()
    return urlunsplit((parsed.scheme, f"{domain}{port}", parsed.path, "", ""))[:2048], domain


def sanitize_sources(values: Any) -> tuple[EvidenceSource, ...]:
    """Normalize a bounded list of public evidence links."""

    if not isinstance(values, (list, tuple)):
        return ()
    sources: list[EvidenceSource] = []
    for value in values[:MAX_SOURCES]:
        if isinstance(value, str):
            url, domain = _safe_url(value)
            title = domain or redact_text(value.strip())[:160]
        elif isinstance(value, dict):
            url, domain = _safe_url(str(value.get("url") or ""))
            title = redact_text(str(value.get("title") or domain or "Source").strip())[:160]
            supplied_domain = str(value.get("domain") or "").strip().lower()
            if not domain and _DOMAIN_RE.fullmatch(supplied_domain):
                domain = supplied_domain[:255]
        else:
            continue
        if title:
            sources.append(EvidenceSource(title=title, url=url, domain=domain))
    return tuple(sources)


def sources_from_text(text: str) -> tuple[EvidenceSource, ...]:
    """Extract a small de-duplicated set of public URLs from an output excerpt."""

    return sanitize_sources(list(dict.fromkeys(_URL_RE.findall(text)))[:8])
