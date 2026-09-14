from decimal import Decimal
from fractions import Fraction

from app.calculator import (
    calculate_exposure,
    calculate_window_exposure,
    windowed_readings,
)
from app.domain import Reading


def reading(ts: str, concentration: str) -> Reading:
    return Reading(
        timestamp=ts,
        concentration_ppm=Decimal(concentration),
    )


def classic_series() -> list[Reading]:
    return [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:01.000Z", "2"),
        reading("2026-01-01T00:00:02.000Z", "2"),
        reading("2026-01-01T00:00:03.000Z", "0"),
        reading("2026-01-01T00:00:04.000Z", "0"),
        reading("2026-01-01T00:00:05.000Z", "2"),
        reading("2026-01-01T00:00:06.000Z", "2"),
        reading("2026-01-01T00:00:07.000Z", "0"),
    ]


def test_windowed_readings_reuses_samples_landing_exactly_on_boundaries():
    readings = classic_series()
    first = readings[0].timestamp

    windowed = windowed_readings(readings, first + 3000, first + 5000)

    assert windowed == [readings[3], readings[4], readings[5]]
    assert all(windowed[i] is readings[3 + i] for i in range(3))
    timestamps = [item.timestamp for item in windowed]
    assert len(timestamps) == len(set(timestamps))


def test_windowed_readings_interpolates_virtual_endpoints_exactly():
    readings = classic_series()
    first = readings[0].timestamp

    windowed = windowed_readings(readings, first + 250, first + 2750)

    assert [item.timestamp for item in windowed] == [
        first + 250,
        first + 1000,
        first + 2000,
        first + 2750,
    ]
    # 250 ms into the 0 -> 2 ppm ramp gives exactly 0.5 ppm; 750 ms into the
    # 2 -> 0 ppm ramp gives exactly 0.5 ppm again.
    assert windowed[0].concentration_ppm == Fraction(1, 2)
    assert windowed[-1].concentration_ppm == Fraction(1, 2)
    assert windowed[1] is readings[1]
    assert windowed[2] is readings[2]


def test_windowed_readings_keeps_non_terminating_interpolation_exact():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:03.000Z", "1"),
    ]
    first = readings[0].timestamp

    windowed = windowed_readings(readings, first + 1000, first + 2000)

    # One third of the ramp is 1/3 ppm, which no finite Decimal can hold.
    assert windowed[0].concentration_ppm == Fraction(1, 3)
    assert windowed[1].concentration_ppm == Fraction(2, 3)


def test_windowed_readings_without_interior_samples_returns_two_endpoints():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:04.000Z", "4"),
    ]
    first = readings[0].timestamp

    windowed = windowed_readings(readings, first + 1000, first + 3000)

    assert [item.timestamp for item in windowed] == [first + 1000, first + 3000]
    assert windowed[0].concentration_ppm == Fraction(1)
    assert windowed[1].concentration_ppm == Fraction(3)


def test_window_exposure_clips_intervals_to_the_window():
    readings = classic_series()
    first = readings[0].timestamp

    # The full series is valid on [500, 2500] and [4500, 6500]; the window
    # [1250, 2750] clips the first interval and drops the second entirely.
    result = calculate_window_exposure(
        readings, Decimal("1"), first + 1250, first + 2750
    )

    assert [(i.start_ms, i.end_ms) for i in result.intervals] == [
        (first + 1250, first + 2500),
    ]
    assert result.longest_duration_ms == 1250


def test_window_exposure_excludes_valid_time_outside_the_window():
    readings = classic_series()
    first = readings[0].timestamp

    result = calculate_window_exposure(
        readings, Decimal("1"), first + 3000, first + 5000
    )

    assert [(i.start_ms, i.end_ms) for i in result.intervals] == [
        (first + 4500, first + 5000),
    ]
    assert result.longest_duration_ms == 500


def test_window_covering_the_whole_series_matches_plain_exposure():
    readings = classic_series()
    first = readings[0].timestamp
    last = readings[-1].timestamp

    windowed_result = calculate_window_exposure(
        readings, Decimal("1"), first, last
    )
    plain_result = calculate_exposure(readings, Decimal("1"))

    assert windowed_result == plain_result
    assert windowed_result.longest_duration_ms == 2000
