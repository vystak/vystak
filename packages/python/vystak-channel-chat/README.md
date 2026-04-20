# vystak-channel-chat

OpenAI-compatible chat channel plugin for Vystak.

Declares `ChannelType.CHAT`. When deployed, spins up a FastAPI container
exposing `/v1/chat/completions`, `/v1/models`, and `/health`. Chat
completions are routed to the agent named in the `model` field (format:
`vystak/<agent-name>`) and proxied to that agent's A2A endpoint.

## Usage

```python
import vystak as ast
import vystak_channel_chat  # triggers plugin registration

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    routes=[ast.RouteRule(agent="weather-agent")],
)
```

Then `vystak apply`, and:

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"vystak/weather-agent","messages":[{"role":"user","content":"hi"}]}'
```
