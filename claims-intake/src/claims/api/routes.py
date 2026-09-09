"""HTTP surface for the claims intake service.

This layer does three things and no more: it parses the request, it calls the
service, and it maps the outcome to a status code. It holds no rule logic. A rule
that appears here is a rule the service layer cannot be tested for.

Day 4 lab. Implement against `docs/api-contract.md` sections 5 and 6.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from claims.models import NotificationRequest, RecordedNotification, RuleFailure
from claims.policy_client import (
    LookupFailureReason,
    PolicyClient,
    PolicyLookupFailed,
    StubPolicyClient,
)
from claims.repository import NotificationRepository
from claims.service import submit_notification

app = FastAPI(title="Claims Intake Service")

# Contract §6, row by row. Status codes are assigned from this table, not from
# if/elif branches. INVALID_REQUEST is included so a parse failure cannot drift
# off the documented 400.
STATUS_BY_CODE: dict[str, int] = {
    "INVALID_REQUEST": 400,
    "POLICY_NOT_FOUND": 422,
    "DUPLICATE_NOTIFICATION": 409,
    "LOSS_BEFORE_INCEPTION": 422,
    "POLICY_CANCELLED": 422,
    "LOSS_AFTER_EXPIRY": 422,
    "AMOUNT_EXCEEDS_LIMIT": 422,
    "TYPE_NOT_COVERED": 422,
    "POLICY_MASTER_UNREACHABLE": 503,
    "POLICY_MASTER_TIMEOUT": 504,
    "POLICY_MASTER_UNPARSABLE": 502,
}

# Contract §6: the three PolicyLookupFailed reasons to their distinct 5xx statuses.
LOOKUP_STATUS_BY_REASON: dict[LookupFailureReason, int] = {
    "unreachable": 503,
    "timeout": 504,
    "unparsable": 502,
}

LOOKUP_CODE_BY_REASON: dict[LookupFailureReason, str] = {
    "unreachable": "POLICY_MASTER_UNREACHABLE",
    "timeout": "POLICY_MASTER_TIMEOUT",
    "unparsable": "POLICY_MASTER_UNPARSABLE",
}

MESSAGE_BY_CODE: dict[str, str] = {
    "INVALID_REQUEST": "The request body is not well formed.",
    "POLICY_NOT_FOUND": "No policy exists with that number.",
    "DUPLICATE_NOTIFICATION": "A notification for this loss has already been recorded.",
    "LOSS_BEFORE_INCEPTION": "Loss date precedes policy inception.",
    "POLICY_CANCELLED": "The policy was cancelled before the loss date.",
    "LOSS_AFTER_EXPIRY": "Loss date falls after policy expiry.",
    "AMOUNT_EXCEEDS_LIMIT": "The estimated amount exceeds the policy limit.",
    "TYPE_NOT_COVERED": "The claim type is not covered by this policy.",
    "POLICY_MASTER_UNREACHABLE": "The policy master could not be reached.",
    "POLICY_MASTER_TIMEOUT": "The policy master did not answer in time.",
    "POLICY_MASTER_UNPARSABLE": "The policy master returned an unreadable response.",
}

_policy_client = StubPolicyClient()
_repository = NotificationRepository()


def get_policy_client() -> PolicyClient:
    return _policy_client


def get_repository() -> NotificationRepository:
    return _repository


def _error_body(code: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "message": MESSAGE_BY_CODE[code],
        "detail": jsonable_encoder(detail),
    }


def _error_response(code: str, detail: dict[str, Any], status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_error_body(code, detail))


def _reason_for_pydantic_type(error_type: str) -> str:
    if error_type == "missing":
        return "required_field_absent"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "json_invalid":
        return "invalid_json"
    if error_type.endswith(("_type", "_parsing")):
        return "wrong_type"
    return "invalid_value"


def _detail_from_validation_errors(errors: Sequence[Any]) -> dict[str, Any]:
    if not errors:
        return {"field": None, "reason": "invalid_value"}
    error = errors[0]
    loc = error.get("loc", ())
    field_parts = [str(part) for part in loc if part != "body"]
    field = field_parts[0] if field_parts else None
    return {
        "field": field,
        "reason": _reason_for_pydantic_type(str(error.get("type", ""))),
    }


def _invalid_request_response(errors: Sequence[Any]) -> JSONResponse:
    return _error_response(
        "INVALID_REQUEST",
        _detail_from_validation_errors(errors),
        STATUS_BY_CODE["INVALID_REQUEST"],
    )


def _rule_failure_response(failure: RuleFailure) -> JSONResponse:
    code = str(failure.code)
    return _error_response(
        code,
        {"rule": str(failure.rule), **failure.detail},
        STATUS_BY_CODE[code],
    )


def _lookup_failure_response(error: PolicyLookupFailed) -> JSONResponse:
    code = LOOKUP_CODE_BY_REASON[error.reason]
    return _error_response(
        code,
        {"policy_number": error.policy_number, "reason": error.reason},
        LOOKUP_STATUS_BY_REASON[error.reason],
    )


def _recorded_response(recorded: RecordedNotification) -> JSONResponse:
    return JSONResponse(status_code=201, content=recorded.model_dump())


@app.exception_handler(RequestValidationError)
def handle_request_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Contract §2.4 / §5: an uninterpretable body is 400 INVALID_REQUEST."""
    return _invalid_request_response(exc.errors())


@app.exception_handler(ValidationError)
def handle_validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
    return _invalid_request_response(exc.errors())


@app.post("/notifications")
def post_notification(
    notification: NotificationRequest,
    policy_client: Annotated[PolicyClient, Depends(get_policy_client)],
    repository: Annotated[NotificationRepository, Depends(get_repository)],
) -> JSONResponse:
    """Accept a first notice of loss. Extra fields are rejected by NotificationRequest."""
    try:
        outcome = submit_notification(notification, policy_client, repository)
    except PolicyLookupFailed as error:
        return _lookup_failure_response(error)
    if isinstance(outcome, RecordedNotification):
        return _recorded_response(outcome)
    return _rule_failure_response(outcome)
