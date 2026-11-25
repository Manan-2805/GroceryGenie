"""Run one explicitly enabled, bounded cloud planner smoke request with no customer data."""

import argparse
import asyncio
import logging
import sys

from app.assistant.provider import interpret
from app.core.config import settings
from app.db.models.enums import UserRole


async def smoke() -> None:
    providers = settings.parsed_llm_providers
    if not providers or not providers[0].get("api_key"):
        raise SystemExit("Configure a cloud provider in the test runtime first.")
    primary = providers[0]
    numeric_rates = [
        primary.get("input_usd_per_million"),
        primary.get("output_usd_per_million"),
    ]
    if any(not isinstance(rate, (int, float)) or rate < 0 for rate in numeric_rates):
        raise SystemExit(
            "Set the provider's current input and output rates before consuming credit."
        )
    estimated_ceiling = (10_000 * numeric_rates[0] + 900 * numeric_rates[1]) / 1_000_000
    if estimated_ceiling > 0.05:
        raise SystemExit("The configured estimated upper bound exceeds $0.05.")
    import json

    settings.LLM_PROVIDERS = json.dumps([primary])
    result = await interpret(
        "List all the orders placed by my grocery account.", UserRole.customer, ""
    )
    if result is None or not any(step.tool == "orders" for step in result.steps):
        raise SystemExit("Cloud planner did not return the expected read-only intent.")
    sys.stdout.write("Cloud planner returned the expected read-only orders intent.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Authorize one real cloud request."
    )
    if not parser.parse_args().live:
        raise SystemExit("Live requests require --live.")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(smoke())


if __name__ == "__main__":
    main()
