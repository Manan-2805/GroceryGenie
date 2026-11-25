"""Measure concurrent catalog requests against a running local GroceryGenie stack."""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

QUERIES = ("butter", "milk", "rice", "spinach", "juice", "biscuits", "almonds")


def request(base: str, index: int) -> tuple[float, bool]:
    started = time.perf_counter()
    query = urlencode(
        {"search": QUERIES[index % len(QUERIES)], "only_in_stock": "true", "limit": 20}
    )
    try:
        with urlopen(f"{base}/api/v1/products?{query}", timeout=10) as response:
            payload = json.load(response)
            ok = (
                response.status == 200
                and len(payload["items"]) > 0
                and all(
                    product["is_active"] and product["stock"] > 0
                    for product in payload["items"]
                )
            )
    except (OSError, ValueError, KeyError):
        ok = False
    return time.perf_counter() - started, ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--requests", type=int, default=400)
    args = parser.parse_args()
    if urlsplit(args.url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use a loopback GroceryGenie instance.")
    if not 1 <= args.clients <= 150 or args.requests < args.clients:
        parser.error("Set 1–150 clients and at least one request per client.")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.clients) as pool:
        results = list(
            pool.map(
                lambda index: request(args.url.rstrip("/"), index), range(args.requests)
            )
        )
    elapsed = time.perf_counter() - started
    values = sorted(duration * 1000 for duration, _ in results)
    failures = sum(not ok for _, ok in results)
    sys.stdout.write(
        json.dumps(
            {
                "clients": args.clients,
                "requests": args.requests,
                "failures": failures,
                "p50_ms": values[len(values) // 2],
                "p95_ms": values[int(len(values) * 0.95) - 1],
                "requests_per_second": len(results) / elapsed,
            },
            indent=2,
        )
        + "\n"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
