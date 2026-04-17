import hashlib
import hmac
import json
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any

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
        self._contracts_cache: dict[str, dict[str, Any]] = {}

        self.base_url = settings.mexc_base_url.rstrip("/")
        self.api_key = settings.mexc_api_key
        self.api_secret = settings.mexc_api_secret
        self.recv_window = "10000"
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })

    # -------------------------
    # Helpers
    # -------------------------

    def _now_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _private_headers(self, timestamp: str, signature: str) -> dict[str, str]:
        return {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Recv-Window": self.recv_window,
            "Signature": signature,
            "Content-Type": "application/json",
        }

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

    def _build_signature(self, timestamp: str, parameter_string: str) -> str:
        payload = f"{self.api_key}{timestamp}{parameter_string}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

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
                parameter_string = self._build_query_string(
                    params if isinstance(params, dict) else {}
                )
            else:
                if isinstance(params, dict):
                    filtered_params = {
                        k: v for k, v in params.items()
                        if v is not None
                    }
                    body = json.dumps(
                        filtered_params,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                else:
                    body = json.dumps(
                        params,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )

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

    @staticmethod
    def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
        steps = (value / step).to_integral_value(rounding=ROUND_DOWN)
        return steps * step

    # -------------------------
    # Public / market data
    # -------------------------

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/contract/ping")

    def get_contracts(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/contract/detail")

    def load_contracts_cache(self) -> None:
        response = self.get_contracts()

        if not response.get("success"):
            raise ValueError(f"Failed to load contracts: {response}")

        self._contracts_cache = {
            item["symbol"]: item
            for item in response.get("data", [])
            if item.get("symbol")
        }

    def get_contract_by_symbol(self, symbol: str) -> dict[str, Any] | None:
        if not self._contracts_cache:
            self.load_contracts_cache()

        return self._contracts_cache.get(symbol)

    # -------------------------
    # Account / positions / orders
    # -------------------------

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

    def get_open_orders(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._request(
            "GET",
            "/api/v1/private/order/list/open_orders",
            params=params,
            private=True,
        )

    def get_position_stop_orders(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._request(
            "GET",
            "/api/v1/private/stoporder/list/orders",
            params=params,
            private=True,
        )

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        response = self.get_open_positions(symbol)

        print("GET_OPEN_POSITIONS RESPONSE:", response)

        if not response.get("success"):
            return None

        data = response.get("data") or []

        # На случай если MEXC вернет объект, а не список
        if isinstance(data, dict):
            items = data.get("resultList") or data.get("list") or []
        else:
            items = data

        for item in items:
            item_symbol = str(item.get("symbol", "")).upper()
            hold_vol = float(item.get("holdVol", 0) or 0)
            state = int(item.get("state", 0) or 0)

            if item_symbol == symbol.upper() and hold_vol > 0 and state in (1, 2):
                return item

        return None

    # -------------------------
    # Normalization
    # -------------------------

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

        normalized = self._floor_to_step(value, vol_unit)
        return float(normalized)

    # -------------------------
    # Volume calculation by margin
    # -------------------------

    def calculate_volume_by_margin(
        self,
        *,
        symbol: str,
        margin_usdt: float,
        leverage: int,
        price: float,
    ) -> float:
        contract = self.get_contract_by_symbol(symbol)
        if not contract:
            raise ValueError(f"Contract not found: {symbol}")

        vol_unit = Decimal(str(contract["volUnit"]))
        min_vol = Decimal(str(contract["minVol"]))

        contract_size_raw = (
            contract.get("contractSize")
            or contract.get("contractValue")
            or contract.get("multiplier")
            or 1
        )
        contract_size = Decimal(str(contract_size_raw))

        margin = Decimal(str(margin_usdt))
        lev = Decimal(str(leverage))
        entry_price = Decimal(str(price))

        if margin <= 0:
            raise ValueError("margin_usdt must be > 0")

        if lev <= 0:
            raise ValueError("leverage must be > 0")

        if entry_price <= 0:
            raise ValueError("price must be > 0")

        target_notional = margin * lev
        raw_vol = target_notional / (entry_price * contract_size)
        normalized_vol = self._floor_to_step(raw_vol, vol_unit)

        if normalized_vol < min_vol:
            normalized_vol = min_vol

        return float(normalized_vol)

    # -------------------------
    # Order placement
    # -------------------------

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
            position_id: int | None = None,
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
            "positionId": position_id,
        }

        return self._request(
            "POST",
            "/api/v1/private/order/create",
            params=payload,
            private=True,
        )

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

        normalized_stop_loss_price = None
        if stop_loss_price is not None:
            normalized_stop_loss_price = self.normalize_price(symbol, stop_loss_price)

        normalized_take_profit_price = None
        if take_profit_price is not None:
            normalized_take_profit_price = self.normalize_price(symbol, take_profit_price)

        return self.place_order(
            symbol=symbol,
            price=normalized_price,
            vol=normalized_vol,
            side=side,
            order_type=self.ORDER_TYPE_LIMIT,
            open_type=open_type,
            leverage=leverage,
            stop_loss_price=normalized_stop_loss_price,
            take_profit_price=normalized_take_profit_price,
        )

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

    # -------------------------
    # Cancel orders
    # -------------------------

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/private/order/cancel",
            params=[int(order_id)],
            private=True,
        )

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

        results = []
        for order_id in limit_order_ids:
            results.append({
                "orderId": order_id,
                "result": self.cancel_order(str(order_id)),
            })

        return {
            "success": True,
            "code": 0,
            "data": results,
            "message": f"Canceled {len(limit_order_ids)} limit orders for {symbol}",
        }

    def cancel_all_open_orders_by_symbol(self, symbol: str) -> dict[str, Any]:
        open_orders = self.get_open_orders(symbol)

        if not open_orders.get("success"):
            return open_orders

        order_ids: list[int] = []

        for item in open_orders.get("data", []):
            order_id = item.get("orderId")
            if order_id is not None:
                order_ids.append(int(order_id))

        if not order_ids:
            return {
                "success": True,
                "code": 0,
                "data": [],
                "message": f"No open orders for {symbol}",
            }

        results = []
        for order_id in order_ids:
            result = self.cancel_order(str(order_id))
            results.append({
                "orderId": order_id,
                "result": result,
            })

        return {
            "success": True,
            "code": 0,
            "data": results,
            "message": f"Canceled {len(order_ids)} open orders for {symbol}",
        }

    # -------------------------
    # Fees / break-even
    # -------------------------

    def get_fee_details(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._request(
            "GET",
            "/api/v1/private/account/tiered_fee_rate/v2",
            params=params,
            private=True,
        )

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

    def calculate_break_even_price(
        self,
        *,
        symbol: str,
        entry_price: float,
        is_long: bool,
        open_fee_rate: float,
        close_fee_rate: float,
    ) -> float:
        contract = self.get_contract_by_symbol(symbol)
        if not contract:
            raise ValueError(f"Contract not found: {symbol}")

        entry = Decimal(str(entry_price))
        open_fee = Decimal(str(open_fee_rate))
        close_fee = Decimal(str(close_fee_rate))

        total_fee = open_fee + close_fee

        if is_long:
            be_price = entry * (Decimal("1") + total_fee)
        else:
            be_price = entry * (Decimal("1") - total_fee)

        price_unit = Decimal(str(contract["priceUnit"]))
        normalized = be_price.quantize(price_unit, rounding=ROUND_DOWN)
        return float(normalized)

    def get_position_stop_order(
        self,
        position_id: int,
        symbol: str,
    ) -> dict[str, Any] | None:
        response = self.get_position_stop_orders(symbol)

        if not response.get("success"):
            return None

        for item in response.get("data", []):
            if int(item.get("positionId", 0) or 0) != position_id:
                continue

            if item.get("symbol") != symbol:
                continue

            is_finished = int(item.get("isFinished", 0) or 0)
            if is_finished != 0:
                continue

            return item

        return None

    def change_position_stop_order(
        self,
        *,
        symbol: str,
        stop_plan_order_id: int,
        stop_loss_price: float | None,
        take_profit_price: float | None,
        loss_trend: int,
        profit_trend: int,
    ) -> dict[str, Any]:
        normalized_stop_loss_price = None
        if stop_loss_price is not None and stop_loss_price > 0:
            normalized_stop_loss_price = self.normalize_price(symbol, stop_loss_price)

        normalized_take_profit_price = None
        if take_profit_price is not None and take_profit_price > 0:
            normalized_take_profit_price = self.normalize_price(symbol, take_profit_price)

        payload = {
            "stopPlanOrderId": stop_plan_order_id,
            "stopLossPrice": normalized_stop_loss_price,
            "takeProfitPrice": normalized_take_profit_price,
            "lossTrend": loss_trend,
            "profitTrend": profit_trend,
            "stopLossReverse": 2,
            "takeProfitReverse": 2,
        }

        return self._request(
            "POST",
            "/api/v1/private/stoporder/change_plan_price",
            params=payload,
            private=True,
        )

    def place_position_stop_order(
        self,
        *,
        symbol: str,
        position_id: int,
        vol: float,
        stop_loss_price: float | None,
        take_profit_price: float | None,
        loss_trend: int,
        profit_trend: int,
        vol_type: int,
        stop_loss_type: int,
    ) -> dict[str, Any]:
        normalized_stop_loss_price = None
        if stop_loss_price is not None and stop_loss_price > 0:
            normalized_stop_loss_price = self.normalize_price(symbol, stop_loss_price)

        normalized_take_profit_price = None
        if take_profit_price is not None and take_profit_price > 0:
            normalized_take_profit_price = self.normalize_price(symbol, take_profit_price)

        payload = {
            "positionId": position_id,
            "vol": vol,
            "stopLossPrice": normalized_stop_loss_price,
            "takeProfitPrice": normalized_take_profit_price,
            "lossTrend": loss_trend,
            "profitTrend": profit_trend,
            "volType": vol_type,
            "stopLossType": stop_loss_type,
            "priceProtect": 0,
            "stopLossReverse": 2,
            "takeProfitReverse": 2,
        }

        if normalized_take_profit_price is not None:
            payload["takeProfitType"] = 0

        return self._request(
            "POST",
            "/api/v1/private/stoporder/place",
            params=payload,
            private=True,
        )

    def move_stop_loss_to_break_even_with_symbol_fee(
        self,
        symbol: str,
        *,
        entry_fee_type: str = "maker",
        exit_fee_type: str = "taker",
        use_hold_avg_price: bool = False,
    ) -> dict[str, Any]:
        try:
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
                    symbol=symbol,
                    stop_plan_order_id=stop_plan_order_id,
                    stop_loss_price=be_price,
                    take_profit_price=current_stop.get("takeProfitPrice"),
                    loss_trend=loss_trend,
                    profit_trend=int(current_stop.get("profitTrend", 1) or 1),
                )

            return self.place_position_stop_order(
                symbol=symbol,
                position_id=position_id,
                vol=hold_vol,
                stop_loss_price=be_price,
                take_profit_price=None,
                loss_trend=loss_trend,
                profit_trend=1,
                vol_type=2,
                stop_loss_type=0,
            )
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "step": "move_stop_loss_to_break_even_with_symbol_fee",
            }

    def move_stop_loss_to_break_even(self, symbol: str) -> dict[str, Any]:
        return self.move_stop_loss_to_break_even_with_symbol_fee(
            symbol,
            entry_fee_type="maker",
            exit_fee_type="taker",
        )

    # -------------------------
    # Partial close
    # -------------------------

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
        close_vol = self._floor_to_step(raw_close_vol, vol_unit)

        if close_vol < min_vol:
            close_vol = min_vol

        if close_vol > hold_vol:
            close_vol = hold_vol

        position_type = int(position.get("positionType", 0) or 0)
        open_type = int(position.get("openType", self.OPEN_TYPE_ISOLATED) or self.OPEN_TYPE_ISOLATED)

        if position_type == 1:
            close_side = self.SIDE_CLOSE_LONG
        elif position_type == 2:
            close_side = self.SIDE_CLOSE_SHORT
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
            order_type=self.ORDER_TYPE_MARKET,
            open_type=open_type,
        )

    def handle_tp_partial_close(self, symbol: str, percent: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": True,
            "step": "handle_tp_partial_close",
        }

        be_result = self.move_stop_loss_to_break_even(symbol)
        result["be_result"] = be_result

        close_result = self.close_position_partially(symbol, percent)
        result["close_result"] = close_result

        if close_result.get("success") is False:
            result["success"] = False
            result["step"] = "close_position_partially"
            return result

        cancel_result = self.cancel_limit_orders_by_symbol(symbol)
        result["cancel_result"] = cancel_result

        if cancel_result.get("success") is False:
            result["success"] = False
            result["step"] = "cancel_limit_orders_by_symbol"

        if be_result.get("success") is False:
            result["success"] = False
            if result["step"] == "handle_tp_partial_close":
                result["step"] = "move_stop_loss_to_break_even"

        return result