from config.config import load_settings
from mexc.client import MexcClient


if __name__ == '__main__':
    settings = load_settings()
    client = MexcClient(settings)

    ololo = client.get_symbol_fee_rates('BTC_USDT')

    print(ololo)