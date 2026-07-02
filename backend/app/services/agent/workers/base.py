from typing import Any


class BaseWorker:
    def __init__(self, context: dict[str, Any], subgoal_results: dict[str, Any]):
        """
        context: dict containing global state like db session, user_id, user_facts, etc.
        subgoal_results: dict containing results from prior DAG subgoals.
        """
        self.context = context
        self.subgoal_results = subgoal_results

    async def run(self, goal: str) -> Any:
        raise NotImplementedError("Subclasses must implement run()")
