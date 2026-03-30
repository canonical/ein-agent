"""Workflow-bound tool factories for agent tools.

These tools need access to workflow state (signals, activities, event waiting).
They accept callback functions rather than the workflow instance itself,
keeping the agents package decoupled from the specific workflow class.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta

from agents import function_tool
from temporalio import workflow

from ein_agent_worker.models.hitl import WorkflowEventType


def create_ask_user_tool(
    set_pending_question: Callable[[str | None], None],
    wait_for_message: Callable[[], Awaitable],
):
    """Create the ask_user tool that pauses for user input.

    Args:
        set_pending_question: Callback to set/clear the pending question in
            workflow state. Called with the question string before waiting,
            and None after receiving response.
        wait_for_message: Async callback that waits for a user message event
            and returns a WorkflowEvent.
    """

    @function_tool
    async def ask_user(question: str) -> str:
        """Ask the user for clarification or additional information.

        Args:
            question: The question to ask the user.
        """
        workflow.logger.info(f'ask_user called: {question}')

        # Set pending question in state for UI
        set_pending_question(question)

        # Wait for user response
        event = await wait_for_message()

        # Clear pending question
        set_pending_question(None)

        if event.type == WorkflowEventType.STOP:
            return 'User ended the conversation.'

        response = event.payload or ''
        workflow.logger.info(f'User responded to ask_user: {response[:100]}...')
        return response

    return ask_user


def create_fetch_alerts_tool(
    get_alertmanager_url: Callable[[], str | None],
    store_alerts: Callable[[list[dict]], None],
):
    """Create the fetch_alerts tool.

    Args:
        get_alertmanager_url: Callback returning the alertmanager URL from config.
        store_alerts: Callback to store fetched alerts in workflow state.
    """

    @function_tool
    async def fetch_alerts(
        status: str = 'firing',
        alertname: str | None = None,
    ) -> str:
        """Fetch alerts from Alertmanager.

        Args:
            status: Alert status filter. Defaults to 'firing'.
            alertname: Optional alert name filter.
        """
        workflow.logger.info(f'fetch_alerts called: status={status}, alertname={alertname}')

        params = {
            'alertmanager_url': get_alertmanager_url(),
            'status': status,
            'alertname': alertname,
        }

        try:
            alerts = await workflow.execute_activity(
                'fetch_alerts_activity',
                params,
                start_to_close_timeout=timedelta(seconds=60),
            )
            store_alerts(alerts)
        except Exception as e:
            workflow.logger.error(f'Failed to fetch alerts: {e}')
            return f'Error: Failed to fetch alerts from Alertmanager: {e}'

        if not alerts:
            return f'No {status} alerts found' + (f" for '{alertname}'." if alertname else '.')

        lines = [f'Found {len(alerts)} {status} alerts:']
        for alert in alerts:
            labels = alert.get('labels', {})
            name = labels.get('alertname', 'N/A')
            fingerprint = alert.get('fingerprint', 'N/A')
            summary = alert.get('annotations', {}).get('summary', 'No summary.')
            lines.append(f'- **{name}** (Fingerprint: `{fingerprint}`): {summary}')
            for key, value in labels.items():
                if key not in ['alertname', 'severity']:
                    lines.append(f'  - {key}: {value}')

        return '\n'.join(lines)

    return fetch_alerts
