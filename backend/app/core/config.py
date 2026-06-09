from typing import List, Optional, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "MCP Kubernetes Server"
    API_V1_STR: str = "/api/v1"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Security
    AUTH_SECRET_KEY: str = "changethis"  # MUST be overridden via AUTH_SECRET_KEY env var
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8 # 8 days
    ALGORITHM: str = "HS256"

    # Dedicated Fernet key for encrypting secrets in the DB. If not set, falls back to
    # SHA-256 of AUTH_SECRET_KEY (weaker). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: Optional[str] = None

    # Database
    SQLITE_URL: str = "sqlite:///./sql_app.db"
    DATABASE_URL: Optional[str] = None  # if set, overrides SQLITE_URL (use for PostgreSQL in prod)

    # Kubernetes
    K8S_IN_CLUSTER_CONFIG: bool = False
    ALLOW_PRIVATE_CLUSTER_IPS: bool = False
    
    # AI / MCP
    AI_PROVIDER: str = "GEMINI" # GEMINI or OPENAI
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    # AI model tiering — set False to disable fast/full split (e.g. single-model deployments)
    AI_TIERING_ENABLED: bool = True

    # --- DOKOPS_* bootstrap / seeding ---
    # Set these to skip the manual /system/setup step on first deploy.
    # All values seed the DB once on startup (insert-if-missing).
    # Set DOKOPS_FORCE_SEED=true to overwrite existing DB values on restart.

    DOKOPS_FORCE_SEED: bool = False

    # Tier 1 — Bootstrap
    DOKOPS_ADMIN_USERNAME: Optional[str] = None
    DOKOPS_ADMIN_PASSWORD: Optional[str] = None
    DOKOPS_AI_PROVIDER: Optional[str] = None
    DOKOPS_AI_API_KEY: Optional[str] = None
    DOKOPS_AI_MODEL: Optional[str] = None

    # Tier 2 — Common configuration
    DOKOPS_AI_BASE_URL: Optional[str] = None
    DOKOPS_AI_API_VERSION: Optional[str] = None
    DOKOPS_RAG_ENABLED: Optional[bool] = None
    DOKOPS_RAG_CHROMA_HOST: Optional[str] = None
    DOKOPS_RAG_CHROMA_PORT: Optional[str] = None
    DOKOPS_SIGNUP_ENABLED: Optional[bool] = None
    DOKOPS_SIGNUP_DEFAULT_ROLE: Optional[str] = None

    # Tier 3 — Optional tuning
    DOKOPS_RAG_EMBEDDING_PROVIDER: Optional[str] = None
    DOKOPS_RAG_EMBEDDING_API_KEY: Optional[str] = None
    DOKOPS_RAG_EMBEDDING_MODEL: Optional[str] = None
    DOKOPS_RAG_EMBEDDING_BASE_URL: Optional[str] = None

    # Logging
    LOG_LEVEL: str = "WARNING"   # WARNING (default) | INFO | DEBUG

    # ── Observability integrations (seeded on startup) ───────────────
    # Elasticsearch — set these to avoid re-configuring after every pod restart
    DOKOPS_ES_URL: Optional[str] = None           # e.g. https://my-elastic:9200
    DOKOPS_ES_AUTH_TYPE: Optional[str] = None     # api_key | basic | bearer | none
    DOKOPS_ES_API_KEY: Optional[str] = None       # full value: "ApiKey <encoded>"
    DOKOPS_ES_HEADER_NAME: Optional[str] = "Authorization"
    DOKOPS_ES_USERNAME: Optional[str] = None      # for basic auth
    DOKOPS_ES_PASSWORD: Optional[str] = None      # for basic auth

    # ── SSO / OAuth2 ─────────────────────────────────────────────────
    SSO_ENABLED: bool = False
    SSO_AUTO_PROVISION: bool = True
    SSO_ALLOWED_DOMAINS: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    # Microsoft Entra ID
    ENTRA_CLIENT_ID: Optional[str] = None
    ENTRA_CLIENT_SECRET: Optional[str] = None
    ENTRA_TENANT_ID: Optional[str] = None
    ENTRA_ROLES_CLAIM: str = "roles"
    ENTRA_ADMIN_ROLE: str = "Admin"

    # Google Workspace
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_ALLOWED_DOMAIN: Optional[str] = None
    GOOGLE_ADMIN_GROUP: str = "dokops-admins"
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None

    # Authentik
    AUTHENTIK_CLIENT_ID: Optional[str] = None
    AUTHENTIK_CLIENT_SECRET: Optional[str] = None
    AUTHENTIK_BASE_URL: Optional[str] = None
    AUTHENTIK_ROLES_CLAIM: str = "roles"
    AUTHENTIK_ADMIN_ROLE: str = "Admin"

    # AWS Cognito
    COGNITO_CLIENT_ID: Optional[str] = None
    COGNITO_CLIENT_SECRET: Optional[str] = None
    COGNITO_USER_POOL_ID: Optional[str] = None
    COGNITO_REGION: Optional[str] = None
    COGNITO_ROLES_CLAIM: str = "cognito:groups"
    COGNITO_ADMIN_ROLE: str = "Admin"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

settings = Settings()
