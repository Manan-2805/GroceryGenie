import json
import logging
from typing import Any, cast

from app.services.memory import get_redis_client

logger = logging.getLogger("app.services.cache")

PRODUCT_CACHE_TTL = 1800  # 30 minutes
PRODUCT_LIST_CACHE_TTL = 600  # 10 minutes


async def get_cached_product(product_id: str) -> dict[str, Any] | None:
    try:
        client = get_redis_client()
        key = f"product:detail:{product_id}"
        cached = await client.get(key)
        if cached:
            logger.debug(f"Cache hit for product detail: {product_id}")
            return cast(dict[str, Any], json.loads(cached))
    except Exception as e:
        logger.error(f"Error reading product detail cache: {e}")
    return None


async def set_cached_product(product_id: str, product_data: dict[str, Any]) -> None:
    try:
        client = get_redis_client()
        key = f"product:detail:{product_id}"
        await client.set(key, json.dumps(product_data), ex=PRODUCT_CACHE_TTL)
        logger.debug(f"Cached product detail: {product_id}")
    except Exception as e:
        logger.error(f"Error writing product detail cache: {e}")


async def invalidate_product_cache(product_id: str) -> None:
    try:
        client = get_redis_client()
        key = f"product:detail:{product_id}"
        await client.delete(key)
        logger.info(f"Invalidated cache for product detail: {product_id}")

        # Targeted invalidation of list keys containing this product_id
        pattern = "product:list:*"
        cursor = 0
        keys_to_delete = []
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            for k in keys:
                cached_data = await client.get(k)
                # Decode bytes to string if needed
                cached_str = (
                    cached_data.decode("utf-8")
                    if isinstance(cached_data, bytes)
                    else (cached_data or "")
                )
                if product_id in cached_str:
                    keys_to_delete.append(k)
            if cursor == 0:
                break

        if keys_to_delete:
            await client.delete(*keys_to_delete)
            logger.info(f"Invalidated targeted list caches: {keys_to_delete}")
    except Exception as e:
        logger.error(f"Error in targeted product cache invalidation: {e}")


async def get_cached_products_list(
    category: str | None, featured: bool | None
) -> list[dict[str, Any]] | None:
    try:
        client = get_redis_client()
        key = f"product:list:cat_{category or 'all'}:feat_{str(featured).lower() if featured is not None else 'all'}"
        cached = await client.get(key)
        if cached:
            logger.debug(f"Cache hit for products list: {key}")
            return cast(list[dict[str, Any]], json.loads(cached))
    except Exception as e:
        logger.error(f"Error reading products list cache: {e}")
    return None


async def set_cached_products_list(
    category: str | None,
    featured: bool | None,
    products_list: list[dict[str, Any]],
) -> None:
    try:
        client = get_redis_client()
        key = f"product:list:cat_{category or 'all'}:feat_{str(featured).lower() if featured is not None else 'all'}"
        await client.set(key, json.dumps(products_list), ex=PRODUCT_LIST_CACHE_TTL)
        logger.debug(f"Cached products list: {key}")
    except Exception as e:
        logger.error(f"Error writing products list cache: {e}")


async def invalidate_all_products_lists() -> None:
    try:
        client = get_redis_client()
        pattern = "product:list:*"
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
                logger.info(f"Deleted product list keys: {keys}")
            if cursor == 0:
                break
        logger.info("All product list caches invalidated.")
    except Exception as e:
        logger.error(f"Error invalidating product lists cache: {e}")
