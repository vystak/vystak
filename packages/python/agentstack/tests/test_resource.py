import pytest

from agentstack.schema.provider import Provider
from agentstack.schema.resource import (
    Cache,
    Database,
    ObjectStore,
    Queue,
    Resource,
    SessionStore,
    VectorStore,
)


@pytest.fixture()
def aws():
    return Provider(name="aws", type="aws")


class TestResource:
    def test_create(self, aws):
        resource = Resource(name="db", provider=aws, engine="postgres")
        assert resource.name == "db"
        assert resource.engine == "postgres"
        assert resource.config == {}

    def test_with_config(self, aws):
        resource = Resource(
            name="db",
            provider=aws,
            engine="postgres",
            config={"host": "localhost", "port": 5432},
        )
        assert resource.config["port"] == 5432

    def test_serialization_roundtrip(self, aws):
        resource = Resource(name="db", provider=aws, engine="postgres", config={"host": "localhost"})
        data = resource.model_dump()
        restored = Resource.model_validate(data)
        assert restored == resource


class TestResourceSubtypes:
    def test_session_store(self, aws):
        store = SessionStore(name="sessions", provider=aws, engine="redis")
        assert isinstance(store, Resource)
        assert store.engine == "redis"

    def test_vector_store(self, aws):
        store = VectorStore(name="kb", provider=aws, engine="pinecone")
        assert isinstance(store, Resource)

    def test_database(self, aws):
        db = Database(name="main", provider=aws, engine="postgres")
        assert isinstance(db, Resource)

    def test_cache(self, aws):
        cache = Cache(name="cache", provider=aws, engine="redis")
        assert isinstance(cache, Resource)

    def test_object_store(self, aws):
        store = ObjectStore(name="files", provider=aws, engine="s3")
        assert isinstance(store, Resource)

    def test_queue(self, aws):
        queue = Queue(name="tasks", provider=aws, engine="sqs")
        assert isinstance(queue, Resource)
