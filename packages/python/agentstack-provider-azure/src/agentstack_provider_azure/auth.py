"""Azure authentication — DefaultAzureCredential with CLI fallback."""

import json
import os
import subprocess

from azure.identity import DefaultAzureCredential


def get_credential() -> DefaultAzureCredential:
    """Get Azure credentials. Tries CLI auth first, falls back to service principal env vars."""
    return DefaultAzureCredential()


def get_subscription_id(config: dict) -> str:
    """Get Azure subscription ID from config, env, or CLI context."""
    if config.get("subscription_id"):
        return config["subscription_id"]

    env_sub = os.environ.get("AZURE_SUBSCRIPTION_ID")
    if env_sub:
        return env_sub

    try:
        result = subprocess.run(
            ["az", "account", "show", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data["id"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, subprocess.TimeoutExpired):
        pass

    raise ValueError(
        "Azure subscription ID not found. Set AZURE_SUBSCRIPTION_ID, "
        "add subscription_id to provider config, or run 'az login'."
    )


def get_location(config: dict) -> str:
    """Get Azure location from config or default."""
    return config.get("location", "eastus2")
