"""API response schemas."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


class ExposureIntervalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_unix_ms: int
    end_unix_ms: int
    duration_ms: int


class VerificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    warehouse_id: str
    valid_intervals: tuple[ExposureIntervalResponse, ...]
    longest_duration_ms: int
    qualified: bool


class ConservativeVerificationResponse(VerificationResponse):
    """Same shape as VerificationResponse, plus the conservative bound."""

    measurement_error_ppm: Decimal

    @field_serializer("measurement_error_ppm")
    def _serialize_measurement_error(self, value: Decimal) -> int | float:
        # Echo the bound as a JSON number, preserving its written precision.
        return int(value) if value == value.to_integral_value() else float(value)


class JointVerificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    warehouse_id: str
    point_ids: tuple[str, ...]
    common_valid_intervals: tuple[ExposureIntervalResponse, ...]
    longest_common_duration_ms: int
    qualified: bool


class WindowVerificationResponse(VerificationResponse):
    """Same shape as VerificationResponse, plus the echoed window bounds."""

    window_start_unix_ms: int
    window_end_unix_ms: int
