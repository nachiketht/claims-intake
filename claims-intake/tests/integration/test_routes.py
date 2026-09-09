"""HTTP integration tests for the claims intake surface.

Exercises `POST /notifications` through FastAPI's test client. The service
function is never called directly: these tests pin the status codes, error
envelope, and claim-reference format that callers actually receive.

Run:

    uv run pytest tests/integration/test_routes.py -q
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from claims.api.routes import app, get_policy_client, get_repository
from claims.policy_client import LookupFailureReason, StubPolicyClient
from claims.repository import NotificationRepository

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CLAIM_REFERENCE_PATTERN = re.compile(r"^CLM-\d{4}-\d{6}$")
ENDPOINT = "/notifications"

RULE_CODES = frozenset(
    {
        "POLICY_NOT_FOUND",
        "DUPLICATE_NOTIFICATION",
        "LOSS_BEFORE_INCEPTION",
        "POLICY_CANCELLED",
        "LOSS_AFTER_EXPIRY",
        "AMOUNT_EXCEEDS_LIMIT",
        "TYPE_NOT_COVERED",
    }
)
DEPENDENCY_CODES = frozenset(
    {
        "POLICY_MASTER_UNREACHABLE",
        "POLICY_MASTER_TIMEOUT",
        "POLICY_MASTER_UNPARSABLE",
    }
)

# Contract §6 matches routes.STATUS_BY_CODE / LOOKUP_STATUS_BY_REASON.
LOOKUP_FAILURES: tuple[tuple[LookupFailureReason, int, str], ...] = (
    ("unreachable", 503, "POLICY_MASTER_UNREACHABLE"),
    ("timeout", 504, "POLICY_MASTER_TIMEOUT"),
    ("unparsable", 502, "POLICY_MASTER_UNPARSABLE"),
)


def _load_payloads(filename: str) -> dict[str, dict[str, Any]]:
    records = json.loads((DATA_DIR / filename).read_text())
    return {record["id"]: record["payload"] for record in records}


VALID_PAYLOADS = _load_payloads("fnol_valid.json")
INVALID_PAYLOADS = _load_payloads("fnol_invalid.json")


@pytest.fixture
def repository() -> NotificationRepository:
    return NotificationRepository()


@pytest.fixture
def client(
    policy_client: StubPolicyClient, repository: NotificationRepository
) -> Iterator[TestClient]:
    app.dependency_overrides[get_policy_client] = lambda: policy_client
    app.dependency_overrides[get_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(ENDPOINT, json=payload)


def _assert_detail_contains(detail: dict[str, Any], expected: dict[str, Any]) -> None:
    for key, value in expected.items():
        assert key in detail, f"detail missing {key!r}: {detail}"
        actual = detail[key]
        if isinstance(value, Decimal) or key in {"estimated_amount", "limit"}:
            assert Decimal(str(actual)) == Decimal(str(value))
        else:
            assert actual == value


def test_accepted_notification_returns_201_and_claim_reference(client: TestClient) -> None:
    payload = VALID_PAYLOADS["VALID-01"]
    response = _post(client, payload)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "recorded"
    assert CLAIM_REFERENCE_PATTERN.fullmatch(body["claim_reference"])


@pytest.mark.parametrize(
    ("case_id", "status", "code", "rule", "detail"),
    [
        pytest.param(
            "INVALID-01",
            422,
            "POLICY_NOT_FOUND",
            "V-1",
            {"policy_number": "MOT-9999"},
            id="V-1",
        ),
        pytest.param(
            "INVALID-02",
            422,
            "LOSS_BEFORE_INCEPTION",
            "V-2",
            {"loss_date": "2026-02-20", "effective_date": "2026-03-15"},
            id="V-2",
        ),
        pytest.param(
            "INVALID-03",
            422,
            "LOSS_AFTER_EXPIRY",
            "V-3",
            {"loss_date": "2026-03-20", "expiry_date": "2026-02-28"},
            id="V-3",
        ),
        pytest.param(
            "INVALID-04",
            422,
            "AMOUNT_EXCEEDS_LIMIT",
            "V-4",
            {"estimated_amount": Decimal("14500.00"), "limit": Decimal("10000.00")},
            id="V-4",
        ),
        pytest.param(
            "INVALID-05",
            422,
            "TYPE_NOT_COVERED",
            "V-5",
            {"claim_type": "collision", "permitted_claim_types": ["liability"]},
            id="V-5",
        ),
        pytest.param(
            "INVALID-06",
            409,
            "DUPLICATE_NOTIFICATION",
            "V-6",
            {},
            id="V-6",
        ),
        pytest.param(
            "INVALID-07",
            422,
            "POLICY_CANCELLED",
            "V-7",
            {"loss_date": "2026-03-05", "cancellation_date": "2026-02-01"},
            id="V-7",
        ),
    ],
)
def test_invalid_payloads_are_rejected_with_rule_envelope(
    client: TestClient,
    case_id: str,
    status: int,
    code: str,
    rule: str,
    detail: dict[str, Any],
) -> None:
    if case_id == "INVALID-06":
        first = _post(client, VALID_PAYLOADS["VALID-01"])
        assert first.status_code == 201
        detail = {"claim_reference": first.json()["claim_reference"]}

    response = _post(client, INVALID_PAYLOADS[case_id])
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["detail"]["rule"] == rule
    _assert_detail_contains(body["detail"], detail)


def test_missing_required_field_is_400_with_non_rule_code(client: TestClient) -> None:
    payload = dict(VALID_PAYLOADS["VALID-01"])
    del payload["estimated_amount"]
    response = _post(client, payload)
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert body["code"] not in RULE_CODES
    assert "rule" not in body["detail"]
    assert body["detail"]["field"] == "estimated_amount"


def test_unexpected_field_is_rejected_not_silently_accepted(client: TestClient) -> None:
    payload = dict(VALID_PAYLOADS["VALID-01"])
    payload["unexpected_field"] = "should-not-be-accepted"
    response = _post(client, payload)
    assert response.status_code == 400
    assert response.status_code != 201
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert "rule" not in body["detail"]
    assert body["detail"]["field"] == "unexpected_field"


@pytest.mark.parametrize(
    ("reason", "status", "code"),
    [pytest.param(*row, id=row[2]) for row in LOOKUP_FAILURES],
)
def test_policy_lookup_failed_maps_reason_to_distinct_5xx(
    client: TestClient,
    policy_client: StubPolicyClient,
    reason: LookupFailureReason,
    status: int,
    code: str,
) -> None:
    policy_client.fail_with = reason
    response = _post(client, VALID_PAYLOADS["VALID-01"])
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["code"] in DEPENDENCY_CODES
    assert body["code"] != "POLICY_NOT_FOUND"
    assert "rule" not in body["detail"]
    assert body["detail"]["reason"] == reason
    assert body["detail"]["policy_number"] == VALID_PAYLOADS["VALID-01"]["policy_number"]


def test_policy_not_found_is_422_not_a_dependency_failure(client: TestClient) -> None:
    response = _post(client, INVALID_PAYLOADS["INVALID-01"])
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "POLICY_NOT_FOUND"
    assert body["code"] not in DEPENDENCY_CODES
    assert body["detail"]["rule"] == "V-1"
    assert body["detail"]["policy_number"] == INVALID_PAYLOADS["INVALID-01"]["policy_number"]
