# vystak-channel-panel

Control-panel API channel plugin for Vystak. Declares `ChannelType.PANEL` and,
when deployed, spins up a FastAPI container that owns the panel DB (users,
projects, conversations, messages) and exposes a REST + SSE API consumed by
the vystak-panel Next.js app — see
`docs/superpowers/specs/2026-07-24-control-panel-design.md` for the full
design.
