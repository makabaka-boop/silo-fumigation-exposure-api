from decimal import Decimal

from app.calculator import (
    calculate_conservative_exposure,
    verify_conservative_request,
)
from app.domain import ConservativeVerificationRequest, Reading


def reading(ts: str, concentration: str) -> Reading:
    return Reading(
        timestamp=ts,
        concentration_ppm=Decimal(concentration),
    )


def request_(measurement_error, **overrides) -> ConservativeVerificationRequest:
    payload = {
        "warehouse_id": "A-01",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 0.5,
        "measurement_error_ppm": measurement_error,
        "readings": [
            {"timestamp": "2026-01-01T00:00:00.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:01.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:02.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:03.000Z", "concentration_ppm": 0},
        ],
    }
    payload.update(overrides)
    return ConservativeVerificationRequest.model_validate(payload)


def test_deducts_bound_from_every_reading_before_interpolation():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:01.000Z", "2"),
        reading("2026-01-01T00:00:02.000Z", "2"),
        reading("2026-01-01T00:00:03.000Z", "0"),
    ]

    result = calculate_conservative_exposure(readings, Decimal("1"), Decimal("0.5"))

    # Adjusted series runs 0 -> (2-0.5); crossings at adjusted level 1 are
    # two-thirds of a millisecond segment from each edge, then half-away round.
    assert [(interval.start_ms, interval.end_ms) for interval in result.intervals] == [
        (readings[0].timestamp + 667, readings[3].timestamp - 667),
    ]
    assert result.longest_duration_ms == 1666


def test_negative_adjusted_concentrations_are_clamped_to_zero():
    # Every sample sits below the bound; deduction must not turn them negative
    # (which would move the interpolation crossings), so no interval survives.
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0.2"),
        reading("2026-01-01T00:00:01.000Z", "0.4"),
        reading("2026-01-01T00:00:02.000Z", "0.3"),
    ]

    result = calculate_conservative_exposure(readings, Decimal("1"), Decimal("1"))

    assert result.intervals == ()
    assert result.longest_duration_ms == 0


def test_zero_bound_reproduces_plain_interpolation_and_rounding():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:01.000Z", "2"),
    ]

    plain = calculate_conservative_exposure(readings, Decimal("1"), Decimal("0"))

    assert [(interval.start_ms, interval.end_ms) for interval in plain.intervals] == [
        (readings[0].timestamp + 500, readings[1].timestamp),
    ]
    assert plain.longest_duration_ms == 500


def test_qualified_when_longest_adjusted_interval_reaches_minimum():
    result, qualified = verify_conservative_request(request_(0.5))

    assert result.longest_duration_ms == 1666
    assert qualified is True


def test_not_qualified_when_deduction_shrinks_interval_below_minimum():
    # The raw ramp reaches the threshold halfway up, giving a 2000 ms interval;
    # deducting 0.75 ppm pushes crossings to 80% of each ramp, shrinking the
    # interval to 800 ms, under the 2000 ms minimum.
    payload = {
        "warehouse_id": "A-01",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "measurement_error_ppm": 0.75,
        "readings": [
            {"timestamp": "2026-01-01T00:00:00.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:02.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:04.000Z", "concentration_ppm": 0},
        ],
    }
    model = ConservativeVerificationRequest.model_validate(payload)

    result, qualified = verify_conservative_request(model)

    assert [(interval.start_ms, interval.end_ms) for interval in result.intervals] == [
        (1767225601600, 1767225602400),
    ]
    assert result.longest_duration_ms == 800
    assert qualified is False
