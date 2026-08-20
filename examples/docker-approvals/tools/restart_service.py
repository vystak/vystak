async def restart_service(name: str) -> str:
    """Restart the named service. Destructive: requires approval."""
    return f"service {name} restarted"
