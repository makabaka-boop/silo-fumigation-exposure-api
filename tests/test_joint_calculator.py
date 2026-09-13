from decimal import Decimal

from app.calculator import calculate_joint_exposure
from app.domain import Reading


def reading(second: str, concentration: str) -> Reading:
    return Reading(
        timestamp=f"2026-01-01T00:00:{second}Z",
        concentration_ppm=Decimal(concentration),
    )


def spans_of(result) -> list[tuple[int, int]]:
    return [(interval.start_ms, interval.end_ms) for interval in result.intervals]


def test_intersects_two_points_into_the_common_interval():
    # P-1 is valid on [0, 2250], P-2 on [750, 3000].
    p1 = [reading("00.000", "2"), reading("01.500", "2"), reading("03.000", "0")]
    p2 = [reading("00.000", "0"), reading("01.500", "2"), reading("03.000", "2")]

    result = calculate_joint_exposure([p1, p2], Decimal("1"))

    base = p1[0].timestamp
    assert spans_of(result) == [(base + 750, base + 2250)]
    assert result.longest_duration_ms == 1500


def test_touching_closed_endpoints_yield_a_zero_length_common_point():
    # P-1 is valid on [0, 1000], P-2 on [1000, 2000]; both closed, so the
    # shared instant 1000 remains a zero-length common interval.
    p1 = [reading("00.000", "1"), reading("01.000", "1"), reading("02.000", "0")]
    p2 = [reading("00.000", "0"), reading("01.000", "1"), reading("02.000", "1")]

    result = calculate_joint_exposure([p1, p2], Decimal("1"))

    base = p1[0].timestamp
    assert spans_of(result) == [(base + 1000, base + 1000)]
    assert result.longest_duration_ms == 0


def test_intersects_three_points_in_point_order():
    # Valid on [0, 3000], [250, 2750] and [500, 2500] respectively.
    p1 = [reading("00.000", "2"), reading("03.000", "2")]
    p2 = [
        reading("00.000", "0"),
        reading("00.500", "2"),
        reading("02.500", "2"),
        reading("03.000", "0"),
    ]
    p3 = [
        reading("00.000", "0"),
        reading("01.000", "2"),
        reading("02.000", "2"),
        reading("03.000", "0"),
    ]

    result = calculate_joint_exposure([p1, p2, p3], Decimal("1"))

    base = p1[0].timestamp
    assert spans_of(result) == [(base + 500, base + 2500)]
    assert result.longest_duration_ms == 2000


def test_separate_common_intervals_are_not_accumulated():
    # Both points are valid on [250, 1250] and [1750, 2750] only.
    series = [
        reading("00.000", "0"),
        reading("00.500", "2"),
        reading("01.000", "2"),
        reading("01.500", "0"),
        reading("02.000", "2"),
        reading("02.500", "2"),
        reading("03.000", "0"),
    ]

    result = calculate_joint_exposure([series, series], Decimal("1"))

    base = series[0].timestamp
    assert spans_of(result) == [
        (base + 250, base + 1250),
        (base + 1750, base + 2750),
    ]
    assert result.longest_duration_ms == 1000


def test_disjoint_valid_intervals_leave_no_common_interval():
    # P-1 valid on [0, 1500], P-2 valid on [2500, 3000].
    p1 = [
        reading("00.000", "2"),
        reading("01.000", "2"),
        reading("02.000", "0"),
        reading("03.000", "0"),
    ]
    p2 = [
        reading("00.000", "0"),
        reading("01.000", "0"),
        reading("02.000", "0"),
        reading("03.000", "2"),
    ]

    result = calculate_joint_exposure([p1, p2], Decimal("1"))

    assert result.intervals == ()
    assert result.longest_duration_ms == 0
