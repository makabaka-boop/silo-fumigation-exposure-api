import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.domain import JointVerificationRequest


_FULL_WIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def _readings(*entries: tuple[str, float]) -> list[dict]:
    return [
        {
            "timestamp": f"2026-01-01T00:00:0{second}.000Z",
            "concentration_ppm": concentration,
        }
        for second, concentration in entries
    ]


def _point(point_id: str, readings: list[dict]) -> dict:
    return {"point_id": point_id, "readings": readings}


BASE_PAYLOAD = {
    "warehouse_id": "B-07",
    "threshold_ppm": 1,
    "minimum_duration_seconds": 2,
    "points": [
        _point(
            "P-1",
            _readings(("0", 0), ("1", 2), ("2", 2), ("3", 0)),
        ),
        _point(
            "P-2",
            _readings(("0", 0), ("1", 2), ("2", 2), ("3", 0)),
        ),
    ],
}


def joint_payload(**overrides) -> dict:
    payload = {
        **BASE_PAYLOAD,
        "points": [
            {"point_id": point["point_id"], "readings": [dict(r) for r in point["readings"]]}
            for point in BASE_PAYLOAD["points"]
        ],
    }
    payload.update(overrides)
    return payload


def error_for(payload: dict, *location: str | int) -> dict:
    __tracebackhide__ = True
    with pytest.raises(ValidationError) as exc_info:
        JointVerificationRequest.model_validate(payload)
    errors = exc_info.value.errors()
    matches = [error for error in errors if tuple(error["loc"]) == location]
    assert matches, (location, errors)
    return matches[0]


def test_accepts_valid_joint_contract_and_converts_duration_exactly():
    model = JointVerificationRequest.model_validate(joint_payload())

    assert model.minimum_duration_ms == 2000
    assert [series.point_id for series in model.points] == ["P-1", "P-2"]
    assert model.points[0].span_ms == 3000


def test_rejects_duplicate_point_ids_at_the_offending_point():
    payload = joint_payload()
    payload["points"][1]["point_id"] = "P-1"

    error = error_for(payload, "points", 1, "point_id")
    assert error["type"] == "value_error.duplicate_point_id"
    assert error["ctx"] == {"point_id": "P-1"}


def test_rejects_mismatched_first_timestamp_at_the_reading_field():
    payload = joint_payload()
    payload["points"][1]["readings"][0]["timestamp"] = "2026-01-01T00:00:00.500Z"

    error = error_for(payload, "points", 1, "readings", 0, "timestamp")
    assert error["type"] == "value_error.series_time_bounds_mismatch"
    assert error["ctx"] == {
        "expected_unix_ms": 1767225600000,
        "actual_unix_ms": 1767225600500,
    }


def test_rejects_mismatched_last_timestamp_at_the_reading_field():
    payload = joint_payload()
    payload["points"][1]["readings"][3]["timestamp"] = "2026-01-01T00:00:04.000Z"

    error = error_for(payload, "points", 1, "readings", 3, "timestamp")
    assert error["type"] == "value_error.series_time_bounds_mismatch"
    assert error["ctx"] == {
        "expected_unix_ms": 1767225603000,
        "actual_unix_ms": 1767225604000,
    }


def test_rejects_series_span_shorter_than_minimum_duration_per_point():
    payload = joint_payload(minimum_duration_seconds=3.5)

    for index in (0, 1):
        error = error_for(payload, "points", index, "readings")
        assert error["type"] == "value_error.span_shorter_than_minimum_duration"
        assert error["ctx"] == {"span_ms": 3000, "minimum_duration_ms": 3500}


def test_rejects_non_increasing_timestamps_inside_the_offending_point():
    payload = joint_payload()
    payload["points"][1]["readings"][2]["timestamp"] = "2026-01-01T00:00:01.000Z"

    error = error_for(payload, "points", 1, "readings", 2, "timestamp")
    assert error["type"] == "value_error.timestamps_not_strictly_increasing"
    assert error["ctx"]["index"] == 2


def test_rejects_negative_concentration_at_the_nested_reading_field():
    payload = joint_payload()
    payload["points"][1]["readings"][0]["concentration_ppm"] = -1

    error = error_for(payload, "points", 1, "readings", 0, "concentration_ppm")
    assert error["type"] == "value_error.negative"


def test_rejects_bad_timestamp_format_at_the_nested_reading_field():
    payload = joint_payload()
    payload["points"][0]["readings"][1]["timestamp"] = "2026-01-01T00:00:01Z"

    error = error_for(payload, "points", 0, "readings", 1, "timestamp")
    assert error["type"] == "value_error.invalid_timestamp"


def test_rejects_full_width_digit_timestamps_on_every_point():
    payload = joint_payload()
    for point in payload["points"]:
        for reading in point["readings"]:
            reading["timestamp"] = reading["timestamp"].translate(_FULL_WIDTH_DIGITS)

    with pytest.raises(ValidationError) as exc_info:
        JointVerificationRequest.model_validate(payload)
    errors = exc_info.value.errors()
    assert errors
    assert all(error["type"] == "value_error.invalid_timestamp" for error in errors)
    assert errors[0]["loc"] == ("points", 0, "readings", 0, "timestamp")


def test_rejects_duration_with_four_trailing_decimal_places():
    payload = joint_payload(minimum_duration_seconds=Decimal("2.0000"))

    error = error_for(payload, "minimum_duration_seconds")
    assert error["type"] == "value_error.too_many_decimal_places"


def test_locates_last_reading_timestamp_when_it_equals_the_first():
    payload = joint_payload()
    payload["points"][1]["readings"][3]["timestamp"] = "2026-01-01T00:00:00.000Z"

    error = error_for(payload, "points", 1, "readings", 3, "timestamp")
    assert error["type"] == "value_error.timestamps_not_strictly_increasing"
    assert error["ctx"]["index"] == 3


def test_flags_first_point_when_only_its_start_time_is_the_outlier():
    payload = joint_payload()
    payload["points"].append(
        {
            "point_id": "P-3",
            "readings": [dict(reading) for reading in payload["points"][1]["readings"]],
        }
    )
    payload["points"][0]["readings"][0]["timestamp"] = "2026-01-01T00:00:00.500Z"

    with pytest.raises(ValidationError) as exc_info:
        JointVerificationRequest.model_validate(payload)
    bounds_errors = [
        error
        for error in exc_info.value.errors()
        if error["type"] == "value_error.series_time_bounds_mismatch"
    ]
    assert [error["loc"] for error in bounds_errors] == [
        ("points", 0, "readings", 0, "timestamp")
    ]
    assert bounds_errors[0]["ctx"] == {
        "expected_unix_ms": 1767225600000,
        "actual_unix_ms": 1767225600500,
    }


def test_flags_first_point_when_only_its_end_time_is_the_outlier():
    payload = joint_payload()
    payload["points"].append(
        {
            "point_id": "P-3",
            "readings": [dict(reading) for reading in payload["points"][1]["readings"]],
        }
    )
    payload["points"][0]["readings"][3]["timestamp"] = "2026-01-01T00:00:04.000Z"

    with pytest.raises(ValidationError) as exc_info:
        JointVerificationRequest.model_validate(payload)
    bounds_errors = [
        error
        for error in exc_info.value.errors()
        if error["type"] == "value_error.series_time_bounds_mismatch"
    ]
    assert [error["loc"] for error in bounds_errors] == [
        ("points", 0, "readings", 3, "timestamp")
    ]
    assert bounds_errors[0]["ctx"] == {
        "expected_unix_ms": 1767225603000,
        "actual_unix_ms": 1767225604000,
    }


def test_rejects_blank_point_id():
    payload = joint_payload()
    payload["points"][0]["point_id"] = "   "

    error = error_for(payload, "points", 0, "point_id")
    assert error["type"] == "value_error.empty_point_id"


def test_requires_between_two_and_ten_points():
    one_point = joint_payload()
    one_point["points"] = one_point["points"][:1]
    error = error_for(one_point, "points")
    assert error["type"] == "too_short"

    eleven_points = joint_payload()
    template = eleven_points["points"][0]
    eleven_points["points"] = [
        {"point_id": f"P-{index}", "readings": template["readings"]}
        for index in range(11)
    ]
    error = error_for(eleven_points, "points")
    assert error["type"] == "too_long"


def test_requires_at_least_two_readings_per_point():
    payload = joint_payload()
    payload["points"][0]["readings"] = payload["points"][0]["readings"][:1]

    error = error_for(payload, "points", 0, "readings")
    assert error["type"] == "too_short"


def test_rejects_unknown_fields_inside_a_point():
    payload = joint_payload()
    payload["points"][0]["label"] = "unexpected"

    error = error_for(payload, "points", 0, "label")
    assert error["type"] == "extra_forbidden"
