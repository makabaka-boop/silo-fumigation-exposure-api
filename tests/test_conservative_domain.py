from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import ConservativeVerificationRequest


BASE_PAYLOAD = {
    "warehouse_id": "A-01",
    "threshold_ppm": 1,
    "minimum_duration_seconds": 2,
    "measurement_error_ppm": 0.1,
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
        ConservativeVerificationRequest.model_validate(payload)
    errors = exc_info.value.errors()
    matches = [error for error in errors if tuple(error["loc"]) == location]
    assert matches, (location, errors)
    return matches[0]


def test_accepts_conservative_contract_and_parses_bound_as_decimal():
    model = ConservativeVerificationRequest.model_validate(BASE_PAYLOAD)

    assert model.measurement_error_ppm == Decimal("0.1")
    assert model.warehouse_id == "A-01"
    assert model.minimum_duration_ms == 2000


def test_accepts_zero_bound():
    payload = BASE_PAYLOAD | {"measurement_error_ppm": 0}

    model = ConservativeVerificationRequest.model_validate(payload)

    assert model.measurement_error_ppm == Decimal("0")


@pytest.mark.parametrize("value", [0.001, 0.5, 12.345])
def test_accepts_up_to_three_decimal_places(value):
    payload = BASE_PAYLOAD | {"measurement_error_ppm": value}

    model = ConservativeVerificationRequest.model_validate(payload)

    assert model.measurement_error_ppm == Decimal(str(value))


@pytest.mark.parametrize("value", [-0.001, -1])
def test_rejects_negative_bound(value):
    payload = BASE_PAYLOAD | {"measurement_error_ppm": value}

    error = error_for(payload, "measurement_error_ppm")
    assert error["type"] == "value_error.negative"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_bound(value):
    payload = BASE_PAYLOAD | {"measurement_error_ppm": value}

    error = error_for(payload, "measurement_error_ppm")
    assert error["type"] == "value_error.not_finite"


def test_rejects_four_decimal_place_bound():
    payload = BASE_PAYLOAD | {"measurement_error_ppm": 0.0001}

    error = error_for(payload, "measurement_error_ppm")
    assert error["type"] == "value_error.too_many_decimal_places"


def test_boolean_bound_is_rejected():
    payload = BASE_PAYLOAD | {"measurement_error_ppm": True}

    error = error_for(payload, "measurement_error_ppm")
    assert error["type"] == "value_error.not_a_number"


def test_numeric_string_bound_is_rejected():
    payload = BASE_PAYLOAD | {"measurement_error_ppm": "0.1"}

    error = error_for(payload, "measurement_error_ppm")
    assert error["type"] == "value_error.not_a_number"


def test_missing_bound_is_required():
    payload = {key: value for key, value in BASE_PAYLOAD.items()
              if key != "measurement_error_ppm"}

    error = error_for(payload, "measurement_error_ppm")
    assert error["type"] == "missing"


def test_rejects_unknown_fields():
    payload = BASE_PAYLOAD | {"unexpected": True}

    error = error_for(payload, "unexpected")
    assert error["type"] == "extra_forbidden"


def test_inherits_single_point_reading_validation():
    payload = BASE_PAYLOAD.copy()
    payload["readings"] = [
        dict(reading, concentration_ppm=-1)
        for reading in BASE_PAYLOAD["readings"]
    ]

    error = error_for(payload, "readings", 0, "concentration_ppm")
    assert error["type"] == "value_error.negative"


def test_inherits_span_validation():
    payload = BASE_PAYLOAD | {"minimum_duration_seconds": 3}

    error = error_for(payload, "readings")
    assert error["type"] == "value_error.span_shorter_than_minimum_duration"
