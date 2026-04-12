import hashlib
import hmac
import json
import time
from typing import Any
from decimal import Decimal, ROUND_DOWN

import requests

from config.config import Settings

class MexcClient:
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