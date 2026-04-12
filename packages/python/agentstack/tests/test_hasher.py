from pydantic import BaseModel

from agentstack.hash.hasher import hash_dict, hash_model


class SimpleModel(BaseModel):
    name: str
    value: int


class TestHashModel:
    def test_deterministic(self):
        model = SimpleModel(name="test", value=42)
        assert hash_model(model) == hash_model(model)

    def test_different_values_different_hash(self):
        model1 = SimpleModel(name="test", value=42)
        model2 = SimpleModel(name="test", value=43)
        assert hash_model(model1) != hash_model(model2)

    def test_field_order_irrelevant(self):
        model1 = SimpleModel(name="test", value=42)
        model2 = SimpleModel(value=42, name="test")
        assert hash_model(model1) == hash_model(model2)

    def test_returns_hex_string(self):
        model = SimpleModel(name="test", value=42)
        h = hash_model(model)
        assert isinstance(h, str)
        assert len(h) == 64


class TestHashDict:
    def test_deterministic(self):
        data = {"a": 1, "b": 2}
        assert hash_dict(data) == hash_dict(data)

    def test_key_order_irrelevant(self):
        data1 = {"a": 1, "b": 2}
        data2 = {"b": 2, "a": 1}
        assert hash_dict(data1) == hash_dict(data2)

    def test_different_values_different_hash(self):
        assert hash_dict({"a": 1}) != hash_dict({"a": 2})

    def test_empty_dict(self):
        h = hash_dict({})
        assert len(h) == 64
