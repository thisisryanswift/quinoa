import os
import time
from datetime import datetime

import pytest

from quinoa.datetime_utils import (
    POLICY_UTC,
    parse_timestamp,
    serialize_timestamp,
    to_local_date_key,
    to_local_naive,
)


def test_new_york_naive_values_normalize_to_fixed_utc() -> None:
    summer = serialize_timestamp(datetime(2026, 8, 8, 18, 7, 12, 123456))
    winter = serialize_timestamp(datetime(2026, 1, 8, 18, 7, 12))

    assert summer == "2026-08-08T22:07:12.123456+00:00"
    assert winter == "2026-01-08T23:07:12.000000+00:00"


def test_aware_value_preserves_instant() -> None:
    value = datetime.fromisoformat("2026-08-08T18:07:12.123456-04:00")

    assert serialize_timestamp(value) == "2026-08-08T22:07:12.123456+00:00"


def test_legacy_chat_naive_value_is_interpreted_as_utc() -> None:
    assert serialize_timestamp("2026-08-08 22:07:12", policy=POLICY_UTC) == (
        "2026-08-08T22:07:12.000000+00:00"
    )


def test_legacy_ambiguous_new_york_string_is_rejected() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        serialize_timestamp("2026-11-01 01:30:00")


def test_legacy_nonexistent_new_york_string_is_rejected() -> None:
    with pytest.raises(ValueError, match="nonexistent"):
        serialize_timestamp("2026-03-08 02:30:00")


def test_runtime_naive_datetime_uses_explicit_fold() -> None:
    first = datetime(2026, 11, 1, 1, 30, fold=0)
    second = datetime(2026, 11, 1, 1, 30, fold=1)

    assert serialize_timestamp(first) == "2026-11-01T05:30:00.000000+00:00"
    assert serialize_timestamp(second) == "2026-11-01T06:30:00.000000+00:00"


def test_unambiguous_runtime_datetime_ignores_irrelevant_fold() -> None:
    value = datetime(2026, 8, 8, 18, 7, fold=1)

    assert serialize_timestamp(value) == "2026-08-08T22:07:00.000000+00:00"


def test_parse_timestamp_rejects_naive_legacy_ambiguity() -> None:
    with pytest.raises(ValueError):
        parse_timestamp("2026-11-01 01:30:00")


def test_local_helpers_respect_utc_date_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(time, "tzset"):
        pytest.skip("tzset is unavailable")
    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        value = "2026-08-09T02:00:00.000000+00:00"
        assert to_local_date_key(value) == "2026-08-08"
        assert to_local_naive(value) == datetime(2026, 8, 8, 22, 0)
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()
