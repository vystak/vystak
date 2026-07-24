from langchain_core.tools import tool

_ORDERS = {"1001": "shipped", "1002": "processing", "1003": "delivered"}


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order's status by its id."""
    status = _ORDERS.get(order_id)
    if status is None:
        return f"Order {order_id} not found."
    return f"Order {order_id}: {status}"
