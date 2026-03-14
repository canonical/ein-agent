"""Script to run a workflow against the Temporal worker for testing."""

import asyncio

from temporallib.client import Client, Options


async def main():
    """Connect to Temporal and execute the investigation workflow."""
    client_opt = Options(
        host='localhost:7233',
        queue='ein-agent-queue',
        namespace='default',
    )

    client = await Client.connect(client_opt=client_opt)
    workflow_name = 'SingleAlertInvestigationWorkflow'
    workflow_id = 'single-alert-investigation-id'

    enabled_services = ['kubernetes', 'grafana']

    await client.execute_workflow(
        workflow_name,
        # prompt,
        'please tell me a joke',
        id=workflow_id,
        task_queue='ein-agent-queue',
        memo={'utcp_services': enabled_services},
    )


if __name__ == '__main__':
    asyncio.run(main())
