import asyncio
import time

from config.config import load_settings
from mexc.client import MexcClient
from pprint import pprint
from telethon import functions

from telegram.client import create_client
from telegram.auth import ensure_authorized
from telegram.topic_listener import listen_selected_topics

from parser.signal_parser import parse_signal_message



async def main():
    settings = load_settings()
    tg_client = create_client(settings)


    test_text = """$AVAX hit TP2, close 10% vol 🎉🎉"""
    #     test_text = """Limit Scalp Short $BTC (Leverage 15x) 📉
    #
    # Entry: 74700.0 - 76043.3
    # TP: 72926.0 - 71404.5 - 69322.6 - 67721.0 - 65446.3
    # SL: 77250.0"""

    parse_signal_message(test_text)

    # try:
    #    await ensure_authorized(tg_client, settings.tg_phone)
    #
    #    await listen_selected_topics(
    #        client=tg_client,
    #        chat_id=settings.chat_id,
    #        topic_ids=[
    #            settings.topic_low_cap_id,
    #            settings.topic_mid_high_cap_id,
    #        ],
    #    )
    #
    # finally:
    #     await tg_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())