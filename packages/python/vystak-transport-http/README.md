# vystak-transport-http

HTTP implementation of the Vystak `Transport` ABC.

- `HttpTransport` — concrete Transport using httpx (client) and FastAPI (server's /a2a is already handled; serve() is a no-op).
- `HttpTransportPlugin` — `TransportPlugin` providing env-var contract and (empty) provisioning.
