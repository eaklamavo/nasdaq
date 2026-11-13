"""Shared helpers for data providers."""
from __future__ import annotations

import functools
import math
from typing import Any, Callable

import pandas as pd


def clean(obj: Any) -> Any:
    """Make pandas/numpy/date values JSON-serialisable (NaN -> None)."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return clean(obj.reset_index().to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return clean(obj.to_dict())
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 6)
    if hasattr(obj, "item"):
        return clean(obj.item())
    return obj


def safe(fn: Callable) -> Callable:
    """Turn provider failures into {'error': ...} so the agent can reason about missing data."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            return clean(fn(*args, **kwargs))
        except Exception as e:  # noqa: BLE001
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {str(e)[:300]}", "source_unavailable": True}

    return wrapper


def missing_key(name: str) -> dict:
    return {"error": f"{name} is not configured; source unavailable", "source_unavailable": True}
