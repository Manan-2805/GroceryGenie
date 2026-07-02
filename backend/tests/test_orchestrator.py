import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import FactCategory
from app.services.agent.dag import execute_subgoal_dag
from app.services.agent.memory import classify_and_store_fact


@pytest.mark.asyncio
async def test_dag_execution_topological_sort():
    # Setup subgoals representing: A -> B, A -> C, B -> D, C -> D
    subgoals = [
        {
            "id": "A",
            "type": "ProductQueryWorker",
            "goal": "Find oat milk",
            "depends_on": [],
        },
        {
            "id": "B",
            "type": "DietaryFactWorker",
            "goal": "Check allergens",
            "depends_on": ["A"],
        },
        {
            "id": "C",
            "type": "StoreLayoutWorker",
            "goal": "Find layout",
            "depends_on": ["A"],
        },
        {
            "id": "D",
            "type": "ExplainerWorker",
            "goal": "Explain status",
            "depends_on": ["B", "C"],
        },
    ]

    executed_order = []

    async def mock_worker_runner(subgoal, _results):
        executed_order.append(subgoal["id"])
        return f"Result {subgoal['id']}"

    context = {}
    results = await execute_subgoal_dag(subgoals, mock_worker_runner, context)

    # Assertions
    assert "A" in results
    assert "B" in results
    assert "C" in results
    assert "D" in results

    # D must be executed after B and C, which must be executed after A
    assert executed_order.index("A") < executed_order.index("B")
    assert executed_order.index("A") < executed_order.index("C")
    assert executed_order.index("B") < executed_order.index("D")
    assert executed_order.index("C") < executed_order.index("D")


@pytest.mark.asyncio
@patch("app.services.agent.memory.call_llm")
async def test_classify_and_store_fact_positive(mock_call_llm):
    # Mock LLM to return JSON containing fact
    mock_call_llm.return_value = """
    {
      "has_fact": true,
      "fact_text": "Is highly allergic to peanuts",
      "category": "dietary"
    }
    """

    db_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db_session.execute = AsyncMock(return_value=mock_result)
    db_session.commit = AsyncMock()
    db_session.refresh = AsyncMock()

    user_id = uuid.uuid4()
    fact = await classify_and_store_fact(
        db_session, user_id, "I'm highly allergic to peanuts"
    )

    assert fact is not None
    assert fact.fact_text == "Is highly allergic to peanuts"
    assert fact.category == FactCategory.dietary
    db_session.add.assert_called_once()
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.agent.memory.call_llm")
async def test_classify_and_store_fact_negative(mock_call_llm):
    # Mock LLM to return JSON indicating no fact
    mock_call_llm.return_value = """
    {
      "has_fact": false,
      "fact_text": "",
      "category": null
    }
    """

    db_session = MagicMock()
    user_id = uuid.uuid4()
    fact = await classify_and_store_fact(
        db_session, user_id, "What is the price of tomatoes?"
    )

    assert fact is None
    db_session.add.assert_not_called()
