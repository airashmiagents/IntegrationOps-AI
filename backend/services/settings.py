"""Load settings from environment (.env) for local hackathon development."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration — CPI OData, mock mode, and OpenRouter."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "IntegrationOps-AI"
    debug: bool = False

    # SAP Cloud Integration — OData monitoring (Basic auth is common for runtime APIs).
    sap_cpi_base_url: str = ""
    sap_cpi_user: str = ""
    sap_cpi_password: str = ""
    # OData entity path for MPL (default matches many tenants). Override if you get HTTP 404.
    sap_cpi_mpl_path: str = "/http/v1/MessageProcessingLogs"
    # Force simulated CPI responses (no outbound HTTP to tenant).
    cpi_use_mock: bool = True

    # OpenRouter — unified API for DeepSeek, Llama, etc.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "deepseek/deepseek-chat"
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
