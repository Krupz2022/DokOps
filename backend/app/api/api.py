from fastapi import APIRouter
from app.api.v1 import auth, user

api_router = APIRouter()
api_router.include_router(auth.router, tags=["login"])
api_router.include_router(user.router, prefix="/users", tags=["users"])
from app.api.v1 import system
api_router.include_router(system.router, prefix="/system", tags=["system"])
from app.api.v1 import dashboard
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
from app.api.v1 import audit
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
from app.api.v1 import kubernetes
api_router.include_router(kubernetes.router, prefix="/k8s", tags=["kubernetes"])
from app.api.v1 import ai
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
from app.api.v1 import clusters
api_router.include_router(clusters.router, prefix="/clusters", tags=["clusters"])
from app.api.v1 import tools
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
from app.api.v1 import operations
api_router.include_router(operations.router, prefix="/operations", tags=["operations"])
from app.api.v1 import chat
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
from app.api.v1 import rag
api_router.include_router(rag.router, prefix="/rag", tags=["rag"])
from app.api.v1 import integrations
api_router.include_router(integrations.router, prefix="/integrations/azure", tags=["integrations"])
from app.api.v1 import mcp as mcp_router
api_router.include_router(mcp_router.router, prefix="/mcp", tags=["mcp"])
from app.api.v1 import cli_tools
api_router.include_router(cli_tools.router, prefix="/system/cli-tools", tags=["cli-tools"])
from app.api.v1 import topology as topology_router
api_router.include_router(topology_router.router, prefix="/topology", tags=["topology"])
from app.api.v1 import sso as sso_router
api_router.include_router(sso_router.router, prefix="/auth/sso", tags=["sso"])
from app.api.v1 import workflows as workflows_router
api_router.include_router(workflows_router.router, prefix="/workflows", tags=["workflows"])
from app.api.v1 import integrations_obs as integrations_obs_router
api_router.include_router(integrations_obs_router.router, prefix="/integrations/obs", tags=["integrations-obs"])
from app.api.v1 import activation as activation_router
api_router.include_router(activation_router.router, prefix="/activation", tags=["activation"])
from app.api.v1 import minions as minions_router
api_router.include_router(minions_router.router, prefix="/minions", tags=["minions"])
from app.api.v1 import organisations as organisations_router
api_router.include_router(organisations_router.router, prefix="/organisations", tags=["organisations"])
from app.api.v1 import patching as patching_router
api_router.include_router(patching_router.router, prefix="/patches", tags=["patching"])
from app.api.v1 import service_credentials as service_credentials_router
api_router.include_router(service_credentials_router.router, prefix="/service-credentials", tags=["service-credentials"])
from app.api.v1 import alerts as alerts_router
api_router.include_router(alerts_router.router, prefix="/alerts", tags=["alerts"])
from app.api.v1 import vault as vault_router
api_router.include_router(vault_router.router, prefix="/vault", tags=["vault"])
from app.api.v1 import registries as registries_router
api_router.include_router(registries_router.router, prefix="/registries", tags=["registries"])
from app.api.v1 import analytics as analytics_router
api_router.include_router(analytics_router.router, prefix="/analytics", tags=["Analytics"])
from app.api.v1 import knowledge_sources as knowledge_sources_router
api_router.include_router(knowledge_sources_router.router, prefix="/knowledge-sources", tags=["knowledge-sources"])
from app.api.v1 import blueprints as blueprints_router
api_router.include_router(blueprints_router.router, prefix="/blueprints", tags=["blueprints"])
from app.api.v1 import keys as keys_router
api_router.include_router(keys_router.router, prefix="/keys", tags=["keys"])
