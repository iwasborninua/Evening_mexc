import asyncio
import time

from config.config import load_settings
from mexc.client import MexcClient
from pprint import pprint
from telethon import functions

from telegram.client import create_client
from telegram.auth import ensure_authorized
from telegram.topic_listener import listen_selected_topics



async def main():
    settings = load_settings()
    tg_client = create_client(settings)

    print(settings)

    try:
       await ensure_authorized(tg_client, settings.tg_phone)

       await listen_selected_topics(
           client=tg_client,
           chat_id=settings.chat_id,
           topic_ids=[
               settings.topic_low_cap_id,
               settings.topic_mid_high_cap_id,
           ],
       )

    finally:
        await tg_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())