import pytest
from pydantic import ValidationError
from vystak.schema.secret import Secret


class TestSecret:
    def test_simple_form(self):
        secret = Secret(name="ANTHROPIC_API_KEY")
        assert secret.name == "ANTHROPIC_API_KEY"
        assert secret.provider is None
        assert secret.path is None
        assert secret.key is None

    def test_full_form(self):
        from vystak.schema.provider import Provider

        vault = Provider(name="vault", type="vault", config={"addr": "https://vault.example.com"})
        secret = Secret(name="api-key", provider=vault, path="secrets/anthropic", key="api_key")
        assert secret.provider.name == "vault"
        assert secret.path == "secrets/anthropic"
        assert secret.key == "api_key"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Secret()

    def test_serialization_roundtrip(self):
        secret = Secret(name="MY_SECRET", path="some/path")
        data = secret.model_dump()
        restored = Secret.model_validate(data)
        assert restored == secret
