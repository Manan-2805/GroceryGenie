from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# SlowAPI Rate Limiter using Redis backend
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
)
