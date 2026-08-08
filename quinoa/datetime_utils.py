"""Shared datetime helpers for parsing, canonicalizing, and displaying timestamps.

All stored SQLite timestamps are canonical UTC ISO 8601 text with a 'T' separator,
six fractional digits, and a '+00:00' offset.  This module provides the central
serializer/parsers and local-display helpers used by the database, UI, search, and
notification consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NYC = ZoneInfo("America/New_York")
UTC = UTC

# Naive-value policies used by the canonical serializer.
POLICY_NYC = "nyc"
POLICY_UTC = "utc"


def _validate_nyc_candidate(local_value: datetime, fold: int) -> datetime | None:
    """Return the fold-aware NYC candidate if it round-trips to the same wall time.

    A candidate is valid only when its UTC round-trip returns the exact same
    naive wall time and the same fold.  This detects both nonexistent spring-
    forward wall times and ambiguous fall-back wall times when the offsets differ.
    """
    candidate = local_value.replace(tzinfo=NYC, fold=fold)
    roundtrip = candidate.astimezone(UTC).astimezone(NYC)
    if roundtrip.replace(tzinfo=None) == local_value and roundtrip.fold == fold:
        return candidate
    return None


def _attach_nyc(local_value: datetime, *, allow_fold: bool = False) -> datetime:
    """Attach America/New_York to a naive datetime with strict DST validation.

    Legacy strings have no fold provenance, so both folds are tested and an
    ambiguous fall-back time with differing offsets is rejected.  A runtime naive
    datetime may use its explicit ``fold`` value when that exact candidate
    validates.

    Raises:
        ValueError: if the wall time is nonexistent or (for string input)
            ambiguous in America/New_York.
    """
    candidates: dict[int, datetime] = {}
    for fold in (0, 1):
        candidate = _validate_nyc_candidate(local_value, fold)
        if candidate is not None:
            candidates[fold] = candidate

    if not candidates:
        raise ValueError("nonexistent wall time in America/New_York")

    offsets = {candidate.utcoffset() for candidate in candidates.values()}
    if len(offsets) > 1:
        if allow_fold and local_value.fold in candidates:
            return candidates[local_value.fold]
        raise ValueError("ambiguous wall time in America/New_York")

    return next(iter(candidates.values()))


def _parse_input(value: str | datetime) -> datetime:
    """Parse a string or return an existing datetime object.

    Supports ISO strings with space or 'T' separators and offsets.  Naive strings
    are returned as naive datetimes; the caller decides the policy.
    """
    if isinstance(value, datetime):
        return value

    # fromisoformat accepts space-separated legacy values in Python 3.11+.
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"malformed timestamp: {value!r}") from exc


def serialize_timestamp(
    value: str | datetime,
    policy: str = POLICY_NYC,
    *,
    context: str = "",
    allow_runtime_fold: bool | None = None,
) -> str:
    """Convert a string or datetime into canonical UTC ISO 8601 text.

    Legacy naive strings have no fold provenance and therefore reject ambiguity.
    A runtime naive ``datetime`` may use its explicit ``fold`` value when that
    exact candidate validates.

    Args:
        value: An ISO string or datetime. Naive values are interpreted by policy.
        policy: POLICY_NYC or POLICY_UTC.
        context: Optional table.column key context for error messages.
        allow_runtime_fold: Override fold handling.  When ``None`` it is inferred
            from the input type (``True`` for ``datetime``, ``False`` for strings).

    Returns:
        Fixed-width UTC ISO text: 'YYYY-MM-DDTHH:MM:SS.ffffff+00:00'.

    Raises:
        ValueError: If the input is malformed or ambiguous/nonexistent under the
            requested policy.  The context string is included when provided.
    """
    prefix = f"{context}: " if context else ""
    try:
        dt = _parse_input(value)

        if allow_runtime_fold is None:
            allow_runtime_fold = isinstance(value, datetime)

        if dt.tzinfo is None:
            if policy == POLICY_UTC:
                dt = dt.replace(tzinfo=UTC)
            elif policy == POLICY_NYC:
                dt = _attach_nyc(dt, allow_fold=allow_runtime_fold)
            else:
                raise ValueError(f"unknown policy: {policy}")

        return dt.astimezone(UTC).isoformat(timespec="microseconds")
    except ValueError as exc:
        if context and not str(exc).startswith(prefix):
            raise ValueError(f"{prefix}{exc}") from exc
        raise


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse a canonical or legacy timestamp into an aware UTC datetime.

    Legacy naive strings reject ambiguity.  A runtime naive ``datetime`` may use
    its explicit ``fold`` when that candidate validates.
    """
    dt = _parse_input(value)
    if dt.tzinfo is None:
        allow_fold = isinstance(value, datetime)
        dt = _attach_nyc(dt, allow_fold=allow_fold)
    return dt.astimezone(UTC)


def to_local_datetime(value: str | datetime) -> datetime:
    """Return an aware datetime in the machine's local timezone."""
    return parse_timestamp(value).astimezone()


def to_local_naive(value: str | datetime) -> datetime:
    """Return a naive datetime in the machine's local time.

    This supports existing comparisons against the naive ``get_now()`` helper.
    """
    return to_local_datetime(value).replace(tzinfo=None)


def to_local_date_key(value: str | datetime) -> str:
    """Return the local YYYY-MM-DD grouping key for a stored timestamp."""
    return to_local_naive(value).strftime("%Y-%m-%d")


def utc_now() -> datetime:
    """Return the current aware UTC datetime."""
    return datetime.now(UTC)
