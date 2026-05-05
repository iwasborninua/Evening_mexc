import re
from pprint import pprint
from typing import Any

from config.config import load_settings
from mexc.client import MexcClient


settings = load_settings()
mexc = MexcClient(settings)


def build_result(text: str) -> dict[str, Any]:
    """
    Базовая структура ответа.
    """
    return {
        "text": text,
        "action": None,
        "success": False,
    }


def extract_symbol(text: str) -> str | None:
    """
    Ищет тикер вида $BTC, $ETH, $JST
    и возвращает symbol в формате BTC_USDT.
    """
    asset = re.search(r"\$([A-Z0-9]+)", text, re.IGNORECASE)
    if not asset:
        return None
    return f"{asset.group(1).upper()}_USDT"

def parse_followup_message(text: str) -> dict[str, Any] | None:
    """
    Разбирает follow-up сообщения, например:
    - $XPL hit TP2 - move SL to BE
    - $JST hit 2 entry +39% profit - move SL to BE
    - $JST close vol - move SL to BE
    - $JST partial close - move SL to BE
    - $DOGE cancel

    Процент частичного закрытия НЕ парсится из сообщения.
    Если сообщение означает частичное закрытие — процент берётся из settings.partial_percent.
    """
    symbol = extract_symbol(text)
    if not symbol:
        return None

    # Только отмена сигнала / ордеров.
    # closed НЕ используем здесь, чтобы не спутать с partial closed.
    cancel_match = re.search(
        r"\b(?:cancel|cancelled)\b",
        text,
        re.IGNORECASE,
    )

    has_be = bool(
        re.search(
            r"\b(?:move\s+SL\s+to\s+BE|SL\s+to\s+BE|move\s+to\s+BE|BE)\b",
            text,
            re.IGNORECASE,
        )
    )

    # hit TP2 / TP2 hit
    tp_match = re.search(
        r"\bhit\s*TP\s*(\d+)\b|\bTP\s*(\d+)\s*hit\b",
        text,
        re.IGNORECASE,
    )

    # hit 2 entry / hit entry 2
    entry_hit_match = re.search(
        r"\bhit\s+(\d+)\s*entry\b|\bhit\s+entry\s*(\d+)\b",
        text,
        re.IGNORECASE,
    )

    # +39% profit
    profit_match = re.search(
        r"([+-]?\d+(?:\.\d+)?)\s*%\s*profit\b",
        text,
        re.IGNORECASE,
    )

    # Частичное закрытие без парсинга процента.
    # Поддерживает старые и новые форматы:
    # close 10% vol, close vol, close position, partial close, partially closed
    partial_close_match = re.search(
        r"\b(?:"
        r"partial\s+close|"
        r"partially\s+closed|"
        r"close\s+\d+%(?:\s*vol)?|"
        r"close\s+vol|"
        r"close\s+volume|"
        r"close\s+position|"
        r"close\s+part|"
        r"take\s+partial|"
        r"close\s+some|"
        r"close\s+position\s+partially"
        r")\b",
        text,
        re.IGNORECASE,
    )

    tp_number = None
    if tp_match:
        tp_number = tp_match.group(1) or tp_match.group(2)

    entry_number = None
    if entry_hit_match:
        entry_number = entry_hit_match.group(1) or entry_hit_match.group(2)

    profit_percent = float(profit_match.group(1)) if profit_match else None

    should_partial_close = any([
        partial_close_match,
        tp_match and has_be,
        profit_match and has_be,
        entry_hit_match and has_be,
    ])

    is_followup = any([
        cancel_match,
        should_partial_close,
        has_be,
        tp_match,
        entry_hit_match,
        profit_match,
    ])

    if not is_followup:
        return None

    return {
        "symbol": symbol,
        "cancel": bool(cancel_match),
        "close_percent": settings.partial_percent if should_partial_close else None,
        "move_to_be": has_be,
        "tp_number": int(tp_number) if tp_number else None,
        "entry_number": int(entry_number) if entry_number else None,
        "profit_percent": profit_percent,
    }


def parse_new_signal_message(text: str) -> dict[str, Any] | None:
    """
    Разбирает новый торговый сигнал, например:
    Long/Short + тикер + leverage + entry + TP + SL
    """
    direction = re.search(r"\b(Long|Short)\b", text, re.IGNORECASE)
    symbol = extract_symbol(text)

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

    if not all([direction, symbol, leverage, entry_match, tp_match, sl_match]):
        return None

    tp_values = re.findall(r"[\d.]+", tp_match.group(1))
    if not tp_values:
        return None

    return {
        "symbol": symbol,
        "direction": direction.group(1).lower(),
        "leverage": int(leverage.group(1)),
        "entry_price_1": float(entry_match.group(1)),
        "entry_price_2": float(entry_match.group(2)),
        "stop_loss_price": float(sl_match.group(1)),
        # Берём последний TP как финальный тейк
        "take_profit_price": float(tp_values[-1]),
    }


def handle_cancel(symbol: str, text: str) -> dict[str, Any]:
    """
    Отмена всех открытых ордеров по символу.
    """
    result = build_result(text)

    cancel_result = mexc.cancel_all_open_orders_by_symbol(symbol)

    result.update({
        "action": "cancel_all_orders",
        "symbol": symbol,
        "success": bool(cancel_result.get("success")),
        "data": cancel_result,
    })

    return result


def handle_partial_close(
    symbol: str,
    close_percent: int,
    move_to_be: bool,
    text: str,
) -> dict[str, Any]:
    """
    Частичное закрытие позиции.
    Если в сообщении есть BE, после частичного закрытия
    логика может перенести стоп в безубыток.
    """
    result = build_result(text)

    if move_to_be:
        partial_result = mexc.handle_tp_partial_close(symbol, close_percent)
    else:
        partial_result = mexc.close_position_partially(symbol, close_percent)

    result.update({
        "action": "partial_close",
        "symbol": symbol,
        "percent": close_percent,
        "move_to_be": move_to_be,
        "success": bool(partial_result.get("success")),
        "data": partial_result,
    })

    return result


def calculate_order_volumes(
    symbol: str,
    leverage: int,
    entry_price_1: float,
    entry_price_2: float,
) -> tuple[float, float]:
    """
    Считает объёмы для двух лимитных ордеров
    по заданной марже из настроек.
    """
    order_vol_1 = mexc.calculate_volume_by_margin(
        symbol=symbol,
        margin_usdt=settings.trading_margin,
        leverage=leverage,
        price=entry_price_1,
    )

    order_vol_2 = mexc.calculate_volume_by_margin(
        symbol=symbol,
        margin_usdt=settings.trading_margin,
        leverage=leverage,
        price=entry_price_2,
    )

    return order_vol_1, order_vol_2


def place_entry_orders(
    symbol: str,
    direction: str,
    leverage: int,
    entry_price_1: float,
    entry_price_2: float,
    order_vol_1: float,
    order_vol_2: float,
    stop_loss_price: float,
    take_profit_price: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Выставляет два лимитных ордера:
    либо long, либо short.
    """
    if direction == "long":
        order_1 = mexc.place_limit_long(
            symbol=symbol,
            price=entry_price_1,
            vol=order_vol_1,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        order_2 = mexc.place_limit_long(
            symbol=symbol,
            price=entry_price_2,
            vol=order_vol_2,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )
    else:
        order_1 = mexc.place_limit_short(
            symbol=symbol,
            price=entry_price_1,
            vol=order_vol_1,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        order_2 = mexc.place_limit_short(
            symbol=symbol,
            price=entry_price_2,
            vol=order_vol_2,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    return order_1, order_2


def handle_new_signal(signal_data: dict[str, Any], text: str) -> dict[str, Any]:
    """
    Обрабатывает новый торговый сигнал:
    - считает объёмы
    - выставляет 2 лимитных ордера
    """
    result = build_result(text)

    symbol = signal_data["symbol"]
    direction = signal_data["direction"]
    leverage = signal_data["leverage"]
    entry_price_1 = signal_data["entry_price_1"]
    entry_price_2 = signal_data["entry_price_2"]
    stop_loss_price = signal_data["stop_loss_price"]
    take_profit_price = signal_data["take_profit_price"]

    try:
        order_vol_1, order_vol_2 = calculate_order_volumes(
            symbol=symbol,
            leverage=leverage,
            entry_price_1=entry_price_1,
            entry_price_2=entry_price_2,
        )
    except Exception as e:
        result.update({
            "action": "open_position",
            "symbol": symbol,
            "success": False,
            "error": f"Volume calculation failed: {e}",
        })
        return result

    order_1, order_2 = place_entry_orders(
        symbol=symbol,
        direction=direction,
        leverage=leverage,
        entry_price_1=entry_price_1,
        entry_price_2=entry_price_2,
        order_vol_1=order_vol_1,
        order_vol_2=order_vol_2,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
    )

    success = bool(order_1.get("success")) and bool(order_2.get("success"))

    result.update({
        "action": "open_position",
        "symbol": symbol,
        "direction": direction,
        "leverage": leverage,
        "entry_prices": [entry_price_1, entry_price_2],
        "volumes": [order_vol_1, order_vol_2],
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "success": success,
        "orders": [order_1, order_2],
    })

    return result


def parse_signal_message(text: str) -> dict[str, Any] | None:
    """
    Главная функция.
    Определяет тип сообщения и вызывает нужную обработку:
    1. cancel / closed
    2. partial close / BE / TP update
    3. новый сигнал на открытие позиции
    """
    # Сначала пробуем разобрать follow-up сообщение
    followup_data = parse_followup_message(text)
    if followup_data:
        symbol = followup_data["symbol"]

        # 1. Отмена / закрытие
        if followup_data["cancel"]:
            result = handle_cancel(symbol, text)
            pprint(result)
            return result

        # 2. Частичное закрытие
        if followup_data["close_percent"] is not None:
            result = handle_partial_close(
                symbol=symbol,
                close_percent=followup_data["close_percent"],
                move_to_be=followup_data["move_to_be"],
                text=text,
            )
            pprint(result)
            return result

        # Если это follow-up, но без чёткого действия,
        # можно вернуть информационный ответ
        result = build_result(text)
        result.update({
            "action": "followup_info",
            "symbol": symbol,
            "success": True,
            "data": followup_data,
        })
        pprint(result)
        return result

    # Если не follow-up, пробуем разобрать как новый сигнал
    signal_data = parse_new_signal_message(text)
    if not signal_data:
        return None

    result = handle_new_signal(signal_data, text)
    pprint(result)
    return result