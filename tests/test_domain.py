from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import VerificationRequest


BASE_PAYLOAD = {
    "warehouse_id": "A-01",
    "threshold_ppm": 1,
    "minimum_duration_seconds": 2,
    "readings": [
        {
            "timestamp": "2026-01-01T00:00:00.000Z",
            "concentration_ppm": 0,
        },
        {
            "timestamp": "2026-01-01T00:00:02.000Z",
            "concentration_ppm": 2,
        },
    ],
}


def error_for(payload: dict, *location: str | int) -> dict:
    __tracebackhide__ = True
    with pytest.raises(ValidationError) as exc_info:
        VerificationRequest.model_validate(payload)
    errors = exc_info.value.errors()
    matches = [error for error in errors if tuple(error["loc"]) == location]
    assert matches, (location, errors)
    return matches[0]


def test_accepts_valid_domain_contract_and_converts_duration_exactly():
    model = VerificationRequest.model_validate(BASE_PAYLOAD)

    assert model.minimum_duration_ms == 2000
    assert model.span_ms == 2000


def test_rejects_four_decimal_place_duration():
    payload = BASE_PAYLOAD | {"minimum_duration_seconds": 1.0001}
    error = error_for(payload, "minimum_duration_seconds")
    assert error["type"] == "value_error.too_many_decimal_places"


@pytest.mark.parametrize("value", [0, -0.001])
def test_rejects_non_positive_duration(value: float):
    payload = BASE_PAYLOAD | {"minimum_duration_seconds": value}
    error = error_for(payload, "minimum_duration_seconds")
    assert error["type"] == "value_error.not_positive"


def test_rejects_nan_and_infinite_numeric_values():
    payload = BASE_PAYLOAD | {"threshold_ppm": float("nan")}
    error = error_for(payload, "threshold_ppm")
    assert error["type"] == "value_error.not_finite"

    payload = BASE_PAYLOAD | {"threshold_ppm": float("inf")}
    error = error_for(payload, "threshold_ppm")
    assert error["type"] == "value_error.not_finite"


def test_rejects_negative_concentration_with_nested_location():
    payload = BASE_PAYLOAD.copy()
    payload["readings"] = [
        dict(reading, concentration_ppm=-1)
        for reading in BASE_PAYLOAD["readings"]
    ]
    error = error_for(payload, "readings", 0, "concentration_ppm")
    assert error["type"] == "value_error.negative"


def test_rejects_timestamp_without_milliseconds_or_z_suffix():
    payload = BASE_PAYLOAD.copy()
    readings = [dict(item) for item in BASE_PAYLOAD["readings"]]
    readings[0]["timestamp"] = "2026-01-01T00:00:00Z"
    payload["readings"] = readings

    error = error_for(payload, "readings", 0, "timestamp")
    assert error["type"] == "value_error.invalid_timestamp"


def test_requires_strictly_increasing_timestamps():
    payload = BASE_PAYLOAD.copy()
    readings = [dict(item) for item in BASE_PAYLOAD["readings"]]
    readings[1]["timestamp"] = readings[0]["timestamp"]
    payload["readings"] = readings

    error = error_for(payload, "readings")
    assert error["type"] == "value_error.timestamps_not_strictly_increasing"
    assert error["ctx"]["index"] == 1


def test_reading_span_must_reach_minimum_duration():
    payload = BASE_PAYLOAD | {"minimum_duration_seconds": 3}
    error = error_for(payload, "readings")
    assert error["type"] == "value_error.span_shorter_than_minimum_duration"
    assert error["ctx"] == {"span_ms": 2000, "minimum_duration_ms": 3000}


def test_requires_at_least_two_readings():
    payload = BASE_PAYLOAD.copy()
    payload["readings"] = BASE_PAYLOAD["readings"][:1]

    error = error_for(payload, "readings")
    assert error["type"] == "too_short"


def test_rejects_unknown_fields():
    payload = BASE_PAYLOAD | {"unexpected": True}
    error = error_for(payload, "unexpected")
    assert error["type"] == "extra_forbidden"


def test_numeric_string_is_rejected_in_strict_contract():
    payload = BASE_PAYLOAD | {"threshold_ppm": "1"}
    error = error_for(payload, "threshold_ppm")
    assert error["type"] == "value_error.not_a_number"


def test_boolean_is_not_accepted_as_number():
    payload = BASE_PAYLOAD | {"minimum_duration_seconds": True}
    error = error_for(payload, "minimum_duration_seconds")
    assert error["type"] == "value_error.not_a_number"


def test_empty_warehouse_id_is_field_level_invalid():
    payload = BASE_PAYLOAD | {"warehouse_id": "   "}
    error = error_for(payload, "warehouse_id")
    assert error["type"] == "value_error.empty_warehouse_id"


def test_decimal_values_avoid_binary_float_artifacts():
    payload = BASE_PAYLOAD | {"threshold_ppm": 0.1}
    model = VerificationRequest.model_validate(payload)
    assert model.threshold_ppm == Decimal("0.1")
