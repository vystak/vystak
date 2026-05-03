# vystak-channel-runtime

Shared runtime base for Vystak channel containers. Defines `ChannelRuntime`
(template-method message lifecycle), `AgentClient` (A2A default impl),
and `ChannelStore` (SQLite + Postgres + in-memory).

Imported by `vystak-channel-slack`, `vystak-channel-chat`,
`vystak-channel-discord` inside their generated containers.
