import hashlib
import hmac
import json
import time
from typing import Any
from decimal import Decimal, ROUND_DOWN

import requests

from config.config import Settings

class MexcClient:
    SIDE_OPEN_LONG = 1
    SIDE_CLOSE_SHORT = 2
    SIDE_OPEN_SHORT = 3
    SIDE_CLOSE_LONG = 4

    ORDER_TYPE_LIMIT = 1
    ORDER_TYPE_MARKET = 5

    OPEN_TYPE_ISOLATED = 1
    OPEN_TYPE_CROSS = 2


    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.mexc_base_url.rstrip("/")
        self.api_key = settings.mexc_api_key
        self.api_secret = settings.mexc_api_secret
        self.recv_window = "10000"
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })

    def _private_headers(self, timestamp: str, signature: str) -> dict[str, str]:
        return {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Recv-Window": self.recv_window,
            "Signature": signature,
            "Content-Type": "application/json",
        }

    # Для API нужно текущее время в ms, юзаем в подписи запроса
    def _now_ms(self) -> str:
        return str(int(time.time() * 1000))

    # Построитель запроса
    def _build_query_string(self, params: dict[str, Any] | None) -> str:
        if not params:
            return ""

        filtered: dict[str, Any] = {
            k: v for k, v in params.items()
            if v is not None
        }

        pairs = []
        for key in sorted(filtered.keys()):
            value = filtered[key]
            pairs.append(f"{key}={value}")

        return "&".join(pairs)

    # Этот метод создает криптографическую подпись запроса.
    def _build_signature(self, timestamp: str, parameter_string: str) -> str:
        payload = f"{self.api_key}{timestamp}{parameter_string}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    # универсальный метод для отправки HTTP - запросов к API
    def _request(
            self,
            method: str,
            path: str,
            params: dict[str, Any] | list[Any] | None = None,
            private: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        method = method.upper()
        params = params or {}
        headers: dict[str, str] = {}
        body = None

        if private:
            timestamp = self._now_ms()

            if method in ("GET", "DELETE"):
                parameter_string = self._build_query_string(params if isinstance(params, dict) else {})
            else:
                if isinstance(params, dict):
                    filtered_params = {k: v for k, v in params.items() if v is not None}
                    body = json.dumps(filtered_params, separators=(",", ":"), ensure_ascii=False)
                else:
                    body = json.dumps(params, separators=(",", ":"), ensure_ascii=False)

                parameter_string = body

            signature = self._build_signature(timestamp, parameter_string)
            headers = self._private_headers(timestamp, signature)

        if method == "GET":
            response = self.session.get(url, params=params, headers=headers, timeout=15)
        elif method == "DELETE":
            response = self.session.delete(url, params=params, headers=headers, timeout=15)
        elif method == "POST":
            response = self.session.post(url, data=body, headers=headers, timeout=15)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()

    # -------------------------
    # Private methods
    # -------------------------

    def ping(self) -> dict:
        return self._request("GET", "/api/v1/contract/ping")

    def get_account_assets(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/private/account/assets", private=True)

    def get_open_positions(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._request(
            "GET",
            "/api/v1/private/position/open_positions",
            params=params,
            private=True,
        )

    # Открытые лимитные ордера
    def get_open_orders(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._request(
            "GET",
            "/api/v1/private/order/list/open_orders",
            params=params,
            private=True,
        )

    # Отменяем лимитные ордера
    def cancel_limit_orders_by_symbol(self, symbol: str) -> dict[str, Any]:
        open_orders = self.get_open_orders(symbol)

        if not open_orders.get("success"):
            return open_orders

        limit_order_ids: list[int] = []

        for item in open_orders.get("data", []):
            order_type = int(item.get("orderType", 0) or 0)

            if order_type in (1, 2):
                limit_order_ids.append(int(item["orderId"]))

        if not limit_order_ids:
            return {
                "success": True,
                "code": 0,
                "data": [],
                "message": f"No open limit orders for {symbol}",
            }

        return self.cancel_orders(limit_order_ids)

    # Размещение позиции
    def place_order(
            self,
            *,
            symbol: str,
            price: float,
            vol: float,
            side: int,
            order_type: int,
            open_type: int,
            leverage: int | None = None,
            stop_loss_price: float | None = None,
            take_profit_price: float | None = None,
            external_oid: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "symbol": symbol,
            "price": price,
            "vol": vol,
            "side": side,
            "type": order_type,
            "openType": open_type,
            "leverage": leverage,
            "stopLossPrice": stop_loss_price,
            "takeProfitPrice": take_profit_price,
            "externalOid": external_oid,
        }

        return self._request(
            "POST",
            "/api/v1/private/order/create",
            params=payload,
            private=True,
        )
    # Обертка для размещения ордера
    def place_limit_order(
            self,
            *,
            symbol: str,
            price: float,
            vol: float,
            side: int,
            open_type: int,
            leverage: int,
            stop_loss_price: float | None = None,
            take_profit_price: float | None = None,
    ) -> dict[str, Any]:
        normalized_price = self.normalize_price(symbol, price)
        normalized_vol = self.normalize_volume(symbol, vol)

        return self.place_order(
            symbol=symbol,
            price=normalized_price,
            vol=normalized_vol,
            side=side,
            order_type=1,
            open_type=open_type,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    # отменяет любой ордер
    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/private/order/cancel",
            params=[int(order_id)],
            private=True,
        )

    # Список текущих позиций
    def get_contracts(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/contract/detail")


    def get_contract_by_symbol(self, symbol: str) -> dict[str, Any] | None:
        response = self.get_contracts()

        if not response.get("success"):
            return None

        for item in response.get("data", []):
            if item.get("symbol") == symbol:
                return item

        return None

    def normalize_price(self, symbol: str, price: float) -> float:
        contract = self.get_contract_by_symbol(symbol)
        if not contract:
            raise ValueError(f"Contract not found: {symbol}")

        price_unit = Decimal(str(contract["priceUnit"]))
        value = Decimal(str(price))
        normalized = value.quantize(price_unit, rounding=ROUND_DOWN)
        return float(normalized)

    def normalize_volume(self, symbol: str, vol: float) -> float:
        contract = self.get_contract_by_symbol(symbol)
        if not contract:
            raise ValueError(f"Contract not found: {symbol}")

        vol_unit = Decimal(str(contract["volUnit"]))
        min_vol = Decimal(str(contract["minVol"]))
        value = Decimal(str(vol))

        if value < min_vol:
            raise ValueError(f"Volume is less than minVol: {min_vol}")

        steps = (value / vol_unit).to_integral_value(rounding=ROUND_DOWN)
        normalized = steps * vol_unit
        return float(normalized)

    # получаем детали комиссий для символа
    def get_fee_details(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._request(
            "GET",
            "/api/v1/private/account/tiered_fee_rate/v2",
            params=params,
            private=True,
        )

    # Получаем комиссии выбранного символа
    def get_symbol_fee_rates(self, symbol: str) -> dict[str, float]:
        response = self.get_fee_details(symbol)

        if not response.get("success"):
            raise ValueError(f"Failed to get fee details for {symbol}: {response}")

        data = response.get("data") or {}

        real_maker_fee = data.get("realMakerFee")
        real_taker_fee = data.get("realTakerFee")

        if real_maker_fee is None or real_taker_fee is None:
            raise ValueError(f"Fee fields not found for {symbol}: {data}")

        return {
            "maker": float(real_maker_fee),
            "taker": float(real_taker_fee),
        }

    # Перемешаем позицию в безубыток, учитываем комиссию
    def move_stop_loss_to_break_even_with_symbol_fee(
            self,
            symbol: str,
            *,
            entry_fee_type: str = "maker",
            exit_fee_type: str = "taker",
            use_hold_avg_price: bool = False,
    ) -> dict[str, Any]:
        position = self.get_position(symbol)
        if position is None:
            return {
                "success": False,
                "error": f"Open position not found for {symbol}",
            }

        entry_price_raw = (
            position.get("holdAvgPrice")
            if use_hold_avg_price
            else position.get("openAvgPrice")
        )

        if entry_price_raw is None:
            return {
                "success": False,
                "error": f"Entry price not found for {symbol}",
            }

        fee_rates = self.get_symbol_fee_rates(symbol)

        if entry_fee_type not in fee_rates:
            return {
                "success": False,
                "error": f"Unknown entry_fee_type: {entry_fee_type}",
            }

        if exit_fee_type not in fee_rates:
            return {
                "success": False,
                "error": f"Unknown exit_fee_type: {exit_fee_type}",
            }

        open_fee_rate = fee_rates[entry_fee_type]
        close_fee_rate = fee_rates[exit_fee_type]

        position_id = int(position["positionId"])
        hold_vol = float(position["holdVol"])
        position_type = int(position["positionType"])

        is_long = position_type == 1
        loss_trend = 1 if is_long else 2

        be_price = self.calculate_break_even_price(
            symbol=symbol,
            entry_price=float(entry_price_raw),
            is_long=is_long,
            open_fee_rate=open_fee_rate,
            close_fee_rate=close_fee_rate,
        )

        current_stop = self.get_position_stop_order(position_id, symbol)

        if current_stop:
            stop_plan_order_id = int(current_stop["id"])

            return self.change_position_stop_order(
                stop_plan_order_id=stop_plan_order_id,
                stop_loss_price=be_price,
                take_profit_price=current_stop.get("takeProfitPrice"),
                loss_trend=loss_trend,
                profit_trend=int(current_stop.get("profitTrend", 1) or 1),
            )

        return self.place_position_stop_order(
            position_id=position_id,
            vol=hold_vol,
            stop_loss_price=be_price,
            take_profit_price=None,
            loss_trend=loss_trend,
            profit_trend=1,
            vol_type=2,
            stop_loss_type=0,
        )

    # Обертка под метод перевода SL в безубыток
    def move_stop_loss_to_break_even(self, symbol: str) -> dict[str, Any]:
        return self.move_stop_loss_to_break_even_with_symbol_fee(
            symbol,
            entry_fee_type="maker",
            exit_fee_type="taker",
        )

    # Частичное закрытие позиции
    def close_position_partially(self, symbol: str, percent: int) -> dict[str, Any]:
        if percent <= 0 or percent > 100:
            return {
                "success": False,
                "error": f"Percent must be in range 1..100. Got: {percent}",
            }

        position = self.get_position(symbol)
        if position is None:
            return {
                "success": False,
                "error": f"Open position not found for {symbol}",
            }

        hold_vol = Decimal(str(position.get("holdVol", 0) or 0))
        if hold_vol <= 0:
            return {
                "success": False,
                "error": f"Position volume is empty for {symbol}",
            }

        contract = self.get_contract_by_symbol(symbol)
        if not contract:
            return {
                "success": False,
                "error": f"Contract not found: {symbol}",
            }

        vol_unit = Decimal(str(contract["volUnit"]))
        min_vol = Decimal(str(contract["minVol"]))

        raw_close_vol = hold_vol * Decimal(str(percent)) / Decimal("100")
        steps = (raw_close_vol / vol_unit).to_integral_value(rounding=ROUND_DOWN)
        close_vol = steps * vol_unit

        if close_vol < min_vol:
            close_vol = min_vol

        if close_vol > hold_vol:
            close_vol = hold_vol

        position_type = int(position.get("positionType", 0) or 0)

        # 1 = long, 2 = short
        if position_type == 1:
            close_side = 4
        elif position_type == 2:
            close_side = 2
        else:
            return {
                "success": False,
                "error": f"Unknown positionType for {symbol}: {position_type}",
            }

        return self.place_order(
            symbol=symbol,
            price=0,
            vol=float(close_vol),
            side=close_side,
            order_type=5,
            open_type=2,
        )


    def get_position(self, symbol: str) -> dict[str, Any] | None:
        response = self.get_open_positions(symbol)

        if not response.get("success"):
            return None

        for item in response.get("data", []):
            hold_vol = float(item.get("holdVol", 0) or 0)
            if item.get("symbol") == symbol and hold_vol > 0:
                return item

        return None

    def handle_tp_partial_close(self, symbol: str, percent: int) -> dict[str, Any]:
        close_result = self.close_position_partially(symbol, percent)
        if close_result.get("success") is False:
            return {
                "success": False,
                "step": "close_position_partially",
                "details": close_result,
            }

        cancel_result = self.cancel_limit_orders_by_symbol(symbol)
        if cancel_result.get("success") is False:
            return {
                "success": False,
                "step": "cancel_limit_orders_by_symbol",
                "details": cancel_result,
            }

        return {
            "success": True,
            "step": "handle_tp_partial_close",
            "close_result": close_result,
            "cancel_result": cancel_result,
        }

    def place_limit_long(
            self,
            *,
            symbol: str,
            price: float,
            vol: float,
            leverage: int,
            open_type: int = OPEN_TYPE_ISOLATED,
            stop_loss_price: float | None = None,
            take_profit_price: float | None = None,
    ) -> dict[str, Any]:
        return self.place_limit_order(
            symbol=symbol,
            price=price,
            vol=vol,
            side=self.SIDE_OPEN_LONG,
            open_type=open_type,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    def place_limit_short(
            self,
            *,
            symbol: str,
            price: float,
            vol: float,
            leverage: int,
            open_type: int = OPEN_TYPE_ISOLATED,
            stop_loss_price: float | None = None,
            take_profit_price: float | None = None,
    ) -> dict[str, Any]:
        return self.place_limit_order(
            symbol=symbol,
            price=price,
            vol=vol,
            side=self.SIDE_OPEN_SHORT,
            open_type=open_type,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    def place_market_long(
            self,
            *,
            symbol: str,
            vol: float,
            leverage: int,
            open_type: int = OPEN_TYPE_ISOLATED,
    ) -> dict[str, Any]:
        normalized_vol = self.normalize_volume(symbol, vol)

        return self.place_order(
            symbol=symbol,
            price=0,
            vol=normalized_vol,
            side=self.SIDE_OPEN_LONG,
            order_type=self.ORDER_TYPE_MARKET,
            open_type=open_type,
            leverage=leverage,
        )

    def place_market_short(
            self,
            *,
            symbol: str,
            vol: float,
            leverage: int,
            open_type: int = OPEN_TYPE_ISOLATED,
    ) -> dict[str, Any]:
        normalized_vol = self.normalize_volume(symbol, vol)

        return self.place_order(
            symbol=symbol,
            price=0,
            vol=normalized_vol,
            side=self.SIDE_OPEN_SHORT,
            order_type=self.ORDER_TYPE_MARKET,
            open_type=open_type,
            leverage=leverage,
        )