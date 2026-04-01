"""Workflow-bound tool factories for agent tools.

These tools need access to workflow state (signals, activities, event waiting).
They accept callback functions rather than the workflow instance itself,
keeping the agents package decoupled from the specific workflow class.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid4

from agents import function_tool
from temporalio import workflow

from ein_agent_worker.models.hitl import WorkflowEventType, WorkflowInterruption


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


def create_ask_selection_tool(
    add_interruption: Callable[[WorkflowInterruption], None],
    clear_interruptions: Callable[[], None],
    wait_for_selection_response: Callable[[], Awaitable],
):
    """Create the ask_selection tool that presents options to the user.

    Args:
        add_interruption: Callback to add a WorkflowInterruption to state.
        clear_interruptions: Callback to clear interruptions from state.
        wait_for_selection_response: Async callback that waits for a
            SELECTION_RESPONSE event and returns a WorkflowEvent.
    """

    @function_tool
    async def ask_selection(prompt: str, options: list[str]) -> str:
        """Present a list of options to the user and return their selection.

        Use this when you want the user to choose from a specific set of options
        rather than typing a free-form response. The user can also reject all
        options and provide a free-text instruction instead.

        Args:
            prompt: The question or instruction to display above the options.
            options: List of option strings for the user to choose from.
        """
        workflow.logger.info(f'ask_selection called: {prompt} ({len(options)} options)')

        interruption = WorkflowInterruption(
            id=f'selection:{uuid4().hex[:8]}',
            type='user_selection',
            agent_name='Agent',
            question=prompt,
            options=options,
            timestamp=workflow.now(),
        )
        add_interruption(interruption)

        # Wait for user selection
        event = await wait_for_selection_response()

        # Clear interruptions
        clear_interruptions()

        if event.type == WorkflowEventType.STOP:
            return 'User ended the conversation.'

        selected = event.payload
        if selected is None:
            workflow.logger.info('User cancelled the selection')
            return 'User cancelled the selection.'

        # Check if user rejected all options and provided custom instruction
        user_instruction_prefix = '[USER_INSTRUCTION] '
        if isinstance(selected, str) and selected.startswith(user_instruction_prefix):
            instruction = selected[len(user_instruction_prefix) :]
            workflow.logger.info(f'User rejected options, instruction: {instruction}')
            return f'User rejected all proposed options. User instruction: {instruction}'

        workflow.logger.info(f'User selected: {selected}')
        return selected

    return ask_selection


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
