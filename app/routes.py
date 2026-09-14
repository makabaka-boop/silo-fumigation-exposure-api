"""HTTP routes for one-shot phosphine exposure verification."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.routing import APIRoute

from app.calculator import (
    verify_conservative_request,
    verify_joint_request,
    verify_request,
)
from app.domain import (
    ConservativeVerificationRequest,
    JointVerificationRequest,
    VerificationRequest,
)
from app.schemas import (
    ConservativeVerificationResponse,
    ExposureIntervalResponse,
    JointVerificationResponse,
    VerificationResponse,
)


class _DecimalJsonRequest(Request):
    """Request whose JSON body keeps every number's written precision.

    The default float parsing silently drops trailing zeros (``2.0000``
    becomes ``2.0``), which would hide violations of the
    at-most-three-decimal-places contract for ``minimum_duration_seconds``.
    """

    async def json(self) -> Any:
        if not hasattr(self, "_json"):
            body = await self.body()
            self._json = json.loads(body, parse_float=Decimal)
        return self._json


class _DecimalJsonRoute(APIRoute):
    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def handler(request: Request) -> Response:
            decimal_request = _DecimalJsonRequest(request.scope, request.receive)
            return await original_handler(decimal_request)

        return handler


router = APIRouter(tags=["verification"], route_class=_DecimalJsonRoute)


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
    "/verify-conservative",
    response_model=ConservativeVerificationResponse,
    status_code=status.HTTP_200_OK,
)
def verify_conservative(
    request: ConservativeVerificationRequest,
) -> ConservativeVerificationResponse:
    exposure, qualified = verify_conservative_request(request)
    return ConservativeVerificationResponse(
        warehouse_id=request.warehouse_id,
        valid_intervals=tuple(
            _interval_response(interval) for interval in exposure.intervals
        ),
        longest_duration_ms=exposure.longest_duration_ms,
        qualified=qualified,
        measurement_error_ppm=request.measurement_error_ppm,
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
