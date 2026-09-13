"""HTTP routes for one-shot phosphine exposure verification."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.calculator import verify_joint_request, verify_request
from app.domain import JointVerificationRequest, VerificationRequest
from app.schemas import (
    ExposureIntervalResponse,
    JointVerificationResponse,
    VerificationResponse,
)

router = APIRouter(tags=["verification"])


def _interval_response(interval) -> ExposureIntervalResponse:
    return ExposureIntervalResponse(
        start_unix_ms=interval.start_ms,
        end_unix_ms=interval.end_ms,
        duration_ms=interval.duration_ms,
    )


@router.post(
    "/verify",
    response_model=VerificationResponse,
    status_code=status.HTTP_200_OK,
)
def verify(
    request: VerificationRequest,
) -> VerificationResponse:
    exposure, qualified = verify_request(request)
    return VerificationResponse(
        warehouse_id=request.warehouse_id,
        valid_intervals=tuple(
            _interval_response(interval) for interval in exposure.intervals
        ),
        longest_duration_ms=exposure.longest_duration_ms,
        qualified=qualified,
    )


@router.post(
    "/verify-joint",
    response_model=JointVerificationResponse,
    status_code=status.HTTP_200_OK,
)
def verify_joint(
    request: JointVerificationRequest,
) -> JointVerificationResponse:
    exposure, qualified = verify_joint_request(request)
    return JointVerificationResponse(
        warehouse_id=request.warehouse_id,
        point_ids=tuple(series.point_id for series in request.points),
        common_valid_intervals=tuple(
            _interval_response(interval) for interval in exposure.intervals
        ),
        longest_common_duration_ms=exposure.longest_duration_ms,
        qualified=qualified,
    )
