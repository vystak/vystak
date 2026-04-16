import pytest
from vystak.provisioning.graph import CycleError, ProvisionError, ProvisionGraph
from vystak.provisioning.health import NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class StubNode(Provisionable):
    def __init__(self, node_name: str, deps: list[str] | None = None, fail: bool = False):
        self._name = node_name
        self._deps = deps or []
        self._fail = fail
        self.provisioned = False
        self.context_received = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._deps

    def provision(self, context: dict) -> ProvisionResult:
        self.context_received = dict(context)
        self.provisioned = True
        if self._fail:
            return ProvisionResult(name=self._name, success=False, error="forced failure")
        return ProvisionResult(name=self._name, success=True, info={"provisioned": True})

    def health_check(self):
        return NoopHealthCheck()

    def destroy(self):
        self.provisioned = False


class TestProvisionGraph:
    def test_single_node(self):
        graph = ProvisionGraph()
        node = StubNode("db")
        graph.add(node)
        results = graph.execute()
        assert node.provisioned
        assert results["db"].success

    def test_dependency_order(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db", deps=["network"])
        app = StubNode("app", deps=["db"])
        graph.add(network)
        graph.add(db)
        graph.add(app)
        graph.execute()
        assert network.provisioned and db.provisioned and app.provisioned
        assert "network" in db.context_received
        assert "network" in app.context_received
        assert "db" in app.context_received

    def test_implicit_dependency(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db")
        graph.add(network)
        graph.add(db)
        graph.add_dependency("db", "network")
        graph.execute()
        assert "network" in db.context_received

    def test_mixed_explicit_and_implicit_deps(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db", deps=["network"])
        cache = StubNode("cache")
        app = StubNode("app", deps=["db"])
        graph.add(network)
        graph.add(db)
        graph.add(cache)
        graph.add(app)
        graph.add_dependency("cache", "network")
        graph.add_dependency("app", "cache")
        graph.execute()
        assert "db" in app.context_received
        assert "cache" in app.context_received

    def test_cycle_detection(self):
        graph = ProvisionGraph()
        a = StubNode("a", deps=["b"])
        b = StubNode("b", deps=["a"])
        graph.add(a)
        graph.add(b)
        with pytest.raises(CycleError):
            graph.execute()

    def test_provision_failure_stops_execution(self):
        graph = ProvisionGraph()
        good = StubNode("good")
        bad = StubNode("bad", deps=["good"], fail=True)
        after = StubNode("after", deps=["bad"])
        graph.add(good)
        graph.add(bad)
        graph.add(after)
        with pytest.raises(ProvisionError, match="bad"):
            graph.execute()
        assert good.provisioned
        assert bad.provisioned
        assert not after.provisioned

    def test_destroy_reverse_order(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db", deps=["network"])
        app = StubNode("app", deps=["db"])
        graph.add(network)
        graph.add(db)
        graph.add(app)
        graph.execute()
        assert network.provisioned and db.provisioned and app.provisioned
        graph.destroy_all()
        assert not network.provisioned
        assert not db.provisioned
        assert not app.provisioned

    def test_unknown_dependency_ignored(self):
        graph = ProvisionGraph()
        node = StubNode("app", deps=["nonexistent"])
        graph.add(node)
        graph.execute()
        assert node.provisioned

    def test_empty_graph(self):
        graph = ProvisionGraph()
        results = graph.execute()
        assert results == {}

    def test_parallel_independent_nodes(self):
        graph = ProvisionGraph()
        a = StubNode("a")
        b = StubNode("b")
        c = StubNode("c")
        graph.add(a)
        graph.add(b)
        graph.add(c)
        graph.execute()
        assert a.provisioned and b.provisioned and c.provisioned
