"""Shared serialization helpers for UTCP results and schemas."""

import json
from typing import Any


def serialize_result(result: Any) -> str:
    """Serialize a result to JSON string."""
    if isinstance(result, dict | list):
        return json.dumps(result, indent=2)
    return str(result)


def serialize_schema(obj: Any) -> dict:
    """Recursively serialize JsonSchema objects to dicts, stripping None values."""
    if hasattr(obj, 'model_dump'):
        data = obj.model_dump()
        return serialize_schema(data)
    elif isinstance(obj, dict):
        return {k: serialize_schema(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [serialize_schema(item) for item in obj]
    return obj
