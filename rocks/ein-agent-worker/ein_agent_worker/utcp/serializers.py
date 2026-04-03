"""Shared serialization helpers for UTCP results and schemas."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Temporal's default payload size limit is 2MB. The invoke_model_activity
# carries the full conversation history (including all prior tool results)
# as its input payload. Large API responses (e.g., Kubernetes PodList for
# all namespaces) accumulate in the conversation and can push subsequent
# activity payloads over the limit, causing a fatal
# BadScheduleActivityAttributes error.
#
# We truncate individual tool results to a conservative limit so that
# even with many tool calls in the conversation, the total stays well
# under 2MB.
RESULT_MAX_CHARS = 100_000


def serialize_result(result: Any, max_chars: int = RESULT_MAX_CHARS) -> str:
    """Serialize a result to JSON string, truncating if too large.

    For list/dict results that exceed max_chars, attempts smart truncation:
    - Kubernetes-style list responses (with 'items'): truncates the items
      array and appends a count summary.
    - Other large results: hard-truncates with a warning message.

    Args:
        result: The raw API result to serialize.
        max_chars: Maximum allowed characters in the output.

    Returns:
        JSON string, guaranteed to be at most ~max_chars.
    """
    serialized = json.dumps(result, indent=2) if isinstance(result, dict | list) else str(result)

    if len(serialized) <= max_chars:
        return serialized

    total_items = None

    # Smart truncation for Kubernetes-style list responses
    if isinstance(result, dict) and 'items' in result and isinstance(result['items'], list):
        total_items = len(result['items'])
        # Binary search for the max number of items that fits
        truncated = result.copy()
        lo, hi = 0, total_items
        while lo < hi:
            mid = (lo + hi + 1) // 2
            truncated['items'] = result['items'][:mid]
            if len(json.dumps(truncated, indent=2)) <= max_chars - 200:  # leave room for message
                lo = mid
            else:
                hi = mid - 1
        truncated['items'] = result['items'][:lo]
        truncated['_truncated'] = {
            'shown': lo,
            'total': total_items,
            'message': (
                f'Response truncated: showing {lo} of {total_items} items. '
                'Use more specific filters (namespace, label selector) to narrow results.'
            ),
        }
        serialized = json.dumps(truncated, indent=2)
    else:
        # Hard truncation for other large results
        serialized = (
            serialized[: max_chars - 200] + '\n\n... [TRUNCATED — response too large. '
            'Use more specific filters to narrow results.] ...'
        )

    logger.warning(
        'Truncated tool result from %d to %d chars (items: %s)',
        len(json.dumps(result, indent=2)) if isinstance(result, dict | list) else len(str(result)),
        len(serialized),
        f'{total_items} total' if total_items else 'N/A',
    )
    return serialized


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
