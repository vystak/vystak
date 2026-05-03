"""Postgres-backed store tests — gated on `docker` marker."""
import pytest

pytestmark = pytest.mark.docker

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
async def pg_store(tmp_path):
    """Spin up a temporary postgres container, yield a store bound to it."""
    import asyncio
    import subprocess
    import uuid

    name = f"vystak-pg-test-{uuid.uuid4().hex[:8]}"
    pw = "testpass"
    port = 55432
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            f"POSTGRES_PASSWORD={pw}",
            "-p",
            f"{port}:5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
    )
    try:
        # wait for ready
        for _ in range(30):
            try:
                conn = await psycopg.AsyncConnection.connect(
                    f"postgresql://postgres:{pw}@localhost:{port}/postgres",
                    autocommit=True,
                )
                await conn.close()
                break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError("postgres did not become ready")

        from vystak_adapter_langchain.compaction.store import PostgresCompactionStore

        conn = await psycopg.AsyncConnection.connect(
            f"postgresql://postgres:{pw}@localhost:{port}/postgres",
            autocommit=True,
        )
        store = PostgresCompactionStore(conn)
        await store.setup()
        try:
            yield store
        finally:
            await conn.close()
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


@pytest.mark.asyncio
async def test_postgres_write_and_latest(pg_store):
    gen = await pg_store.write(
        thread_id="t1",
        summary_text="hello",
        up_to_message_id="m5",
        trigger="threshold",
        summarizer_model="claude",
        usage={"input_tokens": 200, "output_tokens": 40},
    )
    assert gen == 1
    row = await pg_store.latest("t1")
    assert row.summary_text == "hello"
    assert row.input_tokens == 200


@pytest.mark.asyncio
async def test_postgres_generation_increment(pg_store):
    a1 = await pg_store.write(
        thread_id="A",
        summary_text="x",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    a2 = await pg_store.write(
        thread_id="A",
        summary_text="x",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    b1 = await pg_store.write(
        thread_id="B",
        summary_text="x",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    assert (a1, a2, b1) == (1, 2, 1)


@pytest.mark.asyncio
async def test_postgres_list_descending(pg_store):
    for i in range(3):
        await pg_store.write(
            thread_id="A",
            summary_text=f"s{i}",
            up_to_message_id="m",
            trigger="threshold",
            summarizer_model="m",
            usage={},
        )
    rows = await pg_store.list("A")
    assert [r.generation for r in rows] == [3, 2, 1]
