# vystak-workspace-rpc

Runs inside the workspace container as an OpenSSH subsystem. Exposes
`fs.*`, `exec.*`, `git.*`, `tool.*` services over JSON-RPC 2.0 on
stdin/stdout.

Not intended to be run directly. Installed into the workspace image by
the vystak Docker provider; launched by sshd per-channel.
