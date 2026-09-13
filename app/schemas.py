"""API response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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


class JointVerificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    warehouse_id: str
    point_ids: tuple[str, ...]
    common_valid_intervals: tuple[ExposureIntervalResponse, ...]
    longest_common_duration_ms: int
    qualified: bool
