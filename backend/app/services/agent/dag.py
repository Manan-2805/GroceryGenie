import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("app.services.agent.dag")


class DAGCycleError(ValueError):
    pass


class DAGExecutionError(RuntimeError):
    pass


# Worker display names for progress reporting
WORKER_DISPLAY_NAMES = {
    "ProductQueryWorker": "🔍 Searching products",
    "DietaryFactWorker": "🥗 Analyzing dietary info",
    "OrderStatusWorker": "📦 Checking orders",
    "CartActionWorker": "🛒 Updating cart",
    "ExplainerWorker": "💬 Preparing explanation",
    "StoreLayoutWorker": "📍 Finding store locations",
    "SellerDashboardWorker": "📊 Loading dashboard",
    "AddressWorker": "📍 Managing addresses",
    "CheckoutWorker": "🛍️ Processing checkout",
    "ProfileWorker": "👤 Updating profile",
    "SellerProductWorker": "📦 Managing products",
}


async def execute_subgoal_dag(
    subgoals: list[dict[str, Any]],
    worker_runner: Callable[[dict[str, Any], dict[str, Any]], Any],
    _context: dict[str, Any],
    progress_callback: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """
    Executes a list of subgoals represented as a DAG.
    Each subgoal is a dict:
      {
        "id": "A",
        "type": "ProductQueryWorker",
        "goal": "find oat milk...",
        "depends_on": []
      }
    worker_runner is an async callable: worker_runner(subgoal, results)
    context contains session details, user_id, facts, etc.
    progress_callback is an optional async callable to report progress.
    """
    logger.info(f"Decomposing DAG with {len(subgoals)} subgoals...")

    if progress_callback:
        await progress_callback(f"🧠 Planning {len(subgoals)} steps...")

    # Map subgoals by ID
    {sg["id"]: sg for sg in subgoals}
    completed_ids: set[str] = set()
    results: dict[str, Any] = {}

    while len(completed_ids) < len(subgoals):
        # Find all nodes that are not completed and whose dependencies are fully resolved
        runnable_batch = []
        for sg in subgoals:
            sg_id = sg["id"]
            if sg_id in completed_ids:
                continue

            deps = sg.get("depends_on", [])
            if all(dep in completed_ids for dep in deps):
                runnable_batch.append(sg)

        if not runnable_batch:
            # We have uncompleted nodes but none are runnable -> Cycle detected
            remaining_ids = [
                sg["id"] for sg in subgoals if sg["id"] not in completed_ids
            ]
            raise DAGCycleError(
                f"Dependency cycle detected in DAG. Remaining unresolvable nodes: {remaining_ids}"
            )

        logger.info(
            f"Executing batch of runnable subgoals in parallel: {[sg['id'] for sg in runnable_batch]}"
        )

        # Report progress for each worker starting
        for sg in runnable_batch:
            worker_type = sg["type"]
            display = WORKER_DISPLAY_NAMES.get(worker_type, f"⚙️ Running {worker_type}")
            if progress_callback:
                await progress_callback(display)

        # Run this batch in parallel using asyncio.gather
        tasks = []
        for sg in runnable_batch:
            tasks.append(worker_runner(sg, results))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and update status
        for sg, res in zip(runnable_batch, batch_results, strict=False):
            sg_id = sg["id"]
            if isinstance(res, Exception):
                logger.error(f"Subgoal {sg_id} failed during execution: {res}")
                results[sg_id] = {"status": "failed", "error": str(res)}
            else:
                results[sg_id] = {"status": "success", "output": res}

            completed_ids.add(sg_id)

    if progress_callback:
        await progress_callback("✅ Done!")

    return results
