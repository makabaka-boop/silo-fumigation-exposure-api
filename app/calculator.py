"""Pure interpolation and exposure-interval calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from app.domain import (
    ConservativeVerificationRequest,
    JointVerificationRequest,
    Reading,
    VerificationRequest,
)


@dataclass(frozen=True)
class ExposureInterval:
    """A closed interval of Unix milliseconds at or above the threshold."""

    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class ExposureResult:
    intervals: tuple[ExposureInterval, ...]
    longest_duration_ms: int


def _round_half_away_from_zero(value: Fraction) -> int:
    numerator, denominator = abs(value.numerator), value.denominator
    rounded_absolute = (2 * numerator + denominator) // (2 * denominator)
    return rounded_absolute if value >= 0 else -rounded_absolute


def _crossing_time_ms(
    left: Reading,
    right: Reading,
    threshold: Decimal,
) -> int:
    elapsed = right.timestamp - left.timestamp
    crossing = Fraction(left.timestamp) + Fraction(
        threshold - left.concentration_ppm
    ) / Fraction(right.concentration_ppm - left.concentration_ppm) * Fraction(
        elapsed
    )
    return _round_half_away_from_zero(crossing)


def _segment_interval(
    left: Reading,
    right: Reading,
    threshold: Decimal,
) -> ExposureInterval | None:
    left_valid = left.concentration_ppm >= threshold
    right_valid = right.concentration_ppm >= threshold

    if left_valid and right_valid:
        start = left.timestamp
        end = right.timestamp
    elif left_valid:
        start = left.timestamp
        end = _crossing_time_ms(left, right, threshold)
    elif right_valid:
        start = _crossing_time_ms(left, right, threshold)
        end = right.timestamp
    else:
        return None

    return ExposureInterval(start_ms=start, end_ms=end)


def _merge_closed_intervals(
    intervals: tuple[ExposureInterval, ...],
) -> tuple[ExposureInterval, ...]:
    if not intervals:
        return ()

    merged: list[ExposureInterval] = [intervals[0]]
    for interval in intervals[1:]:
        previous = merged[-1]
        # Both endpoints are closed, so touching intervals are one continuous
        # interval. Only true gaps remain separate and cannot be accumulated.
        if interval.start_ms <= previous.end_ms:
            merged[-1] = ExposureInterval(
                start_ms=previous.start_ms,
                end_ms=max(previous.end_ms, interval.end_ms),
            )
        else:
            merged.append(interval)
    return tuple(merged)


def calculate_exposure(
    readings: list[Reading], threshold_ppm: Decimal
) -> ExposureResult:
    """Calculate closed, merged valid intervals from linear interpolation."""

    segment_intervals: list[ExposureInterval] = []
    for left, right in zip(readings, readings[1:]):
        interval = _segment_interval(left, right, threshold_ppm)
        if interval is not None:
            segment_intervals.append(interval)

    intervals = _merge_closed_intervals(tuple(segment_intervals))
    longest_duration_ms = max(
        (interval.duration_ms for interval in intervals),
        default=0,
    )
    return ExposureResult(
        intervals=intervals,
        longest_duration_ms=longest_duration_ms,
    )


def verify_request(request: VerificationRequest) -> tuple[ExposureResult, bool]:
    result = calculate_exposure(request.readings, request.threshold_ppm)
    accepted = result.longest_duration_ms >= request.minimum_duration_ms
    return result, accepted


def _readings_after_error_deduction(
    readings: list[Reading], measurement_error_ppm: Decimal
) -> list[Reading]:
    """Lower every concentration by the error bound, clamping at zero."""
    return [
        Reading.model_construct(
            timestamp=reading.timestamp,
            concentration_ppm=max(Decimal(0), reading.concentration_ppm - measurement_error_ppm),
        )
        for reading in readings
    ]


def calculate_conservative_exposure(
    readings: list[Reading],
    threshold_ppm: Decimal,
    measurement_error_ppm: Decimal,
) -> ExposureResult:
    """Exposure intervals after deducting the error bound from each reading."""
    adjusted_readings = _readings_after_error_deduction(
        readings, measurement_error_ppm
    )
    return calculate_exposure(adjusted_readings, threshold_ppm)


def verify_conservative_request(
    request: ConservativeVerificationRequest,
) -> tuple[ExposureResult, bool]:
    result = calculate_conservative_exposure(
        request.readings,
        request.threshold_ppm,
        request.measurement_error_ppm,
    )
    accepted = result.longest_duration_ms >= request.minimum_duration_ms
    return result, accepted


def _intersect_interval_sets(
    left: tuple[ExposureInterval, ...],
    right: tuple[ExposureInterval, ...],
) -> tuple[ExposureInterval, ...]:
    """Intersect two sorted, merged closed-interval sets (closed endpoints)."""

    intersections: list[ExposureInterval] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        start_ms = max(left[left_index].start_ms, right[right_index].start_ms)
        end_ms = min(left[left_index].end_ms, right[right_index].end_ms)
        if start_ms <= end_ms:
            intersections.append(ExposureInterval(start_ms=start_ms, end_ms=end_ms))
        if left[left_index].end_ms <= right[right_index].end_ms:
            left_index += 1
        else:
            right_index += 1
    return tuple(intersections)


def calculate_joint_exposure(
    series_readings: list[list[Reading]], threshold_ppm: Decimal
) -> ExposureResult:
    """Intersect every point's closed valid intervals into common intervals."""

    per_point_intervals = [
        calculate_exposure(readings, threshold_ppm).intervals
        for readings in series_readings
    ]

    common = per_point_intervals[0]
    for intervals in per_point_intervals[1:]:
        common = _merge_closed_intervals(_intersect_interval_sets(common, intervals))

    longest_duration_ms = max(
        (interval.duration_ms for interval in common),
        default=0,
    )
    return ExposureResult(
        intervals=common,
        longest_duration_ms=longest_duration_ms,
    )


def verify_joint_request(
    request: JointVerificationRequest,
) -> tuple[ExposureResult, bool]:
    result = calculate_joint_exposure(
        [series.readings for series in request.points],
        request.threshold_ppm,
    )
    accepted = result.longest_duration_ms >= request.minimum_duration_ms
    return result, accepted
