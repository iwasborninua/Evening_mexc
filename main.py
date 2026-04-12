from config.config import load_settings
from mexc.client import MexcClient


if __name__ == '__main__':
    settings = load_settings()
    client = MexcClient(settings)

