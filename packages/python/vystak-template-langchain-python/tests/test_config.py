"""load_agent reads vystak.yaml or vystak.py."""

from _vystak.runtime.config import load_agent


def test_load_yaml(tmp_path):
    f = tmp_path / "vystak.yaml"
    f.write_text(
        "name: test\n"
        "framework: langchain-python\n"
        "model:\n"
        "  name: m\n"
        "  provider:\n"
        "    name: anthropic\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )
    a = load_agent(str(f))
    assert a.name == "test"


def test_load_py_module(tmp_path):
    f = tmp_path / "vystak.py"
    f.write_text(
        "from vystak.schema.agent import Agent\n"
        "from vystak.schema.model import Model\n"
        "from vystak.schema.provider import Provider\n"
        "agent = Agent(name='test', model=Model(name='m', "
        "provider=Provider(name='anthropic', type='anthropic'), "
        "model_name='claude-sonnet-4-6'))\n"
    )
    a = load_agent(str(f))
    assert a.name == "test"
