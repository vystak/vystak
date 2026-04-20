# vystak-channel-slack

Slack channel plugin for Vystak. Runs Slack Bolt in Socket Mode inside a
channel container and forwards events to agents via A2A.

## Usage

```python
import vystak as ast
import vystak_channel_slack  # triggers plugin registration

slack = ast.Channel(
    name="slack-main",
    type=ast.ChannelType.SLACK,
    platform=platform,
    secrets=[
        ast.Secret(name="SLACK_BOT_TOKEN"),
        ast.Secret(name="SLACK_APP_TOKEN"),
    ],
    routes=[
        ast.RouteRule(
            match={"slack_channel": "C0123ABCDE"},
            agent="weather-agent",
        ),
    ],
)
```

Export `SLACK_BOT_TOKEN` (xoxb-...) and `SLACK_APP_TOKEN` (xapp-...) in the
environment where you run `vystak apply`. The values are injected as env
vars into the channel container.

Route matching rules:

- `match.slack_channel` — exact channel ID (Cxxxx)
- `match.dm` = `true` — match direct messages
- Empty match — catch-all fallback

## Runtime mode

`SHARED`. One container per channel declaration holds a single Slack
Socket Mode connection and routes events across all declared agents.
