from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    database_url: str = "postgresql+asyncpg://receptionist:receptionist@localhost:5432/receptionist"
    checkpointer_database_url: str = "postgresql://receptionist:receptionist@localhost:5432/receptionist"

    # Spoken persona name only. Lab name/address/phone/hours live in the
    # lab_info table, not here -- see instructions.py.
    agent_name: str = "Sara"

    # GPT-Live's backend reasoning model (responses_options["model"]) -- the
    # model that actually picks tools and drives the conversation logic.
    # The voice/speech layer itself is always gpt-live-1 (see agent.py).
    reasoning_model: str = "gpt-4o-mini"

    # Prices in the catalog/seed data are in this currency (data.json is INR).
    currency_symbol: str = "₹"

    # "dev" mode (see worker.py) defaults to DEBUG logging otherwise, which is
    # noisy enough to backpressure a piped stdout consumer (see run.py) and
    # stall the worker's event loop -- delaying responses and transcription.
    log_level: str = "WARN"

    token_server_host: str = "0.0.0.0"
    token_server_port: int = 8080

    # Real phone line (SIP) -- optional, unused by the browser demo.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_trunk_sid: str = ""
    livekit_sip_trunk_id: str = ""
    livekit_sip_dispatch_rule_id: str = ""
    lab_phone_number: str = ""


settings = Settings()
