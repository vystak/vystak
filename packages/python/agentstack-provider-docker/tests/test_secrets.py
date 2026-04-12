from agentstack_provider_docker.secrets import (
    generate_password,
    get_resource_password,
    load_secrets,
    save_secrets,
)


class TestGeneratePassword:
    def test_returns_string(self):
        pw = generate_password()
        assert isinstance(pw, str)

    def test_length(self):
        pw = generate_password()
        assert len(pw) >= 24

    def test_unique(self):
        pw1 = generate_password()
        pw2 = generate_password()
        assert pw1 != pw2


class TestSecretsFile:
    def test_save_and_load(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        data = {"resources": {"sessions": {"password": "test123"}}}
        save_secrets(secrets_path, data)
        loaded = load_secrets(secrets_path)
        assert loaded == data

    def test_load_missing_returns_empty(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        loaded = load_secrets(secrets_path)
        assert loaded == {"resources": {}}


class TestGetResourcePassword:
    def test_creates_new(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        pw = get_resource_password("sessions", secrets_path)
        assert isinstance(pw, str)
        assert len(pw) >= 24

    def test_reuses_existing(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        pw1 = get_resource_password("sessions", secrets_path)
        pw2 = get_resource_password("sessions", secrets_path)
        assert pw1 == pw2

    def test_different_resources_different_passwords(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        pw1 = get_resource_password("sessions", secrets_path)
        pw2 = get_resource_password("other", secrets_path)
        assert pw1 != pw2
