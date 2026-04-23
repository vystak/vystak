from vystak.hash.tree import compute_grants_hash, hash_agent, hash_workspace
from vystak.schema.agent import Agent
from vystak.schema.common import WorkspaceType
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak.schema.workspace import Workspace


def _agent_with_workspace_secret(secret_name: str = "STRIPE_API_KEY") -> Agent:
    anthropic = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="a",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=Workspace(
            name="w",
            type=WorkspaceType.PERSISTENT,
            secrets=[Secret(name=secret_name)],
        ),
    )


def test_agent_hash_tree_includes_workspace_identity_and_grants():
    tree = hash_agent(_agent_with_workspace_secret())
    assert tree.workspace_identity  # non-empty hash string
    assert tree.grants
    assert tree.root


def test_changing_workspace_secret_changes_grants_hash():
    t1 = hash_agent(_agent_with_workspace_secret("STRIPE_API_KEY"))
    t2 = hash_agent(_agent_with_workspace_secret("TWILIO_API_KEY"))
    assert t1.grants != t2.grants
    assert t1.root != t2.root


def test_compute_grants_hash_stable_across_ordering():
    a = _agent_with_workspace_secret()
    h1 = compute_grants_hash(a)
    h2 = compute_grants_hash(a)
    assert h1 == h2


def test_hash_workspace_round_trip():
    ws = Workspace(
        name="w",
        type=WorkspaceType.PERSISTENT,
        identity="/subscriptions/x/uami",
        secrets=[Secret(name="STRIPE_API_KEY")],
    )
    tree = hash_workspace(ws)
    assert tree.identity
    assert tree.secrets
    assert tree.root
