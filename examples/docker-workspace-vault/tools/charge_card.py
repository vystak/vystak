"""Illustrative Stripe charge tool — runs in the workspace container
with scoped access to STRIPE_API_KEY.

The agent container cannot see STRIPE_API_KEY; only the workspace
container's env has it via the Vault Agent sidecar + entrypoint shim.
"""

import httpx

from vystak.secrets import get


def charge_card(card_id: str, amount: int) -> dict:
    """Charge a card via Stripe. Uses vystak.secrets.get to fetch the
    API key from the container's env (populated by Vault Agent)."""
    api_key = get("STRIPE_API_KEY")
    response = httpx.post(
        "https://api.stripe.example/v1/charges",  # illustrative, not live
        data={"source": card_id, "amount": amount},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    response.raise_for_status()
    return {"charge_id": response.json()["id"], "status": response.status_code}
