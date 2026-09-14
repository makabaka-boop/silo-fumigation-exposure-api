import pytest
from pydantic import ValidationError

from app.domain import WindowVerificationRequest


_EPOCH = 1767225600000  # 2026-01-01T00:00:00.000Z, Unix milliseconds.

BASE_PAYLOAD = {
    "warehouse_id": "A-01",
    "threshold_ppm": 1,
    "minimum_duration_seconds": 2,
    "window_start": "2026-01-01T00:00:00.250Z",
    "window_end": "2026-01-01T00:00:02.750Z",
    "readings": [
        {
            "timestamp": "2026-01-01T00:00:00.000Z",
            "concentration_ppm": 0,
        },
        {
            "timestamp": "2026-01-01T00:00:01.000Z",
            "concentration_ppm": 2,
        },
        {
            "timestamp": "2026-01-01T00:00:02.000Z",
            "concentration_ppm": 2,
        },
        {
            "timestamp": "2026-01-01T00:00:03.000Z",
            "concentration_ppm": 0,
        },
    ],
}


def error_for(payload: dict, *location: str | int) -> dict:
    __tracebackhide__ = True
    with pytest.raises(ValidationError) as exc_info:
        WindowVerificationRequest.model_validate(payload)
    errors = exc_info.value.errors()
    matches = [error for error in errors if tuple(error["loc"]) == location]
    assert matches, (location, errors)
    return matches[0]


def test_accepts_valid_window_and_parses_bounds_to_unix_ms():
    model = WindowVerificationRequest.model_validate(BASE_PAYLOAD)

    assert model.window_start == _EPOCH + 250
    assert model.window_end == _EPOCH + 2750
    assert model.minimum_duration_ms == 2000


def test_window_bounds_may_coincide_with_first_and_last_readings():
    payload = BASE_PAYLOAD | {
        "window_start": "2026-01-01T00:00:00.000Z",
        "window_end": "2026-01-01T00:00:03.000Z",
    }

    model = WindowVerificationRequest.model_validate(payload)

    assert model.window_start == _EPOCH
    assert model.window_end == _EPOCH + 3000


def test_rejects_window_start_before_first_reading():
    payload = BASE_PAYLOAD | {"window_start": "2025-12-31T23:59:59.999Z"}

    error = error_for(payload, "window_start")
    assert error["type"] == "value_error.window_outside_span"
    assert error["ctx"] == {
        "window_start_unix_ms": _EPOCH - 1,
        "first_reading_unix_ms": _EPOCH,
        "last_reading_unix_ms": _EPOCH + 3000,
    }


def test_rejects_window_end_after_last_reading():
    payload = BASE_PAYLOAD | {"window_end": "2026-01-01T00:00:03.001Z"}

    error = error_for(payload, "window_end")
    assert error["type"] == "value_error.window_outside_span"
    assert error["ctx"] == {
        "window_end_unix_ms": _EPOCH + 3001,
        "first_reading_unix_ms": _EPOCH,
        "last_reading_unix_ms": _EPOCH + 3000,
    }


def test_reports_each_out_of_span_bound_on_its_own_field():
    payload = BASE_PAYLOAD | {
        "window_start": "2025-12-31T23:59:59.999Z",
        "window_end": "2026-01-01T00:00:03.001Z",
    }

    with pytest.raises(ValidationError) as exc_info:
        WindowVerificationRequest.model_validate(payload)
    span_errors = [
        error
        for error in exc_info.value.errors()
        if error["type"] == "value_error.window_outside_span"
    ]
    assert [error["loc"] for error in span_errors] == [
        ("window_start",),
        ("window_end",),
    ]


def test_rejects_inverted_window_at_window_end():
    payload = BASE_PAYLOAD | {
        "window_start": "2026-01-01T00:00:02.000Z",
        "window_end": "2026-01-01T00:00:01.000Z",
    }

    error = error_for(payload, "window_end")
    assert error["type"] == "value_error.window_not_ordered"
    assert error["ctx"] == {
        "window_start_unix_ms": _EPOCH + 2000,
        "window_end_unix_ms": _EPOCH + 1000,
    }


def test_rejects_zero_length_window():
    payload = BASE_PAYLOAD | {
        "window_start": "2026-01-01T00:00:01.000Z",
        "window_end": "2026-01-01T00:00:01.000Z",
    }

    error = error_for(payload, "window_end")
    assert error["type"] == "value_error.window_not_ordered"


def test_rejects_window_timestamp_without_milliseconds():
    payload = BASE_PAYLOAD | {"window_start": "2026-01-01T00:00:00Z"}

    error = error_for(payload, "window_start")
    assert error["type"] == "value_error.invalid_timestamp"


def test_rejects_non_string_window_bound():
    payload = BASE_PAYLOAD | {"window_end": 1767225602750}

    error = error_for(payload, "window_end")
    assert error["type"] == "value_error.timestamp_not_string"


def test_inherits_single_point_reading_and_field_rules():
    payload = BASE_PAYLOAD.copy()
    payload["readings"] = [dict(reading) for reading in BASE_PAYLOAD["readings"]]
    payload["readings"][1]["timestamp"] = payload["readings"][0]["timestamp"]

    error = error_for(payload, "readings")
    assert error["type"] == "value_error.timestamps_not_strictly_increasing"

    error = error_for(BASE_PAYLOAD | {"unexpected": True}, "unexpected")
    assert error["type"] == "extra_forbidden"
