from config.config import load_settings
from mexc.client import MexcClient
from pprint import pprint
from telethon import functions
from telegram.client import create_client
import time


if __name__ == '__main__':
    settings = load_settings()
    tg_client = create_client(settings)
