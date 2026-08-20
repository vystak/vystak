async def read_status(service: str) -> str:
    """Read the current health status of a named service."""
    return f"service {service} is DOWN (health check failing since 09:14 UTC)"
