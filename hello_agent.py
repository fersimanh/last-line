"""Hello agent: proves that Entra ID auth to the Foundry project works.

Before running, sign in once with:  az login
Then run:                            python3 hello_agent.py
"""
import asyncio
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

# .env wins over any old values set in the terminal
load_dotenv(override=True)


async def main():
    # The client talks to the Foundry project. AzureCliCredential reuses
    # the sign-in from `az login`, so no API key is needed.
    client = FoundryChatClient(
        project_endpoint=os.environ["PROJECT_ENDPOINT"],
        model=os.environ["MODEL_DEPLOYMENT_NAME"],
        credential=AzureCliCredential(),
    )

    agent = Agent(client, instructions="You are a friendly football pundit.", name="Hello")
    response = await agent.run("Say hello in one short sentence.")
    print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
