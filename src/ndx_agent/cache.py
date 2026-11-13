"""Small on-disk TTL cache so providers aren't hammered and repeated runs are fast."""
from __future__ import annotations

import functools
import hashlib
import json
import pickle
import time
from typing import Any, Callable

from . import config


def _path(key: str):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".pkl")


def ttl_cache(ttl_seconds: int) -> Callable:
    """Cache a function's result on disk keyed by name + args. Exceptions are not cached."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            key = f"{fn.__module__}.{fn.__name__}:{json.dumps([args, kwargs], default=str, sort_keys=True)}"
            p = _path(key)
            if p.exists() and time.time() - p.stat().st_mtime < ttl_seconds:
                try:
                    return pickle.loads(p.read_bytes())
                except Exception:
                    pass
            result = fn(*args, **kwargs)
            try:
                p.write_bytes(pickle.dumps(result))
            except Exception:
                pass
            return result

        return wrapper

    return deco


_last_call: dict[str, float] = {}


def throttle(name: str, min_interval: float) -> None:
    """Block so that calls sharing `name` are at least `min_interval` seconds apart."""
    wait = _last_call.get(name, 0) + min_interval - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[name] = time.time()
