import pytest

from agentstack_gateway.router import Route, Router


@pytest.fixture()
def router():
    return Router()


@pytest.fixture()
def support_route():
    return Route(
        provider_name="internal-slack",
        agent_name="support-bot",
        agent_url="http://agentstack-support-bot:8000",
        channels=["#support", "#help"],
        listen="mentions",
        threads=True,
        dm=True,
    )


@pytest.fixture()
def sales_route():
    return Route(
        provider_name="internal-slack",
        agent_name="sales-bot",
        agent_url="http://agentstack-sales-bot:8000",
        channels=["#sales"],
        listen="messages",
        threads=True,
        dm=False,
    )


@pytest.fixture()
def customer_route():
    return Route(
        provider_name="customer-slack",
        agent_name="customer-bot",
        agent_url="http://agentstack-customer-bot:8000",
        channels=["#customer-help"],
        listen="messages",
        threads=True,
        dm=True,
    )


class TestAddRoute:
    def test_add_and_list(self, router, support_route):
        router.add_route(support_route)
        routes = router.list_routes()
        assert len(routes) == 1
        assert routes[0].agent_name == "support-bot"


class TestResolve:
    def test_resolve_by_channel(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", "#support", is_dm=False)
        assert route is not None
        assert route.agent_name == "support-bot"

    def test_resolve_second_channel(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", "#help", is_dm=False)
        assert route is not None
        assert route.agent_name == "support-bot"

    def test_resolve_no_match(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", "#random", is_dm=False)
        assert route is None

    def test_resolve_dm(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", None, is_dm=True)
        assert route is not None
        assert route.agent_name == "support-bot"

    def test_resolve_dm_disabled(self, router, sales_route):
        router.add_route(sales_route)
        route = router.resolve("internal-slack", None, is_dm=True)
        assert route is None

    def test_multiple_providers(self, router, support_route, customer_route):
        router.add_route(support_route)
        router.add_route(customer_route)
        r1 = router.resolve("internal-slack", "#support", is_dm=False)
        assert r1.agent_name == "support-bot"
        r2 = router.resolve("customer-slack", "#customer-help", is_dm=False)
        assert r2.agent_name == "customer-bot"

    def test_same_provider_different_channels(self, router, support_route, sales_route):
        router.add_route(support_route)
        router.add_route(sales_route)
        r1 = router.resolve("internal-slack", "#support", is_dm=False)
        assert r1.agent_name == "support-bot"
        r2 = router.resolve("internal-slack", "#sales", is_dm=False)
        assert r2.agent_name == "sales-bot"


class TestRemoveRoutes:
    def test_remove(self, router, support_route, sales_route):
        router.add_route(support_route)
        router.add_route(sales_route)
        router.remove_routes("support-bot")
        routes = router.list_routes()
        assert len(routes) == 1
        assert routes[0].agent_name == "sales-bot"

    def test_remove_nonexistent(self, router):
        router.remove_routes("nobody")
