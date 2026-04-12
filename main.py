from config.config import load_settings
from mexc.client import MexcClient
import time


if __name__ == '__main__':
    start = time.perf_counter()
    settings = load_settings()
    client = MexcClient(settings)

    client.ping()
    client.load_contracts_cache()

    order_1 = client.place_limit_short(
        symbol="BTC_USDT",
        price=72800,
        vol=1,
        leverage=5,
        stop_loss_price=73500,
        take_profit_price=71000,
    )

    order_2 = client.place_limit_short(
        symbol="BTC_USDT",
        price=73200,
        vol=1,
        leverage=5,
        stop_loss_price=73800,
        take_profit_price=71500,
    )

    print("ORDER 1:", order_1)
    print("ORDER 2:", order_2)

    elapsed = time.perf_counter() - start

    print(f"Elapsed: {elapsed:.3f}s")