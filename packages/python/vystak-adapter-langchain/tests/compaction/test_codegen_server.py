from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_adapter_langchain.templates import generate_server_py

# Note: ServiceType is a Union/TypeAlias; instantiate the concrete Postgres
# subclass instead. Inspect packages/python/vystak/src/vystak/schema/service.py
# to find the right concrete class. The point of these tests is that the
# generator handles a postgres-engine session store and a no-store agent.


def _agent_persistent_compaction():
    from vystak.schema.service import Postgres  # adjust if class name differs
    return Agent(
        name="x",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        sessions=Postgres(provider=Provider(name="docker", type="docker"), engine="postgres"),
        compaction=Compaction(mode="conservative"),
    )


def _agent_memory_compaction():
    return Agent(
        name="x",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        compaction=Compaction(mode="conservative"),
    )


def test_persistent_uses_postgres_compaction_store():
    code = generate_server_py(_agent_persistent_compaction())
    assert "PostgresCompactionStore" in code
    assert "_compaction_store" in code


def test_persistent_runs_setup_in_lifespan():
    code = generate_server_py(_agent_persistent_compaction())
    assert "_compaction_store.setup()" in code


def test_memory_uses_inmemory_compaction_store():
    code = generate_server_py(_agent_memory_compaction())
    assert "InMemoryCompactionStore" in code
    assert "_compaction_store = InMemoryCompactionStore()" in code


def test_no_compaction_no_compaction_store():
    a = _agent_persistent_compaction().model_copy(update={"compaction": None})
    code = generate_server_py(a)
    assert "_compaction_store" not in code
