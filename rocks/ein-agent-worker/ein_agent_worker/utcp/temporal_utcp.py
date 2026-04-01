"""Temporal UTCP integration - run UTCP operations as Temporal activities.

This module provides UTCP tool execution within Temporal workflows by running
each UTCP operation as a separate activity. This allows network I/O to happen
outside the workflow sandbox.

Pattern follows the MCP integration in temporalio.contrib.openai_agents._mcp.
"""

import dataclasses
import json
import logging
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

from agents import function_tool
from temporalio import activity, workflow
from temporalio.workflow import ActivityConfig

from ein_agent_worker.utcp import registry as utcp_registry
from ein_agent_worker.utcp.approval import create_approval_checker
from ein_agent_worker.utcp.config import UTCPServiceConfig
from ein_agent_worker.utcp.serializers import serialize_result, serialize_schema

logger = logging.getLogger(__name__)


# =============================================================================
# Activity Arguments
# =============================================================================


@dataclasses.dataclass
class _ListOperationsArguments:
    service_name: str
    tag: str = ''


@dataclasses.dataclass
class _SearchOperationsArguments:
    service_name: str
    query: str
    limit: int = 20


@dataclasses.dataclass
class _GetOperationDetailsArguments:
    service_name: str
    tool_name: str


@dataclasses.dataclass
class _CallOperationArguments:
    service_name: str
    tool_name: str
    arguments: str  # JSON string


# =============================================================================
# Activity Definitions
# =============================================================================


def get_utcp_activities() -> Sequence[Callable]:
    """Get UTCP activity functions to register with the worker.

    Returns:
        Sequence of activity functions
    """

    @activity.defn(name='utcp-list-operations')
    async def list_operations(args: _ListOperationsArguments) -> str:
        """List all available API operations with optional tag filtering."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({'error': f"UTCP service '{args.service_name}' not found"})

        try:
            # Fetch all tools using a broad search
            all_tools = await client.search_tools(' ', limit=2000)

            # Filter by tag if provided
            if args.tag:
                tag_lower = args.tag.lower()
                filtered_tools = [
                    t
                    for t in all_tools
                    if hasattr(t, 'tags') and any(tag_lower in str(tag).lower() for tag in t.tags)
                ]
            else:
                filtered_tools = all_tools

            result = [
                {
                    'name': tool.name,
                    'tags': tool.tags if hasattr(tool, 'tags') else [],
                    'description': tool.description,
                }
                for tool in filtered_tools
            ]

            response = {
                'total': len(result),
                'operations': result,
            }

            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error('Error listing %s operations: %s', args.service_name, e)
            return json.dumps({'error': str(e)})

    @activity.defn(name='utcp-search-operations')
    async def search_operations(args: _SearchOperationsArguments) -> str:
        """Search for API operations matching the query."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({'error': f"UTCP service '{args.service_name}' not found"})

        try:
            # Fetch all tools for client-side scoring
            all_tools = await client.search_tools(' ', limit=2000)

            query_lower = args.query.lower()
            query_words = query_lower.split()

            scored_tools = []
            for tool in all_tools:
                name_lower = tool.name.lower()
                desc_lower = tool.description.lower() if tool.description else ''

                score = 0

                # Exact name match
                if query_lower == name_lower.replace(f'{args.service_name}.', ''):
                    score += 100

                # Partial name match
                if query_lower in name_lower:
                    score += 50

                # Word matches in name
                matches_in_name = sum(1 for w in query_words if w in name_lower)
                score += matches_in_name * 10

                # Word matches in description
                matches_in_desc = sum(1 for w in query_words if w in desc_lower)
                score += matches_in_desc * 5

                if score > 0:
                    scored_tools.append((score, tool))

            # Sort by score descending
            scored_tools.sort(key=lambda x: x[0], reverse=True)

            # Take top 'limit'
            top_tools = [t[1] for t in scored_tools[: args.limit]]

            result = [
                {
                    'name': tool.name,
                    'tags': tool.tags if hasattr(tool, 'tags') else [],
                    'description': tool.description,
                }
                for tool in top_tools
            ]

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(
                'Error searching %s operations: %s',
                args.service_name,
                e,
            )
            return json.dumps({'error': str(e)})

    @activity.defn(name='utcp-get-operation-details')
    async def get_operation_details(args: _GetOperationDetailsArguments) -> str:
        """Get detailed parameter schema for a specific operation."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({'error': f"UTCP service '{args.service_name}' not found"})

        try:
            tools = await client.search_tools(args.tool_name, limit=10)

            for tool in tools:
                if tool.name == args.tool_name:
                    schema = serialize_schema(tool.inputs) if hasattr(tool, 'inputs') else {}

                    response = {
                        'name': tool.name,
                        'description': tool.description,
                        'parameters': schema,
                    }

                    return json.dumps(response, indent=2)

            return json.dumps({'error': f"Tool '{args.tool_name}' not found."})
        except Exception as e:
            logger.error(
                'Error getting %s operation details: %s',
                args.service_name,
                e,
            )
            return json.dumps({'error': str(e)})

    @activity.defn(name='utcp-call-operation')
    async def call_operation(args: _CallOperationArguments) -> str:
        """Execute an API operation."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({'error': f"UTCP service '{args.service_name}' not found"})

        try:
            # Validate tool name belongs to this service
            # UTCP normalizes hyphens to underscores in manual/tool names
            normalized_name = args.service_name.replace('-', '_')
            expected_prefix = f'{normalized_name}.'
            if not args.tool_name.startswith(expected_prefix):
                tool_service = args.tool_name.split('.')[0]
                error_msg = (
                    f"Tool name mismatch: '{args.tool_name}' does not "
                    f"start with '{expected_prefix}'. "
                    f"You called 'call_{args.service_name}_operation' "
                    f'but provided a tool from a different service. '
                    f'Please use the correct tool function: '
                    f'call_{tool_service}_operation'
                )
                logger.error('[%s] %s', args.service_name, error_msg)
                return json.dumps({'error': error_msg})

            logger.debug(
                '[%s] Calling tool: %s',
                args.service_name,
                args.tool_name,
            )
            arguments = json.loads(args.arguments) if args.arguments else {}
            result = await client.call_tool(args.tool_name, arguments)
            return serialize_result(result)
        except json.JSONDecodeError as e:
            return json.dumps({'error': f'Invalid JSON arguments: {e}'})
        except Exception as e:
            import traceback

            error_msg = str(e) or type(e).__name__
            logger.error(
                '[%s] Error calling operation %s: %s',
                args.service_name,
                args.tool_name,
                error_msg,
            )
            logger.error('Traceback: %s', traceback.format_exc())
            return json.dumps({'error': error_msg})

    return (list_operations, search_operations, get_operation_details, call_operation)


# =============================================================================
# Workflow Tool Wrappers
# =============================================================================


def create_utcp_workflow_tools(
    service_name: str,
    service_config: UTCPServiceConfig | None = None,
    config: ActivityConfig | None = None,
    sticky_approvals: dict[str, bool] | None = None,
) -> list[Callable]:
    """Create UTCP tools for use in Temporal workflows (single instance).

    These tools execute UTCP operations as activities, allowing network I/O
    to happen outside the workflow sandbox.

    Args:
        service_name: UTCP service instance name (e.g., 'kubernetes')
        service_config: Optional UTCP service configuration (for approval policy)
        config: Optional activity configuration
        sticky_approvals: Optional shared sticky approvals dict

    Returns:
        List of function tools for the agent
    """
    svc_type = service_config.resolved_type if service_config else service_name
    return create_grouped_utcp_workflow_tools(
        service_type=svc_type,
        instances={service_name: service_config},
        config=config,
        sticky_approvals=sticky_approvals,
    )


def create_grouped_utcp_workflow_tools(
    service_type: str,
    instances: dict[str, UTCPServiceConfig | None],
    config: ActivityConfig | None = None,
    sticky_approvals: dict[str, bool] | None = None,
) -> list[Callable]:
    """Create UTCP tools for a group of instances of the same service type.

    Shared read tools (search/list/get_details) are created once per service
    type using the first instance's client. Per-instance call tools are created
    for each instance to route to the correct endpoint.

    Args:
        service_type: Service type (e.g., 'kubernetes')
        instances: Dict of instance_name -> UTCPServiceConfig for all instances
            of this type
        config: Optional activity configuration
        sticky_approvals: Optional shared sticky approvals dict

    Returns:
        List of function tools for the agent
    """
    activity_config = config or ActivityConfig(start_to_close_timeout=timedelta(seconds=60))

    # Use the first instance for shared read tools (operations are identical)
    first_instance = next(iter(instances))

    # --- Shared read tools (named after service type) ---

    @function_tool(name_override=f'list_{service_type}_operations')
    async def list_operations(tag: str = '') -> str:
        """List all available API operations with optional tag filtering.

        Use this to discover what operations are available without searching.
        Returns ALL operations (no pagination).

        Args:
            tag: Optional tag filter (e.g., "v1", "core", "apps").
                Leave empty to list all.

        Returns:
            JSON list of available operations with their names, tags,
            and descriptions.
        """
        return await workflow.execute_activity(
            'utcp-list-operations',
            _ListOperationsArguments(first_instance, tag),
            result_type=str,
            **activity_config,
        )

    @function_tool(name_override=f'search_{service_type}_operations')
    async def search_operations(query: str, limit: int = 20) -> str:
        """Search for API operations matching the query.

        Args:
            query: Natural language description of what you want to do
                   (e.g., "list pods", "get dashboard", "cluster status")
            limit: Maximum number of operations to return (default: 20)

        Returns:
            JSON list of available operations with their names and descriptions.
        """
        return await workflow.execute_activity(
            'utcp-search-operations',
            _SearchOperationsArguments(first_instance, query, limit),
            result_type=str,
            **activity_config,
        )

    @function_tool(name_override=f'get_{service_type}_operation_details')
    async def get_operation_details(tool_name: str) -> str:
        """Get detailed parameter schema for a specific operation.

        Use this after finding an operation with search to know
        what parameters it requires.

        Args:
            tool_name: The exact name of the tool
                (e.g., "kubernetes.listCoreV1NamespacedPod")

        Returns:
            JSON schema of the tool's parameters.
        """
        return await workflow.execute_activity(
            'utcp-get-operation-details',
            _GetOperationDetailsArguments(first_instance, tool_name),
            result_type=str,
            **activity_config,
        )

    tools: list[Callable] = [list_operations, search_operations, get_operation_details]

    # --- Per-instance call tools ---

    for instance_name, service_config in instances.items():
        call_prefix = instance_name.replace('-', '_')

        # Create approval checker per instance
        approval_checker = None
        if service_config:
            approval_checker = create_approval_checker(
                service_config, sticky_approvals=sticky_approvals
            )
            logger.info(
                '[%s] Approval policy: %s',
                instance_name,
                service_config.approval_policy,
            )

        # Each instance gets its own call tool bound to its endpoint
        call_tool = _create_call_tool(
            instance_name=instance_name,
            call_prefix=call_prefix,
            activity_config=activity_config,
            approval_checker=approval_checker,
        )
        tools.append(call_tool)

    return tools


def _create_call_tool(
    instance_name: str,
    call_prefix: str,
    activity_config: ActivityConfig,
    approval_checker: Any | None = None,
) -> Callable:
    """Create a per-instance call_operation tool.

    Separated into its own function so each closure captures
    the correct instance_name and call_prefix.

    Args:
        instance_name: UTCP instance name (e.g., 'kubernetes-prod')
        call_prefix: Sanitized name for tool naming (e.g., 'kubernetes_prod')
        activity_config: Temporal activity configuration
        approval_checker: Optional approval checker for this instance

    Returns:
        A function tool for calling operations on this instance
    """

    @function_tool(
        name_override=f'call_{call_prefix}_operation',
        needs_approval=approval_checker if approval_checker else False,
    )
    async def call_operation(tool_name: str, arguments: str = '{}') -> str:
        """Execute an API operation.

        IMPORTANT: This tool is ONLY for operations of this service instance.
        Tool names must start with the service prefix.
        If you need to call operations from other services,
        use their respective call_*_operation tools.

        Args:
            tool_name: The exact tool name from search results
            arguments: JSON string of arguments matching the tool's
                parameter schema

        Returns:
            The result of the API call as JSON
        """
        return await workflow.execute_activity(
            'utcp-call-operation',
            _CallOperationArguments(instance_name, tool_name, arguments),
            result_type=str,
            **activity_config,
        )

    return call_operation
