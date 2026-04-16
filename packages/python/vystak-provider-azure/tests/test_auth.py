from unittest.mock import MagicMock, patch

import pytest


class TestGetCredential:
    def test_returns_default_credential(self):
        from vystak_provider_azure.auth import get_credential

        with patch("vystak_provider_azure.auth.DefaultAzureCredential") as mock_cred:
            mock_cred.return_value = MagicMock()
            cred = get_credential()
            assert cred is not None
            mock_cred.assert_called_once()


class TestGetSubscriptionId:
    def test_from_config(self):
        from vystak_provider_azure.auth import get_subscription_id

        sub_id = get_subscription_id(config={"subscription_id": "test-sub-123"})
        assert sub_id == "test-sub-123"

    def test_from_env(self):
        from vystak_provider_azure.auth import get_subscription_id

        with patch.dict("os.environ", {"AZURE_SUBSCRIPTION_ID": "env-sub-456"}):
            sub_id = get_subscription_id(config={})
            assert sub_id == "env-sub-456"

    def test_from_cli(self):
        from vystak_provider_azure.auth import get_subscription_id

        with patch("vystak_provider_azure.auth.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"id": "cli-sub-789"}',
            )
            with patch.dict("os.environ", {}, clear=True):
                sub_id = get_subscription_id(config={})
                assert sub_id == "cli-sub-789"

    def test_raises_when_not_found(self):
        from vystak_provider_azure.auth import get_subscription_id

        with (
            patch("vystak_provider_azure.auth.subprocess.run") as mock_run,
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="subscription"),
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            get_subscription_id(config={})


class TestGetLocation:
    def test_from_config(self):
        from vystak_provider_azure.auth import get_location

        assert get_location({"location": "westus2"}) == "westus2"

    def test_default(self):
        from vystak_provider_azure.auth import get_location

        assert get_location({}) == "eastus2"
