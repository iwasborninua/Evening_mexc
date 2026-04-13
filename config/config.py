import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    tg_api_id: int
    tg_api_hash: str
    tg_phone: str
    tg_chat_id: int
    topic_low_cap_id: int
    topic_mid_high_cap_id: int
    mexc_api_key: str
    mexc_api_secret: str
    mexc_base_url: str
    trading_margin: float
    session_name: str = "tg_session"


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        tg_api_id=int(os.getenv("TG_API_ID")),
        tg_api_hash=os.getenv("TG_API_HASH"),
        tg_phone=os.getenv("TG_PHONE"),
        tg_chat_id=int(os.getenv("TG_CHAT_ID")),
        session_name=os.getenv("TG_SESSION", "tg_session").strip(),
        topic_low_cap_id=int(os.getenv("TOPIC_LOW_CAP_ID")),
        topic_mid_high_cap_id=int(os.getenv("TOPIC_MID_HIGH_CAP_ID")),
        mexc_api_key=os.getenv("MEXC_API_KEY"),
        mexc_api_secret=os.getenv("MEXC_API_SECRET"),
        mexc_base_url=os.getenv("MEXC_BASE_URL", "https://api.mexc.com"),
        trading_margin=float(os.getenv("TRADING_MARGIN", "2")),
    )