from config.config import load_settings
from mexc.client import MexcClient


if __name__ == '__main__':
    settings = load_settings()
    client = MexcClient(settings)

    order = client.place_limit_order(
        symbol="ETH_USDT",
        price=1000,
        vol=1,
        side=1,
        open_type=1,
        leverage=5,
    )

    print(order)

    if order.get("success"):
        order_id = order["data"]["orderId"]
        print(client.cancel_order(order_id))