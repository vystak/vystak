import pytest

from agentstack.schema.provider import Provider
from agentstack.schema.service import Postgres, Qdrant, Redis, Service, Sqlite


@pytest.fixture()
def docker():
    return Provider(name="docker", type="docker")


@pytest.fixture()
def azure():
    return Provider(name="azure", type="azure", config={"location": "eastus2"})


class TestService:
    def test_minimal(self):
        svc = Service()
        assert svc.name == ""
        assert svc.provider is None
        assert svc.connection_string_env is None
        assert svc.config == {}

    def test_is_managed_with_provider(self, docker):
        svc = Service(provider=docker)
        assert svc.is_managed is True

    def test_is_not_managed_with_connection_string(self):
        svc = Service(connection_string_env="DATABASE_URL")
        assert svc.is_managed is False

    def test_is_not_managed_with_both(self, docker):
        svc = Service(provider=docker, connection_string_env="DATABASE_URL")
        assert svc.is_managed is False

    def test_is_not_managed_with_neither(self):
        svc = Service()
        assert svc.is_managed is False

    def test_with_config(self, azure):
        svc = Service(provider=azure, config={"sku": "Standard_B1ms"})
        assert svc.config["sku"] == "Standard_B1ms"


class TestPostgres:
    def test_engine_default(self, docker):
        pg = Postgres(provider=docker)
        assert pg.engine == "postgres"
        assert isinstance(pg, Service)

    def test_managed(self, docker):
        pg = Postgres(provider=docker)
        assert pg.is_managed is True

    def test_bring_your_own(self):
        pg = Postgres(connection_string_env="DATABASE_URL")
        assert pg.is_managed is False
        assert pg.engine == "postgres"

    def test_with_config(self, azure):
        pg = Postgres(provider=azure, config={"sku": "Standard_B1ms", "storage_gb": 64})
        assert pg.config["storage_gb"] == 64

    def test_serialization_roundtrip(self, docker):
        pg = Postgres(name="sessions", provider=docker, config={"version": "16"})
        data = pg.model_dump()
        restored = Postgres.model_validate(data)
        assert restored == pg


class TestSqlite:
    def test_engine_default(self, docker):
        sl = Sqlite(provider=docker)
        assert sl.engine == "sqlite"
        assert isinstance(sl, Service)

    def test_bring_your_own(self):
        sl = Sqlite(connection_string_env="SQLITE_PATH")
        assert sl.is_managed is False


class TestRedis:
    def test_engine_default(self, docker):
        rd = Redis(name="cache", provider=docker)
        assert rd.engine == "redis"
        assert isinstance(rd, Service)


class TestQdrant:
    def test_engine_default(self, docker):
        qd = Qdrant(name="vectors", provider=docker)
        assert qd.engine == "qdrant"
        assert isinstance(qd, Service)


class TestServiceDependsOn:
    def test_default_empty(self, docker):
        pg = Postgres(provider=docker)
        assert pg.depends_on == []

    def test_explicit_depends_on(self, docker):
        rd = Redis(name="cache", provider=docker, depends_on=["sessions"])
        assert rd.depends_on == ["sessions"]

    def test_serialization_with_depends_on(self, docker):
        rd = Redis(name="cache", provider=docker, depends_on=["sessions", "memory"])
        data = rd.model_dump()
        restored = Redis.model_validate(data)
        assert restored.depends_on == ["sessions", "memory"]
