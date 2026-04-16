import pytest
from vystak.provisioning.grouping import group_agents_by_platform, platform_fingerprint
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider


@pytest.fixture()
def model():
    return Model(name="claude", provider=Provider(name="anthropic", type="anthropic"), model_name="claude-sonnet-4-20250514")


class TestPlatformFingerprint:
    def test_same_platform_object(self, model):
        docker = Provider(name="docker", type="docker")
        platform = Platform(name="local", type="docker", provider=docker)
        a = Agent(name="a", model=model, platform=platform)
        b = Agent(name="b", model=model, platform=platform)
        assert platform_fingerprint(a) == platform_fingerprint(b)

    def test_same_config_same_fingerprint(self, model):
        p1 = Platform(name="aca", type="container-apps", provider=Provider(name="azure", type="azure", config={"location": "eastus2"}))
        p2 = Platform(name="aca", type="container-apps", provider=Provider(name="azure", type="azure", config={"location": "eastus2"}))
        assert platform_fingerprint(Agent(name="a", model=model, platform=p1)) == platform_fingerprint(Agent(name="b", model=model, platform=p2))

    def test_different_config(self, model):
        p1 = Platform(name="aca", type="container-apps", provider=Provider(name="azure", type="azure", config={"location": "eastus2"}))
        p2 = Platform(name="aca", type="container-apps", provider=Provider(name="azure", type="azure", config={"location": "westus2"}))
        assert platform_fingerprint(Agent(name="a", model=model, platform=p1)) != platform_fingerprint(Agent(name="b", model=model, platform=p2))

    def test_no_platform_default(self, model):
        assert platform_fingerprint(Agent(name="a", model=model)) == "docker:default"

    def test_different_provider_type(self, model):
        p1 = Platform(name="a", type="docker", provider=Provider(name="docker", type="docker"))
        p2 = Platform(name="b", type="container-apps", provider=Provider(name="azure", type="azure"))
        assert platform_fingerprint(Agent(name="a", model=model, platform=p1)) != platform_fingerprint(Agent(name="b", model=model, platform=p2))


class TestGroupAgentsByPlatform:
    def test_single_group(self, model):
        platform = Platform(name="local", type="docker", provider=Provider(name="docker", type="docker"))
        agents = [Agent(name="a", model=model, platform=platform), Agent(name="b", model=model, platform=platform)]
        groups = group_agents_by_platform(agents)
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2

    def test_two_groups(self, model):
        docker = Platform(name="local", type="docker", provider=Provider(name="docker", type="docker"))
        azure = Platform(name="aca", type="container-apps", provider=Provider(name="azure", type="azure"))
        agents = [Agent(name="a", model=model, platform=docker), Agent(name="b", model=model, platform=azure)]
        groups = group_agents_by_platform(agents)
        assert len(groups) == 2

    def test_empty(self):
        assert group_agents_by_platform([]) == {}
