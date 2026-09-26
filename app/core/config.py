from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_sync: str
    fpl_api_base_url: str = "https://fantasy.premierleague.com/api"
    api_key: str


settings = Settings()
