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

    def __init__(self, settings: Settings, logger=None) -> None:
        self._contracts_cache: dict[str, dict[str, Any]] = {}

        self.base_url = settings.mexc_base_url.rstrip("/")
        self.api_key = settings.mexc_api_key
        self.api_secret = settings.mexc_api_secret
        self.recv_window = "10000"
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })
        self.logger = logger

    # -------------------------
    # Logging helpers
    # -------------------------

    def _log_info(self, message: str, *args) -> None:
        formatted = message % args if args else message
        print(formatted)

        if self.logger:
            self.logger.info(message, *args)

    def _log_error(self, message: str, *args) -> None:
        formatted = message % args if args else message
        print(formatted)

        if self.logger:
            self.logger.error(message, *args)

    def _log_exception(self, message: str, *args) -> None:
        formatted = message % args if args else message
        print(formatted)

        if self.logger:
            self.logger.exception(message, *args)

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

        self._log_info(
            "HTTP request | method=%s | path=%s | private=%s | params=%s",
            method,
            path,
            private,
            params,
        )

        try:
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

            self._log_info(
                "HTTP response | method=%s | path=%s | status_code=%s",
                method,
                path,
                response.status_code,
            )

            response.raise_for_status()
            result = response.json()

            self._log_info(
                "HTTP response body | method=%s | path=%s | success=%s",
                method,
                path,
                result.get("success"),
            )

            return result

        except Exception as e:
            self._log_exception(
                "HTTP request failed | method=%s | path=%s | error=%s",
                method,
                path,
                e,
            )
            raise

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
        self._log_info("Loading contracts cache")

        response = self.get_contracts()

        if not response.get("success"):
            self._log_error("Failed to load contracts cache | response=%s", response)
            raise ValueError(f"Failed to load contracts: {response}")

        self._contracts_cache = {
            item["symbol"]: item
            for item in response.get("data", [])
            if item.get("symbol")
        }

        self._log_info(
            "Contracts cache loaded | count=%s",
            len(self._contracts_cache),
        )

    def get_contract_by_symbol(self, symbol: str) -> dict[str, Any] | None:
        if not self._contracts_cache:
            self.load_contracts_cache()

        contract = self._contracts_cache.get(symbol)

        if contract:
            self._log_info("Contract found | symbol=%s", symbol)
        else:
            self._log_error("Contract not found | symbol=%s", symbol)

        return contract

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

        self._log_info("GET_OPEN_POSITIONS RESPONSE: %s", response)

        if not response.get("success"):
            self._log_error(
                "Failed get_open_positions | symbol=%s | response=%s",
                symbol,
                response,
            )
            return None

        data = response.get("data") or []

        if isinstance(data, dict):
            items = data.get("resultList") or data.get("list") or []
        else:
            items = data

        for item in items:
            item_symbol = str(item.get("symbol", "")).upper()
            hold_vol = float(item.get("holdVol", 0) or 0)
            state = int(item.get("state", 0) or 0)

            if item_symbol == symbol.upper() and hold_vol > 0 and state in (1, 2):
                self._log_info(
                    "Open position found | symbol=%s | hold_vol=%s | state=%s",
                    symbol,
                    hold_vol,
                    state,
                )
                return item

        self._log_info("Open position not found | symbol=%s", symbol)
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

        self._log_info(
            "Price normalized | symbol=%s | input=%s | output=%s",
            symbol,
            price,
            float(normalized),
        )

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

        self._log_info(
            "Volume normalized | symbol=%s | input=%s | output=%s",
            symbol,
            vol,
            float(normalized),
        )

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

        self._log_info(
            "Volume calculated | symbol=%s | margin_usdt=%s | leverage=%s | price=%s | result=%s",
            symbol,
            margin_usdt,
            leverage,
            price,
            float(normalized_vol),
        )

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

        self._log_info(
            "Place order | symbol=%s | price=%s | vol=%s | side=%s | type=%s | open_type=%s | leverage=%s",
            symbol,
            price,
            vol,
            side,
            order_type,
            open_type,
            leverage,
        )

        result = self._request(
            "POST",
            "/api/v1/private/order/create",
            params=payload,
            private=True,
        )

        self._log_info(
            "Place order result | symbol=%s | success=%s | result=%s",
            symbol,
            result.get("success"),
            result,
        )

        return result

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
        self._log_info("Cancel order | order_id=%s", order_id)

        result = self._request(
            "POST",
            "/api/v1/private/order/cancel",
            params=[int(order_id)],
            private=True,
        )

        self._log_info(
            "Cancel order result | order_id=%s | success=%s | result=%s",
            order_id,
            result.get("success"),
            result,
        )

        return result

    def cancel_limit_orders_by_symbol(self, symbol: str) -> dict[str, Any]:
        self._log_info("Cancel limit orders by symbol | symbol=%s", symbol)

        open_orders = self.get_open_orders(symbol)

        if not open_orders.get("success"):
            self._log_error(
                "Failed get_open_orders for cancel limit | symbol=%s | response=%s",
                symbol,
                open_orders,
            )
            return open_orders

        limit_order_ids: list[int] = []

        for item in open_orders.get("data", []):
            order_type = int(item.get("orderType", 0) or 0)
            if order_type in (1, 2):
                limit_order_ids.append(int(item["orderId"]))

        if not limit_order_ids:
            result = {
                "success": True,
                "code": 0,
                "data": [],
                "message": f"No open limit orders for {symbol}",
            }
            self._log_info("Cancel limit orders result | %s", result)
            return result

        results = []
        for order_id in limit_order_ids:
            results.append({
                "orderId": order_id,
                "result": self.cancel_order(str(order_id)),
            })

        result = {
            "success": True,
            "code": 0,
            "data": results,
            "message": f"Canceled {len(limit_order_ids)} limit orders for {symbol}",
        }

        self._log_info("Cancel limit orders result | symbol=%s | result=%s", symbol, result)
        return result

    def cancel_all_open_orders_by_symbol(self, symbol: str) -> dict[str, Any]:
        self._log_info("Cancel all open orders by symbol | symbol=%s", symbol)

        open_orders = self.get_open_orders(symbol)

        if not open_orders.get("success"):
            self._log_error(
                "Failed get_open_orders for cancel all | symbol=%s | response=%s",
                symbol,
                open_orders,
            )
            return open_orders

        order_ids: list[int] = []

        for item in open_orders.get("data", []):
            order_id = item.get("orderId")
            if order_id is not None:
                order_ids.append(int(order_id))

        if not order_ids:
            result = {
                "success": True,
                "code": 0,
                "data": [],
                "message": f"No open orders for {symbol}",
            }
            self._log_info("Cancel all open orders result | %s", result)
            return result

        results = []
        for order_id in order_ids:
            result = self.cancel_order(str(order_id))
            results.append({
                "orderId": order_id,
                "result": result,
            })

        final_result = {
            "success": True,
            "code": 0,
            "data": results,
            "message": f"Canceled {len(order_ids)} open orders for {symbol}",
        }

        self._log_info(
            "Cancel all open orders result | symbol=%s | result=%s",
            symbol,
            final_result,
        )

        return final_result

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

        result = {
            "maker": float(real_maker_fee),
            "taker": float(real_taker_fee),
        }

        self._log_info("Fee rates | symbol=%s | result=%s", symbol, result)
        return result

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

        self._log_info(
            "Break-even price calculated | symbol=%s | entry_price=%s | is_long=%s | be_price=%s",
            symbol,
            entry_price,
            is_long,
            float(normalized),
        )

        return float(normalized)

    def get_position_stop_order(
        self,
        position_id: int,
        symbol: str,
    ) -> dict[str, Any] | None:
        response = self.get_position_stop_orders(symbol)

        if not response.get("success"):
            self._log_error(
                "Failed get_position_stop_orders | symbol=%s | response=%s",
                symbol,
                response,
            )
            return None

        for item in response.get("data", []):
            if int(item.get("positionId", 0) or 0) != position_id:
                continue

            if item.get("symbol") != symbol:
                continue

            is_finished = int(item.get("isFinished", 0) or 0)
            if is_finished != 0:
                continue

            self._log_info(
                "Position stop order found | symbol=%s | position_id=%s | stop_order_id=%s",
                symbol,
                position_id,
                item.get("id"),
            )
            return item

        self._log_info(
            "Position stop order not found | symbol=%s | position_id=%s",
            symbol,
            position_id,
        )
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

        self._log_info(
            "Change position stop order | symbol=%s | stop_plan_order_id=%s | stop_loss=%s | take_profit=%s",
            symbol,
            stop_plan_order_id,
            normalized_stop_loss_price,
            normalized_take_profit_price,
        )

        result = self._request(
            "POST",
            "/api/v1/private/stoporder/change_plan_price",
            params=payload,
            private=True,
        )

        self._log_info(
            "Change position stop order result | symbol=%s | success=%s | result=%s",
            symbol,
            result.get("success"),
            result,
        )

        return result

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

        self._log_info(
            "Place position stop order | symbol=%s | position_id=%s | vol=%s | stop_loss=%s | take_profit=%s",
            symbol,
            position_id,
            vol,
            normalized_stop_loss_price,
            normalized_take_profit_price,
        )

        result = self._request(
            "POST",
            "/api/v1/private/stoporder/place",
            params=payload,
            private=True,
        )

        self._log_info(
            "Place position stop order result | symbol=%s | success=%s | result=%s",
            symbol,
            result.get("success"),
            result,
        )

        return result

    def move_stop_loss_to_break_even_with_symbol_fee(
        self,
        symbol: str,
        *,
        entry_fee_type: str = "maker",
        exit_fee_type: str = "taker",
        use_hold_avg_price: bool = False,
    ) -> dict[str, Any]:
        try:
            self._log_info(
                "Move SL to break-even | symbol=%s | entry_fee_type=%s | exit_fee_type=%s | use_hold_avg_price=%s",
                symbol,
                entry_fee_type,
                exit_fee_type,
                use_hold_avg_price,
            )

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

                result = self.change_position_stop_order(
                    symbol=symbol,
                    stop_plan_order_id=stop_plan_order_id,
                    stop_loss_price=be_price,
                    take_profit_price=current_stop.get("takeProfitPrice"),
                    loss_trend=loss_trend,
                    profit_trend=int(current_stop.get("profitTrend", 1) or 1),
                )
                self._log_info("Move SL to break-even result | symbol=%s | result=%s", symbol, result)
                return result

            result = self.place_position_stop_order(
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
            self._log_info("Move SL to break-even result | symbol=%s | result=%s", symbol, result)
            return result

        except Exception as e:
            self._log_exception("Move SL to break-even failed | symbol=%s | error=%s", symbol, e)
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
        self._log_info("Close position partially | symbol=%s | percent=%s", symbol, percent)

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

        self._log_info(
            "Partial close calculated | symbol=%s | hold_vol=%s | close_vol=%s | close_side=%s",
            symbol,
            float(hold_vol),
            float(close_vol),
            close_side,
        )

        result = self.place_order(
            symbol=symbol,
            price=0,
            vol=float(close_vol),
            side=close_side,
            order_type=self.ORDER_TYPE_MARKET,
            open_type=open_type,
        )

        self._log_info(
            "Close position partially result | symbol=%s | success=%s | result=%s",
            symbol,
            result.get("success"),
            result,
        )

        return result

    def handle_tp_partial_close(self, symbol: str, percent: int) -> dict[str, Any]:
        self._log_info("Handle TP partial close | symbol=%s | percent=%s", symbol, percent)

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
            self._log_error("Handle TP partial close failed | symbol=%s | result=%s", symbol, result)
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

        self._log_info("Handle TP partial close result | symbol=%s | result=%s", symbol, result)
        return result