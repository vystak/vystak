import pytest
from pydantic import ValidationError

from vystak.schema.platform import Platform
from vystak.schema.provider import Provider


class TestPlatform:
    def test_create(self):
        docker = Provider(name="docker", type="docker")
        platform = Platform(name="local", type="docker", provider=docker)
        assert platform.type == "docker"
        assert platform.provider.name == "docker"
        assert platform.config == {}

    def test_with_config(self):
        aws = Provider(name="aws", type="aws")
        platform = Platform(name="prod", type="agentcore", provider=aws, config={"region": "us-east-1"})
        assert platform.config["region"] == "us-east-1"

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            Platform(name="local", type="docker")

    def test_serialization_roundtrip(self):
        docker = Provider(name="docker", type="docker")
        platform = Platform(name="local", type="docker", provider=docker)
        data = platform.model_dump()
        restored = Platform.model_validate(data)
        assert restored == platform
