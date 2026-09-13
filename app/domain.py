"""Domain contracts and value validation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError


_TIMESTAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z$"
)


def _reject_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise PydanticCustomError(
            "value_error.not_a_number",
            "Boolean values are not accepted as numbers.",
        )
    return value


def _parse_finite_decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, str):
        raise PydanticCustomError(
            "value_error.not_a_number",
            "{field_name} must be a JSON number, not a string.",
            {"field_name": field_name},
        )
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PydanticCustomError(
            "value_error.not_a_number",
            "{field_name} must be a finite decimal number.",
            {"field_name": field_name},
        ) from exc
    if not result.is_finite():
        raise PydanticCustomError(
            "value_error.not_finite",
            "{field_name} must be a finite number.",
            {"field_name": field_name},
        )
    return result


def validate_non_negative_concentration(value: Any) -> Decimal:
    value = _reject_bool(value)
    result = _parse_finite_decimal(value, field_name="concentration")
    if result < 0:
        raise PydanticCustomError(
            "value_error.negative",
            "Concentration must be non-negative.",
        )
    return result


def validate_non_negative_threshold(value: Any) -> Decimal:
    value = _reject_bool(value)
    result = _parse_finite_decimal(value, field_name="threshold")
    if result < 0:
        raise PydanticCustomError(
            "value_error.negative",
            "Threshold must be non-negative.",
        )
    return result


def validate_minimum_duration(value: Any) -> Decimal:
    value = _reject_bool(value)
    result = _parse_finite_decimal(value, field_name="minimum duration")
    if result <= 0:
        raise PydanticCustomError(
            "value_error.not_positive",
            "Minimum duration must be greater than zero.",
        )
    if max(0, -result.as_tuple().exponent) > 3:
        raise PydanticCustomError(
            "value_error.too_many_decimal_places",
            "Minimum duration may have at most three decimal places.",
        )
    return result


def parse_utc_millisecond_timestamp(value: Any) -> int:
    if not isinstance(value, str):
        raise PydanticCustomError(
            "value_error.timestamp_not_string",
            "Timestamp must be an ISO 8601 UTC string.",
        )

    match = _TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise PydanticCustomError(
            "value_error.invalid_timestamp",
            "Timestamp must use YYYY-MM-DDTHH:mm:ss.sssZ.",
        )

    year, month, day, hour, minute, second, millisecond = map(int, match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise PydanticCustomError(
            "value_error.invalid_calendar_date",
            "Timestamp contains an invalid calendar date.",
        )
    if hour > 23 or minute > 59 or second > 59:
        raise PydanticCustomError(
            "value_error.invalid_clock_time",
            "Timestamp contains an invalid UTC time.",
        )

    # Howard Hinnant's civil-date algorithm. This avoids platform-dependent
    # datetime limits and preserves milliseconds without binary fractions.
    adjusted_year = year - (1 if month <= 2 else 0)
    era = adjusted_year // 400
    year_of_era = adjusted_year - era * 400
    month_origin = month + (-3 if month > 2 else 9)
    day_of_year = (153 * month_origin + 2) // 5 + day - 1
    day_of_era = (
        year_of_era * 365
        + year_of_era // 4
        - year_of_era // 100
        + day_of_year
    )
    days_since_epoch = era * 146097 + day_of_era - 719468

    if not _is_valid_civil_date(year, month, day):
        raise PydanticCustomError(
            "value_error.invalid_calendar_date",
            "Timestamp contains an invalid calendar date.",
        )

    return (
        days_since_epoch * 86_400_000
        + hour * 3_600_000
        + minute * 60_000
        + second * 1_000
        + millisecond
    )


def _is_valid_civil_date(year: int, month: int, day: int) -> bool:
    days_in_month = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0):
        days_in_month[2] = 29
    return day <= days_in_month[month]


NonNegativeConcentration = Annotated[
    Decimal,
    BeforeValidator(validate_non_negative_concentration),
]
NonNegativeThreshold = Annotated[
    Decimal,
    BeforeValidator(validate_non_negative_threshold),
]
PositiveDuration = Annotated[
    Decimal,
    BeforeValidator(validate_minimum_duration),
]
UtcMillisecondTimestamp = Annotated[
    int,
    BeforeValidator(parse_utc_millisecond_timestamp),
]


class Reading(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    timestamp: UtcMillisecondTimestamp
    concentration_ppm: NonNegativeConcentration


def _series_span_ms(readings: list[Reading]) -> int:
    return readings[-1].timestamp - readings[0].timestamp


def _ensure_strictly_increasing(readings: list[Reading]) -> None:
    previous_timestamp = readings[0].timestamp
    for index in range(1, len(readings)):
        if readings[index].timestamp <= previous_timestamp:
            raise PydanticCustomError(
                "value_error.timestamps_not_strictly_increasing",
                "Readings must be strictly increasing in time.",
                {"index": index, "timestamp": readings[index].timestamp},
            )
        previous_timestamp = readings[index].timestamp


def _ensure_span_reaches_minimum_duration(
    readings: list[Reading], minimum_duration_ms: int
) -> None:
    span_ms = _series_span_ms(readings)
    if span_ms < minimum_duration_ms:
        raise PydanticCustomError(
            "value_error.span_shorter_than_minimum_duration",
            "The first and last readings must span at least the minimum duration.",
            {
                "span_ms": span_ms,
                "minimum_duration_ms": minimum_duration_ms,
            },
        )


class VerificationRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    warehouse_id: Annotated[str, Field(min_length=1)]
    threshold_ppm: NonNegativeThreshold
    minimum_duration_seconds: PositiveDuration
    readings: Annotated[list[Reading], Field(min_length=2)]

    @field_validator("warehouse_id")
    @classmethod
    def validate_warehouse_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise PydanticCustomError(
                "value_error.empty_warehouse_id",
                "Warehouse ID must contain at least one non-whitespace character.",
            )
        return stripped

    @field_validator("readings")
    @classmethod
    def validate_reading_series(
        cls, readings: list[Reading], info: ValidationInfo
    ) -> list[Reading]:
        if len(readings) < 2:
            raise PydanticCustomError(
                "value_error.too_few_readings",
                "At least two readings are required.",
            )

        _ensure_strictly_increasing(readings)

        minimum_duration = info.data.get("minimum_duration_seconds")
        if minimum_duration is not None:
            minimum_duration_ms = int(
                (minimum_duration * Decimal(1000)).to_integral_value()
            )
            _ensure_span_reaches_minimum_duration(readings, minimum_duration_ms)

        return readings

    @property
    def minimum_duration_ms(self) -> int:
        return int((self.minimum_duration_seconds * Decimal(1000)).to_integral_value())

    @property
    def span_ms(self) -> int:
        return self.readings[-1].timestamp - self.readings[0].timestamp


class MeasurementSeries(BaseModel):
    """One measurement point's strictly increasing reading series."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    point_id: Annotated[str, Field(min_length=1)]
    readings: Annotated[list[Reading], Field(min_length=2)]

    @field_validator("point_id")
    @classmethod
    def validate_point_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise PydanticCustomError(
                "value_error.empty_point_id",
                "Point ID must contain at least one non-whitespace character.",
            )
        return stripped

    @field_validator("readings")
    @classmethod
    def validate_reading_series(cls, readings: list[Reading]) -> list[Reading]:
        if len(readings) < 2:
            raise PydanticCustomError(
                "value_error.too_few_readings",
                "At least two readings are required.",
            )
        _ensure_strictly_increasing(readings)
        return readings

    @property
    def span_ms(self) -> int:
        return _series_span_ms(self.readings)


class JointVerificationRequest(BaseModel):
    """Joint decision over two to ten measurement points in one warehouse."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    warehouse_id: Annotated[str, Field(min_length=1)]
    threshold_ppm: NonNegativeThreshold
    minimum_duration_seconds: PositiveDuration
    points: Annotated[list[MeasurementSeries], Field(min_length=2, max_length=10)]

    @field_validator("warehouse_id")
    @classmethod
    def validate_warehouse_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise PydanticCustomError(
                "value_error.empty_warehouse_id",
                "Warehouse ID must contain at least one non-whitespace character.",
            )
        return stripped

    @model_validator(mode="after")
    def validate_joint_series(self) -> "JointVerificationRequest":
        errors: list[InitErrorDetails] = []
        minimum_duration_ms = self.minimum_duration_ms

        seen_point_ids: set[str] = set()
        for index, series in enumerate(self.points):
            if series.point_id in seen_point_ids:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "value_error.duplicate_point_id",
                            "Point IDs must be unique across the joint request.",
                            {"point_id": series.point_id},
                        ),
                        "loc": ("points", index, "point_id"),
                        "input": series.point_id,
                    }
                )
            else:
                seen_point_ids.add(series.point_id)

            if series.span_ms < minimum_duration_ms:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "value_error.span_shorter_than_minimum_duration",
                            "The first and last readings must span at least the minimum duration.",
                            {
                                "span_ms": series.span_ms,
                                "minimum_duration_ms": minimum_duration_ms,
                            },
                        ),
                        "loc": ("points", index, "readings"),
                        "input": series.readings,
                    }
                )

        reference = self.points[0]
        for index, series in enumerate(self.points[1:], start=1):
            if series.readings[0].timestamp != reference.readings[0].timestamp:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "value_error.series_time_bounds_mismatch",
                            "All series must share the same first and last timestamps.",
                            {
                                "expected_unix_ms": reference.readings[0].timestamp,
                                "actual_unix_ms": series.readings[0].timestamp,
                            },
                        ),
                        "loc": ("points", index, "readings", 0, "timestamp"),
                        "input": series.readings[0].timestamp,
                    }
                )
            if series.readings[-1].timestamp != reference.readings[-1].timestamp:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "value_error.series_time_bounds_mismatch",
                            "All series must share the same first and last timestamps.",
                            {
                                "expected_unix_ms": reference.readings[-1].timestamp,
                                "actual_unix_ms": series.readings[-1].timestamp,
                            },
                        ),
                        "loc": (
                            "points",
                            index,
                            "readings",
                            len(series.readings) - 1,
                            "timestamp",
                        ),
                        "input": series.readings[-1].timestamp,
                    }
                )

        if errors:
            raise ValidationError.from_exception_data(
                self.__class__.__name__, errors
            )
        return self

    @property
    def minimum_duration_ms(self) -> int:
        return int((self.minimum_duration_seconds * Decimal(1000)).to_integral_value())
