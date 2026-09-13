"""Pure interpolation and exposure-interval calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.domain import Reading, VerificationRequest


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


def _round_half_away_from_zero(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _crossing_time_ms(
    left: Reading,
    right: Reading,
    threshold: Decimal,
) -> int:
    elapsed = Decimal(right.timestamp - left.timestamp)
    concentration_change = right.concentration_ppm - left.concentration_ppm
    crossing = Decimal(left.timestamp) + elapsed * (
        threshold - left.concentration_ppm
    ) / concentration_change
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
