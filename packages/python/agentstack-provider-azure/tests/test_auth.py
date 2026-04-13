from unittest.mock import MagicMock, patch

import pytest


class TestGetCredential:
    def test_returns_default_credential(self):
        from agentstack_provider_azure.auth import get_credential
        with patch("agentstack_provider_azure.auth.DefaultAzureCredential") as mock_cred:
            mock_cred.return_value = MagicMock()
            cred = get_credential()
            assert cred is not None
            mock_cred.assert_called_once()


class TestGetSubscriptionId:
    def test_from_config(self):
        from agentstack_provider_azure.auth import get_subscription_id
        sub_id = get_subscription_id(config={"subscription_id": "test-sub-123"})
        assert sub_id == "test-sub-123"

    def test_from_env(self):
        from agentstack_provider_azure.auth import get_subscription_id
        with patch.dict("os.environ", {"AZURE_SUBSCRIPTION_ID": "env-sub-456"}):
            sub_id = get_subscription_id(config={})
            assert sub_id == "env-sub-456"

    def test_from_cli(self):
        from agentstack_provider_azure.auth import get_subscription_id
        with patch("agentstack_provider_azure.auth.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"id": "cli-sub-789"}',
            )
            with patch.dict("os.environ", {}, clear=True):
                sub_id = get_subscription_id(config={})
                assert sub_id == "cli-sub-789"

    def test_raises_when_not_found(self):
        from agentstack_provider_azure.auth import get_subscription_id
        with patch("agentstack_provider_azure.auth.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(ValueError, match="subscription"):
                    get_subscription_id(config={})


class TestGetLocation:
    def test_from_config(self):
        from agentstack_provider_azure.auth import get_location
        assert get_location({"location": "westus2"}) == "westus2"

    def test_default(self):
        from agentstack_provider_azure.auth import get_location
        assert get_location({}) == "eastus2"
