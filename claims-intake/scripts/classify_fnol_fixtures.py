"""Classify FNOL fixtures as well-formed or 400 INVALID_REQUEST.

Comparison-worktree variant of the RequestValidationError / contract §6 table
work. Does not change `src/claims/api/routes.py`. Shape failures stay at 400;
rule and dependency codes never appear on a body that did not parse.

Run from this worktree's `claims-intake/` directory:

    PYTHONPATH=src uv run python scripts/classify_fnol_fixtures.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.models import NotificationRequest  # noqa: E402

# Contract §6. Status codes are assigned from these tables, not from if/elif.
INVALID_REQUEST_STATUS = 400

RULE_STATUS: dict[str, int] = {
    "POLICY_NOT_FOUND": 422,
    "DUPLICATE_NOTIFICATION": 409,
    "LOSS_BEFORE_INCEPTION": 422,
    "POLICY_CANCELLED": 422,
    "LOSS_AFTER_EXPIRY": 422,
    "AMOUNT_EXCEEDS_LIMIT": 422,
    "TYPE_NOT_COVERED": 422,
}

DEPENDENCY_STATUS: dict[str, int] = {
    "POLICY_MASTER_UNREACHABLE": 503,
    "POLICY_MASTER_TIMEOUT": 504,
    "POLICY_MASTER_UNPARSABLE": 502,
}

INVALID_REQUEST_MESSAGE = "The request body is not well formed."

FIXTURE_FILES = ("fnol_valid.json", "fnol_invalid.json", "fnol_edge.json")
DATA_DIR = ROOT / "data"


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
    """Contract §5: 400 detail names the field, not a rule identifier."""
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


def invalid_request_envelope(errors: Sequence[Any]) -> dict[str, Any]:
    return {
        "code": "INVALID_REQUEST",
        "message": INVALID_REQUEST_MESSAGE,
        "detail": _detail_from_validation_errors(errors),
        "status": INVALID_REQUEST_STATUS,
    }


def load_fixture_payloads(path: Path) -> dict[str, dict[str, Any]]:
    """Fixtures are wrapped `{id, payload}` records, not bare POST bodies."""
    records = json.loads(path.read_text())
    payloads: dict[str, dict[str, Any]] = {}
    for record in records:
        payloads[record["id"]] = record["payload"]
    return payloads


def classify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        NotificationRequest.model_validate(payload)
    except ValidationError as exc:
        return {"outcome": "rejected", **invalid_request_envelope(exc.errors())}
    return {"outcome": "well_formed"}


def main() -> None:
    print("RULE_STATUS")
    for code, status in RULE_STATUS.items():
        print(f"  {code:24} {status}")
    print("DEPENDENCY_STATUS")
    for code, status in DEPENDENCY_STATUS.items():
        print(f"  {code:24} {status}")
    print(f"INVALID_REQUEST           {INVALID_REQUEST_STATUS}")
    print()
    print(f"{'id':12} {'outcome':12} {'status':7} {'code':18} field / reason")
    print("-" * 78)

    for filename in FIXTURE_FILES:
        payloads = load_fixture_payloads(DATA_DIR / filename)
        for case_id, payload in payloads.items():
            result = classify_payload(payload)
            if result["outcome"] == "well_formed":
                print(f"{case_id:12} well_formed            (rule layer, not 400)")
                continue
            detail = result["detail"]
            print(
                f"{case_id:12} rejected     {result['status']:<7} "
                f"{result['code']:18} {detail['field']} / {detail['reason']}"
            )
            assert "rule" not in detail, "400 envelope must not name a rule"


if __name__ == "__main__":
    main()
