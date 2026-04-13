import re
from config.config import load_settings
from mexc.client import MexcClient
from pprint import pprint

settings = load_settings()
mexc = MexcClient(settings)
vol = settings.trading_margin

def parse_signal_message(text: str) -> dict | None:
    direction = re.search(r"\b(Long|Short)\b", text, re.IGNORECASE)
    asset = re.search(r"\$([A-Z0-9]+)", text)
    leverage = re.search(r"(?:Max|Leverage)\s+(\d+)x", text, re.IGNORECASE)
    leverage_value = int(leverage.group(1)) if leverage else None
    entry_match = re.search(r"Entry:\s*([\d.]+)\s*-\s*([\d.]+)", text, re.IGNORECASE)
    tp_match = re.search(r"TP:\s*([^\n]+)", text, re.IGNORECASE)
    sl_match = re.search(r"SL:\s*([\d.]+)", text, re.IGNORECASE)
    cancel = bool(re.search(r"\b(?:cancel|closed|close)\b", text, re.IGNORECASE))


    hit_tp = re.search(
        r"hit\s+TP\d*.*?close\s+(\d+)%(?:.*?(\bBE\b))?",
        text,
        re.IGNORECASE,
    )

    if all([direction, asset, leverage, entry_match, tp_match, sl_match]):
        symbol = asset.group(1) + '_USDT'
        tp_values = re.findall(r"[\d.]+", tp_match.group(1))

        if direction.group(1).lower() == "long":
            order_1 = mexc.place_limit_long(
                symbol=symbol,
                price=float(entry_match.group(1)),
                vol=float(vol),
                leverage=int(leverage.group(1)),
                stop_loss_price=float(sl_match.group(1)),
                take_profit_price=float(tp_values[-1]),
            )

            if entry_match.group(2):
                order_2 = mexc.place_limit_long(
                    symbol=symbol,
                    price=float(entry_match.group(2)),
                    vol=float(vol),
                    leverage=int(leverage.group(1)),
                    stop_loss_price=float(sl_match.group(1)),
                    take_profit_price=float(tp_values[-1]),
                )

        elif direction.group(1).lower() == "short":
            order_1 = mexc.place_limit_short(
                symbol=symbol,
                price=float(entry_match.group(1)),
                vol=float(vol),
                leverage=int(leverage.group(1)),
                stop_loss_price=float(sl_match.group(1)),
                take_profit_price=float(tp_values[-1]),
            )

            pprint(order_1)

            if entry_match.group(2):
                order_2 = mexc.place_limit_short(
                    symbol=symbol,
                    price=float(entry_match.group(2)),
                    vol=float(vol),
                    leverage=int(leverage.group(1)),
                    stop_loss_price=float(sl_match.group(1)),
                    take_profit_price=float(tp_values[-1]),
                )

                pprint(order_2)