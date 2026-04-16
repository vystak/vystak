import pytest
from pydantic import ValidationError

from vystak.schema.provider import Provider


class TestProvider:
    def test_create(self):
        provider = Provider(name="anthropic", type="anthropic")
        assert provider.name == "anthropic"
        assert provider.type == "anthropic"
        assert provider.config == {}

    def test_with_config(self):
        provider = Provider(
            name="aws",
            type="aws",
            config={"region": "us-east-1", "profile": "default"},
        )
        assert provider.config["region"] == "us-east-1"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Provider(type="aws")

    def test_type_required(self):
        with pytest.raises(ValidationError):
            Provider(name="aws")

    def test_serialization_roundtrip(self):
        provider = Provider(name="docker", type="docker", config={"socket": "/var/run/docker.sock"})
        data = provider.model_dump()
        restored = Provider.model_validate(data)
        assert restored == provider
