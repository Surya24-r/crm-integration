from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    zoho_accounts_url: str
    zoho_api_url: str
    zoho_org_id: str
    zoho_client_id: str
    zoho_client_secret: str
    zoho_refresh_token: str
    zoho_rate_per_minute: int = 80
    zoho_app_url: str = "https://books.zoho.com/app"  # for links back to records
    zoho_base_currency: str = "AED"
    zoho_place_of_supply: str = "DU"  # UAE emirate code used on sales orders

    crm_base_url: str = ""
    crm_api_token: str = ""

    webhook_secret: str = "change-me"


settings = Settings()