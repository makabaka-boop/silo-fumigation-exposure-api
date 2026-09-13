"""HTTP routes for one-shot phosphine exposure verification."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.calculator import verify_request
from app.domain import VerificationRequest
from app.schemas import ExposureIntervalResponse, VerificationResponse

router = APIRouter(tags=["verification"])


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
            ExposureIntervalResponse(
                start_unix_ms=interval.start_ms,
                end_unix_ms=interval.end_ms,
                duration_ms=interval.duration_ms,
            )
            for interval in exposure.intervals
        ),
        longest_duration_ms=exposure.longest_duration_ms,
        qualified=qualified,
    )
