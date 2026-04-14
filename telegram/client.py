from telethon import TelegramClient
from config.config import Settings

def create_client(settings: Settings) -> TelegramClient:
    return TelegramClient(
        settings.session_name,
        settings.tg_api_id,
        settings.tg_api_hash,
        auto_reconnect=True,
        retry_delay=5,
        request_retries=5,
        timeout=30,
    )