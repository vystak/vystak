import pytest
from pydantic import ValidationError

from vystak.schema.gateway import ChannelProvider, Gateway
from vystak.schema.provider import Provider


@pytest.fixture()
def docker():
    return Provider(name="docker", type="docker")


@pytest.fixture()
def gateway(docker):
    return Gateway(name="main-gateway", provider=docker, config={"port": 8080})


class TestGateway:
    def test_create(self, docker):
        gw = Gateway(name="main", provider=docker)
        assert gw.name == "main"
        assert gw.config == {}

    def test_with_config(self, docker):
        gw = Gateway(name="main", provider=docker, config={"port": 8080})
        assert gw.config["port"] == 8080

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            Gateway(name="main")

    def test_serialization_roundtrip(self, docker):
        gw = Gateway(name="main", provider=docker, config={"port": 8080})
        data = gw.model_dump()
        restored = Gateway.model_validate(data)
        assert restored == gw


class TestChannelProvider:
    def test_create(self, gateway):
        cp = ChannelProvider(name="internal-slack", type="slack", gateway=gateway, config={"bot_token": "xoxb-test"})
        assert cp.name == "internal-slack"
        assert cp.type == "slack"
        assert cp.gateway.name == "main-gateway"

    def test_gateway_required(self):
        with pytest.raises(ValidationError):
            ChannelProvider(name="test", type="slack")

    def test_type_required(self, gateway):
        with pytest.raises(ValidationError):
            ChannelProvider(name="test", gateway=gateway)

    def test_serialization_roundtrip(self, gateway):
        cp = ChannelProvider(name="slack", type="slack", gateway=gateway, config={"bot_token": "xoxb-test"})
        data = cp.model_dump()
        restored = ChannelProvider.model_validate(data)
        assert restored == cp
