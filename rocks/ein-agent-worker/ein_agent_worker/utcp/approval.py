"""Approval logic for UTCP tool calls."""

import logging
import re
from typing import Any

from ein_agent_worker.models import ApprovalPolicy
from ein_agent_worker.utcp.config import READ_HTTP_METHODS, WRITE_HTTP_METHODS

logger = logging.getLogger(__name__)


def extract_http_method_from_operation(tool_name: str) -> str | None:
    """Extract HTTP method from operation name.

    Examples:
        - kubernetes.listCoreV1NamespacedPod -> "LIST"
        - kubernetes.createCoreV1NamespacedPod -> "CREATE"
        - kubernetes.patchCoreV1NamespacedPod -> "PATCH"
        - grafana.getApiDashboardsUid -> "GET"

    Args:
        tool_name: The UTCP tool name (e.g., "kubernetes.listCoreV1NamespacedPod")

    Returns:
        HTTP method in uppercase, or None if not detected
    """
    # Remove service prefix (e.g., "kubernetes.")
    operation = tool_name.split('.', 1)[-1]

    # Check for common HTTP method prefixes in camelCase
    for method in WRITE_HTTP_METHODS | READ_HTTP_METHODS:
        method_lower = method.lower()
        # Check if operation starts with the method name (case-insensitive)
        if operation.lower().startswith(method_lower):
            return method.upper()

    # Fallback: check for method in the middle (e.g., "replaceCoreV1Namespace")
    for method in WRITE_HTTP_METHODS:
        if re.search(rf'\b{method.lower()}\b', operation.lower()):
            return method.upper()

    logger.debug('Could not extract HTTP method from operation: %s', tool_name)
    return None


def check_needs_approval(
    approval_policy: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> bool:
    """Check if a UTCP tool call requires approval based on policy.

    Args:
        approval_policy: The approval policy string (never, always, read_only)
        tool_name: The UTCP tool name (e.g., "kubernetes.listCoreV1NamespacedPod")
        arguments: Optional tool arguments

    Returns:
        True if approval is required, False otherwise
    """
    # Parse policy
    try:
        policy = ApprovalPolicy(approval_policy)
    except ValueError:
        logger.warning(
            "Invalid approval policy '%s', defaulting to read_only",
            approval_policy,
        )
        policy = ApprovalPolicy.READ_ONLY

    # Never require approval
    if policy == ApprovalPolicy.NEVER:
        return False

    # Always require approval
    if policy == ApprovalPolicy.ALWAYS:
        return True

    # Extract HTTP method from operation name
    http_method = extract_http_method_from_operation(tool_name)

    if not http_method:
        # Can't determine method, err on the side of caution
        logger.warning(
            'Could not determine HTTP method for %s, requiring approval',
            tool_name,
        )
        return True

    # Read only policy: auto-approve reads, require approval for writes
    if policy == ApprovalPolicy.READ_ONLY:
        return http_method in WRITE_HTTP_METHODS

    # Default: require approval
    return True


def create_approval_checker(service_config, sticky_approvals: dict[str, bool] | None = None):
    """Create an approval checker function for a specific UTCP service.

    This returns a callable that can be passed to function_tool(needs_approval=...).

    Args:
        service_config: UTCPServiceConfig instance
        sticky_approvals: Optional sticky approvals dict (tool_name -> approved)

    Returns:
        Callable that checks if a tool call needs approval
    """

    def needs_approval_fn(_ctx, params: dict[str, Any], _call_id: str) -> bool:
        """Check if this tool call needs approval."""
        tool_name = params.get('tool_name', '')
        arguments = params.get('arguments')

        # Parse arguments if it's a JSON string
        if isinstance(arguments, str):
            import json

            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                arguments = {}

        # Check sticky approvals first (if provided)
        if sticky_approvals is not None and tool_name in sticky_approvals:
            cached_decision = sticky_approvals[tool_name]
            logger.debug(
                'Sticky approval for %s: %s',
                tool_name,
                'approved' if cached_decision else 'rejected',
            )
            # If sticky approved, don't need approval again
            # If sticky rejected, still need to interrupt (to show rejection)
            return not cached_decision

        # No sticky decision, check policy
        return check_needs_approval(service_config.approval_policy, tool_name, arguments)

    return needs_approval_fn
