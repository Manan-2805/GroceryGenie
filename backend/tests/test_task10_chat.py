from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.chat import ChatMessagePayload
from app.assistant.runner import Turn, fast_plan
from app.assistant.schema import Plan, Search
from app.db.models.enums import UserRole


def test_client_cannot_choose_confirmation_tool_or_payload():
    with pytest.raises(ValidationError):
        ChatMessagePayload.model_validate(
            {
                "message": "yes",
                "session_id": str(uuid4()),
                "approved_action": "stock",
                "approved_payload": {"quantity": 100},
            }
        )


def test_confirmation_has_opaque_id_and_requires_conversation():
    approval = uuid4()
    with pytest.raises(ValidationError):
        ChatMessagePayload(confirmation_id=approval, approved=True)
    with pytest.raises(ValidationError):
        ChatMessagePayload(session_id=uuid4(), confirmation_id=approval)
    assert Turn(text="Confirm the change?", confirmation_id=approval).event() == {
        "type": "permission_request",
        "summary": "Confirm the change?",
        "confirmation_id": str(approval),
    }


def test_fast_plan_preserves_stock_and_price_filters():
    plan = fast_plan("Find cheap butter under ₹400", UserRole.customer)
    assert plan and len(plan.steps) == 1
    step = plan.steps[0]
    assert isinstance(step, Search)
    assert step.filters.query == "butter"
    assert step.filters.stock_quantity == 1
    assert step.filters.max_price == Decimal("399.99")


def test_generated_plan_is_bounded_and_has_no_unregistered_operation():
    with pytest.raises(ValidationError):
        Plan.model_validate({"steps": [{"tool": "query", "sql": "SELECT 1"}]})
    with pytest.raises(ValidationError):
        Plan.model_validate({"steps": [{"tool": "orders"}] * 6})
