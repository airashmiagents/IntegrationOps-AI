"""Load settings from environment (.env) for local hackathon development."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration — CPI OData, mock mode, and OpenRouter."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "IntegrationOps-AI"
    debug: bool = False

    # SAP Cloud Integration — tenant host only, e.g. https://<account>-tmn.<region>.hana.ondemand.com
    sap_cpi_base_url: str = ""
    sap_cpi_user: str = ""
    sap_cpi_password: str = ""
    # REST OData root per SAP Swagger (Integration Content + MPL): .../api/v1/...
    sap_cpi_api_root: str = "/api/v1"
    # Full path override for MessageProcessingLogs only (leave empty to use {api_root}/MessageProcessingLogs).
    sap_cpi_mpl_path: str = ""
    # Override design-time root only if it differs from api_root (leave empty to use api_root).
    sap_cpi_designtime_odata_root: str = ""
    # Force simulated CPI responses (no outbound HTTP to tenant).
    cpi_use_mock: bool = True

    # Periodic CPI monitor (APScheduler) — pulls recent FAILED MPL + design-time + LLM.
    scheduler_enabled: bool = False
    scheduler_interval_sec: int = 300
    # Comma-separated IntegrationArtifact.Id values (same as agent ``iflow_name``).
    monitor_iflow_ids: str = ""
    # MPL lookback window for ``LogEnd`` filter (minutes).
    scheduler_lookback_minutes: int = 15

    # Step-by-step investigation narrative to stderr (see ``services.agent_trace``).
    agent_terminal_trace: bool = False

    # Append-only SQLite of chat/completions payloads + model output (see ``services.llm_audit_sqlite``).
    llm_audit_sqlite_enabled: bool = True
    llm_audit_sqlite_path: str = ""  # empty → backend/llm_audit.sqlite

    # Autonomous monitor persisted incidents (see ``services.incidents_store``).
    incidents_sqlite_enabled: bool = True
    incidents_sqlite_path: str = ""  # empty → backend/incidents.sqlite

    # OpenRouter — unified API for DeepSeek, Llama, etc.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "deepseek/deepseek-chat"
    # Used when primary model errors (HTTP non-200) or JSON parse fails. Set empty to disable.
    openrouter_fallback_model: str = "meta-llama/llama-3.1-8b-instruct:free"
    openrouter_http_referer: str = "https://localhost"
    openrouter_app_title: str = "IntegrationOps-AI"

    # Legacy aliases from older .env (optional).
    llm_api_key: str = ""
    llm_api_base_url: str = ""

    def effective_openrouter_key(self) -> str:
        return self.openrouter_api_key or self.llm_api_key

    def effective_openrouter_base(self) -> str:
        if self.llm_api_base_url and "/v1" in self.llm_api_base_url:
            return self.llm_api_base_url.rstrip("/").removesuffix("/v1") + "/v1"
        if self.llm_api_base_url:
            return self.llm_api_base_url.rstrip("/")
        return self.openrouter_base_url.rstrip("/")


settings = Settings()
