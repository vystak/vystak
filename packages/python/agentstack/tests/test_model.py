import pytest
from pydantic import ValidationError

from agentstack.schema.model import Embedding, Model
from agentstack.schema.provider import Provider


@pytest.fixture()
def anthropic():
    return Provider(name="anthropic", type="anthropic")


class TestModel:
    def test_create(self, anthropic):
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        assert model.name == "claude"
        assert model.provider.name == "anthropic"
        assert model.model_name == "claude-sonnet-4-20250514"
        assert model.parameters == {}

    def test_with_parameters(self, anthropic):
        model = Model(
            name="claude",
            provider=anthropic,
            model_name="claude-sonnet-4-20250514",
            parameters={"temperature": 0.7, "max_tokens": 4096},
        )
        assert model.parameters["temperature"] == 0.7

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            Model(name="claude", model_name="claude-sonnet-4-20250514")

    def test_model_name_required(self, anthropic):
        with pytest.raises(ValidationError):
            Model(name="claude", provider=anthropic)

    def test_serialization_roundtrip(self, anthropic):
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        data = model.model_dump()
        restored = Model.model_validate(data)
        assert restored == model


class TestEmbedding:
    def test_create(self, anthropic):
        emb = Embedding(name="embed", provider=anthropic, model_name="text-embedding-3-small")
        assert emb.dimensions is None

    def test_with_dimensions(self, anthropic):
        emb = Embedding(
            name="embed",
            provider=anthropic,
            model_name="text-embedding-3-small",
            dimensions=1536,
        )
        assert emb.dimensions == 1536

    def test_serialization_roundtrip(self, anthropic):
        emb = Embedding(name="embed", provider=anthropic, model_name="text-embedding-3-small", dimensions=768)
        data = emb.model_dump()
        restored = Embedding.model_validate(data)
        assert restored == emb
