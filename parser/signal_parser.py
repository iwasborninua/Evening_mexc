import re
from pprint import pprint

from config.config import load_settings
from mexc.client import MexcClient

settings = load_settings()
mexc = MexcClient(settings)


def parse_signal_message(text: str) -> dict | None:
    direction = re.search(r"\b(Long|Short)\b", text, re.IGNORECASE)
    asset = re.search(r"\$([A-Z0-9]+)", text)
    leverage = re.search(
        r"(?:Max|Leverage)\s*\(?\s*(\d+)x",
        text,
        re.IGNORECASE,
    )
    entry_match = re.search(
        r"Entry:\s*([\d.]+)\s*-\s*([\d.]+)",
        text,
        re.IGNORECASE,
    )
    tp_match = re.search(r"TP:\s*([^\n]+)", text, re.IGNORECASE)
    sl_match = re.search(r"SL:\s*([\d.]+)", text, re.IGNORECASE)

    # Только cancel / closed, без close,
    # чтобы не ловить "close 10% vol" из сообщений про TP
    cancel_match = re.search(r"\b(?:cancel|closed)\b", text, re.IGNORECASE)

    # Пример:
    # "$XPL hit TP2, close 60% vol - move SL to BE"
    hit_tp = re.search(
        r"hit\s+TP\d*.*?close\s+(\d+)%(?:.*?(\bBE\b))?",
        text,
        re.IGNORECASE,
    )

    result: dict[str, object] = {
        "text": text,
        "action": None,
        "success": False,
    }

    # -------------------------
    # Отмена всех ордеров по символу
    # -------------------------
    if asset and cancel_match:
        symbol = asset.group(1) + "_USDT"
        cancel_result = mexc.cancel_all_open_orders_by_symbol(symbol)

        result.update({
            "action": "cancel_all_orders",
            "symbol": symbol,
            "success": bool(cancel_result.get("success")),
            "data": cancel_result,
        })

        pprint(result)
        return result

    # -------------------------
    # Частичный профит
    # -------------------------
    if asset and hit_tp:
        symbol = asset.group(1) + "_USDT"
        percent = int(hit_tp.group(1))
        has_be = bool(hit_tp.group(2))

        if has_be:
            partial_result = mexc.handle_tp_partial_close(symbol, percent)
        else:
            partial_result = mexc.close_position_partially(symbol, percent)

        result.update({
            "action": "partial_close",
            "symbol": symbol,
            "percent": percent,
            "move_to_be": has_be,
            "success": bool(partial_result.get("success")),
            "data": partial_result,
        })

        pprint(result)
        return result

    # -------------------------
    # Открытие позиции по сигналу
    # -------------------------
    if not all([direction, asset, leverage, entry_match, tp_match, sl_match]):
        return None

    symbol = asset.group(1) + "_USDT"
    leverage_value = int(leverage.group(1))
    entry_price_1 = float(entry_match.group(1))
    entry_price_2 = float(entry_match.group(2))
    stop_loss_price = float(sl_match.group(1))
    tp_values = re.findall(r"[\d.]+", tp_match.group(1))

    if not tp_values:
        return None

    take_profit_price = float(tp_values[-1])

    try:
        order_vol_1 = mexc.calculate_volume_by_margin(
            symbol=symbol,
            margin_usdt=settings.trading_margin,
            leverage=leverage_value,
            price=entry_price_1,
        )

        order_vol_2 = mexc.calculate_volume_by_margin(
            symbol=symbol,
            margin_usdt=settings.trading_margin,
            leverage=leverage_value,
            price=entry_price_2,
        )
    except Exception as e:
        result.update({
            "action": "open_position",
            "symbol": symbol,
            "success": False,
            "error": f"Volume calculation failed: {e}",
        })
        pprint(result)
        return result

    if direction.group(1).lower() == "long":
        order_1 = mexc.place_limit_long(
            symbol=symbol,
            price=entry_price_1,
            vol=order_vol_1,
            leverage=leverage_value,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        order_2 = mexc.place_limit_long(
            symbol=symbol,
            price=entry_price_2,
            vol=order_vol_2,
            leverage=leverage_value,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    else:
        order_1 = mexc.place_limit_short(
            symbol=symbol,
            price=entry_price_1,
            vol=order_vol_1,
            leverage=leverage_value,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        order_2 = mexc.place_limit_short(
            symbol=symbol,
            price=entry_price_2,
            vol=order_vol_2,
            leverage=leverage_value,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    success = bool(order_1.get("success")) and bool(order_2.get("success"))

    result.update({
        "action": "open_position",
        "symbol": symbol,
        "direction": direction.group(1).lower(),
        "leverage": leverage_value,
        "entry_prices": [entry_price_1, entry_price_2],
        "volumes": [order_vol_1, order_vol_2],
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "success": success,
        "orders": [order_1, order_2],
    })

    pprint(result)
    return result