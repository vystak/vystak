# Ops checklist

On every heartbeat:

1. Check whether any deploys are pending review in the queue.
2. Check whether any error-rate alerts have fired in the last 30 minutes.
3. Check whether any on-call schedule changes are needed for the next 24h.

Reply only when at least one item needs human attention. Otherwise reply
with `HEARTBEAT_OK`.
