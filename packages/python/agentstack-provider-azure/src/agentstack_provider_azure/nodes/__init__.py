"""Azure provider node types for the provisioning graph."""

from agentstack_provider_azure.nodes.resource_group import ResourceGroupNode
from agentstack_provider_azure.nodes.log_analytics import LogAnalyticsNode
from agentstack_provider_azure.nodes.acr import ACRNode
from agentstack_provider_azure.nodes.aca_environment import ACAEnvironmentNode
from agentstack_provider_azure.nodes.aca_app import ContainerAppNode
from agentstack_provider_azure.nodes.postgres import AzurePostgresNode

__all__ = [
    "ResourceGroupNode",
    "LogAnalyticsNode",
    "ACRNode",
    "ACAEnvironmentNode",
    "ContainerAppNode",
    "AzurePostgresNode",
]
