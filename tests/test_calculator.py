from decimal import Decimal

from app.calculator import calculate_exposure
from app.domain import Reading


def reading(ts: str, concentration: str) -> Reading:
    return Reading(
        timestamp=ts,
        concentration_ppm=Decimal(concentration),
    )


def test_zero_length_valid_endpoints_inside_a_gap_remain_separate():
    # The first and third samples equal the threshold, but the sample between
    # them is below it, so those isolated closed points do not connect.
    readings = [
        reading("2026-01-01T00:00:00.000Z", "2"),
        reading("2026-01-01T00:00:01.000Z", "1"),
        reading("2026-01-01T00:00:02.000Z", "2"),
        reading("2026-01-01T00:00:03.000Z", "3"),
    ]

    result = calculate_exposure(readings, Decimal("2"))

    assert [(interval.start_ms, interval.end_ms) for interval in result.intervals] == [
        (readings[0].timestamp, readings[0].timestamp),
        (readings[2].timestamp, readings[3].timestamp),
    ]
    assert result.longest_duration_ms == 1000


def test_merges_intervals_touching_at_a_closed_crossing_point():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "2"),
        reading("2026-01-01T00:00:01.000Z", "1"),
        reading("2026-01-01T00:00:02.000Z", "0"),
    ]

    result = calculate_exposure(readings, Decimal("1"))

    assert [(interval.start_ms, interval.end_ms) for interval in result.intervals] == [
        (readings[0].timestamp, readings[1].timestamp),
    ]
    assert result.longest_duration_ms == 1000


def test_separated_intervals_are_not_accumulated():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:01.000Z", "2"),
        reading("2026-01-01T00:00:02.000Z", "2"),
        reading("2026-01-01T00:00:03.000Z", "0"),
        reading("2026-01-01T00:00:04.000Z", "0"),
        reading("2026-01-01T00:00:05.000Z", "2"),
        reading("2026-01-01T00:00:06.000Z", "2"),
        reading("2026-01-01T00:00:07.000Z", "0"),
    ]

    result = calculate_exposure(readings, Decimal("1"))

    assert [(interval.start_ms, interval.end_ms) for interval in result.intervals] == [
        (readings[0].timestamp + 500, readings[2].timestamp + 500),
        (readings[4].timestamp + 500, readings[6].timestamp + 500),
    ]
    assert result.longest_duration_ms == 2000


def test_threshold_equality_forms_closed_intervals():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "1"),
        reading("2026-01-01T00:00:01.000Z", "1"),
        reading("2026-01-01T00:00:02.000Z", "0"),
    ]

    result = calculate_exposure(readings, Decimal("1"))

    assert len(result.intervals) == 1
    assert result.intervals[0].start_ms == readings[0].timestamp
    assert result.intervals[0].end_ms == readings[1].timestamp
    assert result.longest_duration_ms == 1000


def test_half_millisecond_rounds_away_from_zero_positive_and_negative():
    # A one-millisecond segment crossing halfway gives +0.5 ms.
    positive = [
        reading("1970-01-01T00:00:00.000Z", "0"),
        reading("1970-01-01T00:00:00.001Z", "2"),
    ]
    positive_result = calculate_exposure(positive, Decimal("1"))
    assert positive_result.intervals[0].start_ms == 1
    assert positive_result.longest_duration_ms == 0

    # Crossing halfway at one millisecond before the Unix epoch gives -0.5 ms.
    negative = [
        reading("1969-12-31T23:59:59.999Z", "2"),
        reading("1970-01-01T00:00:00.000Z", "0"),
    ]
    negative_result = calculate_exposure(negative, Decimal("1"))
    assert negative_result.intervals[0].end_ms == -1
    assert negative_result.longest_duration_ms == 0


def test_empty_result_has_zero_longest_duration():
    readings = [
        reading("2026-01-01T00:00:00.000Z", "0"),
        reading("2026-01-01T00:00:01.000Z", "0"),
    ]

    result = calculate_exposure(readings, Decimal("1"))

    assert result.intervals == ()
    assert result.longest_duration_ms == 0
