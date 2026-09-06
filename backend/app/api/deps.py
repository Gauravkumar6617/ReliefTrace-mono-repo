"""Shared API dependencies / singletons."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory rate-limit store. Fine for a single process; move to Redis
# (slowapi supports a redis storage URI) once this runs behind several.
limiter = Limiter(key_func=get_remote_address)
