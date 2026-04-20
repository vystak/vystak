"""charge_card — example tool that reads STRIPE_API_KEY from the sidecar env.

This tool runs inside the **workspace sidecar container**, not inside the
LLM-facing container. The LLM can call ``charge_card`` with arguments but
cannot read STRIPE_API_KEY itself — the key only materializes in this
container's env via ACA ``secretRef`` backed by the workspace UAMI.

The endpoint used below is an illustrative placeholder. Replace
``https://api.stripe.example/v1/charges`` with the real Stripe API URL
(``https://api.stripe.com/v1/charges``) before using this in production.
"""

from __future__ import annotations

import httpx
import vystak.secrets


def charge_card(amount_cents: int, currency: str, source: str, description: str = "") -> str:
    """Create a Stripe charge. Returns a short human-readable status.

    Args:
        amount_cents: Amount in the smallest currency unit (e.g. cents).
        currency: 3-letter ISO currency code, lowercase (``"usd"``, ``"eur"``).
        source: Tokenized card source from Stripe.js (``"tok_..."``).
        description: Optional free-text description attached to the charge.

    The LLM never sees the API key — it lives only in this container's env,
    injected via ACA secretRef from the workspace UAMI. A prompt-injection
    attack that manipulates the model cannot exfiltrate the key because the
    key is not in the model's process.
    """
    # Read the Stripe key from the container env via vystak.secrets.get;
    # raises SecretNotAvailableError with actionable guidance if the secret
    # was not declared on the Workspace.
    stripe_key = vystak.secrets.get("STRIPE_API_KEY")

    try:
        # Illustrative placeholder endpoint — swap for api.stripe.com in real use.
        response = httpx.post(
            "https://api.stripe.example/v1/charges",
            auth=(stripe_key, ""),
            data={
                "amount": amount_cents,
                "currency": currency,
                "source": source,
                "description": description,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return f"charge ok: {response.json().get('id', '?')}"
    except httpx.HTTPError as e:
        return f"charge failed: {e}"
