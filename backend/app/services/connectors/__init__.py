from typing import Dict
from .base import ConnectorBase
from .http_connector import HttpConnector
from .jenkins_connector import JenkinsConnector
from .argocd_connector import ArgoCDConnector
from .slack_connector import SlackConnector
from .teams_connector import TeamsConnector
from .jira_connector import JiraConnector
from .email_connector import EmailConnector
from .k8s_connector import K8sConnector
from .toolset_connector import ToolsetConnector

CONNECTOR_REGISTRY: Dict[str, ConnectorBase] = {
    "http": HttpConnector(),
    "jenkins": JenkinsConnector(),
    "argocd": ArgoCDConnector(),
    "slack": SlackConnector(),
    "teams": TeamsConnector(),
    "jira": JiraConnector(),
    "email": EmailConnector(),
    "k8s": K8sConnector(),
    "toolset": ToolsetConnector(),
}


def get_connector(connector_type: str) -> ConnectorBase:
    connector = CONNECTOR_REGISTRY.get(connector_type)
    if not connector:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return connector
