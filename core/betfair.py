# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/betfair.py — Cliente para Betfair Exchange API.

⚠️  ADVERTENCIA: Este módulo coloca apuestas REALES con dinero real.
    Cada operación requiere confirmación explícita del usuario en la UI.
    NUNCA llames a place_bet() sin mostrar antes un diálogo de confirmación.

Requisitos:
    - Cuenta Betfair con acceso a la API habilitado
    - App Key (Developer App Key) desde betfair.com/account/myaccount
    - Usuario y contraseña de Betfair

Documentación: https://developer.betfair.com/exchange-api/
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Endpoints ─────────────────────────────────────────────────────────────────

_LOGIN_URL    = "https://identitysso.betfair.com/api/login"
_API_BASE     = "https://api.betfair.com/exchange/betting/json-rpc/v1"
_ACCOUNTS_URL = "https://api.betfair.com/exchange/account/json-rpc/v1"

# Event Type ID de fútbol en Betfair
_SOCCER_EVENT_TYPE_ID = "1"

# Mapa: nuestro pick code → nombres de runner en Betfair (con variantes)
_PICK_TO_RUNNER: dict[str, list[str]] = {
    "1":       ["home", "home team", "local"],
    "X":       ["draw", "the draw", "empate"],
    "2":       ["away", "away team", "visitante"],
    "1X":      [],  # Double Chance market
    "X2":      [],
    "12":      [],
    "OVER2.5": ["over 2.5 goals", "over 2.5", "más de 2.5"],
    "UNDER2.5":["under 2.5 goals", "under 2.5", "menos de 2.5"],
}

_PICK_TO_MARKET_TYPE: dict[str, str] = {
    "1":        "MATCH_ODDS",
    "X":        "MATCH_ODDS",
    "2":        "MATCH_ODDS",
    "1X":       "DOUBLE_CHANCE",
    "X2":       "DOUBLE_CHANCE",
    "12":       "DOUBLE_CHANCE",
    "OVER2.5":  "OVER_UNDER_25",
    "UNDER2.5": "OVER_UNDER_25",
}


# ── Cliente principal ─────────────────────────────────────────────────────────

class BetfairClient:
    """
    Cliente REST para Betfair Exchange.

    Uso típico:
        client = BetfairClient(app_key, username, password)
        ok, msg = client.login()
        markets = client.find_football_market("Arsenal", "Chelsea", "1")
        price   = client.get_best_back_price(markets[0]["market_id"],
                                             markets[0]["selection_id"])
        # ← Mostrar diálogo de confirmación en la UI ANTES de continuar
        result  = client.place_bet(market_id, selection_id, stake=10.0,
                                   min_price=price)
    """

    def __init__(self, app_key: str, username: str, password: str) -> None:
        self.app_key       = app_key.strip()
        self.username      = username.strip()
        self.password      = password
        self.session_token: Optional[str] = None
        self._timeout = 15

    # ── Autenticación ─────────────────────────────────────────────────────────

    def login(self) -> tuple[bool, str]:
        """
        Autentica en Betfair.
        Returns (success, message_for_ui).
        """
        if not self.app_key:
            return False, "App Key vacía. Configura tu Developer App Key."
        if not self.username or not self.password:
            return False, "Usuario o contraseña vacíos."

        try:
            resp = requests.post(
                _LOGIN_URL,
                data={"username": self.username, "password": self.password},
                headers={
                    "X-Application":  self.app_key,
                    "Content-Type":   "application/x-www-form-urlencoded",
                    "Accept":         "application/json",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "SUCCESS":
                self.session_token = data.get("token")
                logger.info("Betfair login OK — user=%s", self.username)
                return True, f"✅  Conectado a Betfair como {self.username}"

            error_code = data.get("error", "UNKNOWN_ERROR")
            msg_map = {
                "INVALID_USERNAME_OR_PASSWORD": "Usuario o contraseña incorrectos.",
                "ACCOUNT_LOCKED":              "Cuenta bloqueada. Contacta a Betfair.",
                "PENDING_AUTH":                "Autenticación pendiente (2FA).",
            }
            return False, f"❌  {msg_map.get(error_code, error_code)}"

        except requests.Timeout:
            return False, "Tiempo de espera agotado. Comprueba tu conexión."
        except Exception as exc:
            logger.warning("Betfair login error: %s", exc)
            return False, f"Error de conexión: {exc}"

    def is_authenticated(self) -> bool:
        return self.session_token is not None

    def get_balance(self) -> Optional[float]:
        """Devuelve el saldo disponible en €. None si hay error."""
        try:
            result = self._api(_ACCOUNTS_URL, "getAccountFunds", {
                "wallet": "UK wallet",
            })
            return float(result.get("availableToBetBalance", 0))
        except Exception:
            return None

    # ── Búsqueda de mercados ──────────────────────────────────────────────────

    def find_football_market(
        self,
        home_team: str,
        away_team: str,
        pick: str,
    ) -> list[dict]:
        """
        Busca mercados de Betfair para el partido.

        Returns lista de dicts:
            [{
                "market_id":    "1.12345678",
                "market_name":  "Match Odds",
                "event_name":   "Arsenal v Chelsea",
                "selection_id":  1234567,
                "runner_name":  "Arsenal",
                "pick":          "1",
            }, ...]

        Lista vacía si no hay mercados o no está autenticado.
        """
        market_type = _PICK_TO_MARKET_TYPE.get(pick, "MATCH_ODDS")

        try:
            # 1. Buscar eventos con el nombre del equipo local
            catalogo = self._api(_API_BASE, "listMarketCatalogue", {
                "filter": {
                    "eventTypeIds":  [_SOCCER_EVENT_TYPE_ID],
                    "marketTypeCodes": [market_type],
                    "textQuery":      home_team[:10],
                },
                "marketProjection": ["RUNNER_DESCRIPTION", "EVENT"],
                "sort":             "FIRST_TO_START",
                "maxResults":       20,
            })

            results: list[dict] = []
            for market in (catalogo or []):
                event_name = market.get("event", {}).get("name", "")
                market_id  = market.get("marketId", "")
                market_name = market.get("marketName", "")
                runners     = market.get("runners", [])

                # Verificar que el visitante también aparece en el nombre del evento
                if away_team.lower()[:6] not in event_name.lower():
                    continue

                # Encontrar el runner que corresponde al pick
                target_runner = self._match_runner(runners, pick, home_team, away_team)
                if target_runner is None:
                    continue

                results.append({
                    "market_id":    market_id,
                    "market_name":  market_name,
                    "event_name":   event_name,
                    "selection_id": target_runner["selectionId"],
                    "runner_name":  target_runner.get("runnerName", ""),
                    "pick":         pick,
                })

            return results

        except Exception as exc:
            logger.warning("find_football_market error: %s", exc)
            return []

    def _match_runner(
        self, runners: list[dict], pick: str,
        home_team: str, away_team: str,
    ) -> Optional[dict]:
        """Selecciona el runner correcto de una lista según el pick."""
        if not runners:
            return None

        if pick in ("1", "OVER2.5"):
            # El primer runner suele ser el equipo local / Over
            # Pero verificamos por nombre
            for r in runners:
                name = r.get("runnerName", "").lower()
                if (home_team.lower()[:5] in name or
                        any(alias in name for alias in _PICK_TO_RUNNER.get(pick, []))):
                    return r
            return runners[0]  # fallback al primero

        if pick == "X":
            for r in runners:
                if "draw" in r.get("runnerName", "").lower():
                    return r
            # El segundo runner suele ser el empate en Match Odds
            return runners[1] if len(runners) > 1 else None

        if pick in ("2", "UNDER2.5"):
            for r in runners:
                name = r.get("runnerName", "").lower()
                if (away_team.lower()[:5] in name or
                        any(alias in name for alias in _PICK_TO_RUNNER.get(pick, []))):
                    return r
            return runners[-1]  # fallback al último

        if pick in ("1X", "X2", "12"):
            # Double Chance: match por nombre del runner
            dc_names = {
                "1X": ["home or draw", "1x", "local or draw"],
                "X2": ["draw or away", "x2"],
                "12": ["home or away", "12"],
            }
            for r in runners:
                rn = r.get("runnerName", "").lower()
                if any(alias in rn for alias in dc_names.get(pick, [])):
                    return r
            return runners[0] if runners else None

        return runners[0]

    # ── Precios ───────────────────────────────────────────────────────────────

    def get_best_back_price(
        self, market_id: str, selection_id: int
    ) -> Optional[float]:
        """
        Devuelve la mejor cuota disponible (lay side) para respaldar una selección.
        None si hay error o no hay liquidez.
        """
        try:
            books = self._api(_API_BASE, "listMarketBook", {
                "marketIds": [market_id],
                "priceProjection": {
                    "priceData":        ["EX_BEST_OFFERS"],
                    "virtualise":       False,
                    "rolloverStakes":   False,
                },
            })
            if not books:
                return None

            for runner in books[0].get("runners", []):
                if runner.get("selectionId") == selection_id:
                    avail = runner.get("ex", {}).get("availableToBack", [])
                    if avail:
                        return float(avail[0]["price"])
            return None

        except Exception as exc:
            logger.warning("get_best_back_price error: %s", exc)
            return None

    def get_market_summary(self, market_id: str) -> Optional[dict]:
        """
        Devuelve estado del mercado: runners con precios back/lay.
        Útil para mostrar en el diálogo de confirmación.
        """
        try:
            books = self._api(_API_BASE, "listMarketBook", {
                "marketIds": [market_id],
                "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
            })
            return books[0] if books else None
        except Exception:
            return None

    # ── Colocación de apuesta ─────────────────────────────────────────────────

    def place_bet(
        self,
        market_id:    str,
        selection_id: int,
        stake:        float,
        min_price:    float,
    ) -> dict:
        """
        ⚠️  COLOCA UNA APUESTA REAL. Solo llamar tras confirmación explícita.

        Parameters
        ----------
        market_id    : ID del mercado Betfair (ej. "1.234567890")
        selection_id : ID del runner (ej. 1234567)
        stake        : Importe a apostar en € (mínimo 2.00)
        min_price    : Cuota mínima aceptable — la apuesta se cancela si el
                       precio cae por debajo de este valor

        Returns
        -------
        dict con campos:
            status       : "EXECUTABLE" | "EXECUTION_COMPLETE" | "EXPIRED"
            bet_id       : str — ID de la apuesta colocada
            size_matched : float — importe emparejado en €
            average_price: float — precio medio de ejecución
            error        : str — mensaje de error si algo fue mal
        """
        if not self.is_authenticated():
            return {"status": "ERROR", "error": "No autenticado — llama a login() primero."}
        if stake < 2.0:
            return {"status": "ERROR", "error": f"Apuesta mínima en Betfair: €2.00 (recibido: €{stake:.2f})"}

        try:
            result = self._api(_API_BASE, "placeOrders", {
                "marketId": market_id,
                "instructions": [{
                    "selectionId": selection_id,
                    "handicap":    0,
                    "side":        "BACK",
                    "orderType":   "LIMIT",
                    "limitOrder": {
                        "size":            round(max(stake, 2.0), 2),
                        "price":           round(min_price, 2),
                        "persistenceType": "LAPSE",
                    },
                }],
                "async": False,
            })

            # Parsear resultado
            if not result or not result.get("instructionReports"):
                return {"status": "ERROR", "error": "Respuesta vacía de Betfair."}

            report = result["instructionReports"][0]
            order  = report.get("placedDate") or {}

            return {
                "status":        report.get("status", "UNKNOWN"),
                "error":         report.get("errorCode", ""),
                "bet_id":        report.get("betId", ""),
                "size_matched":  float(report.get("sizeMatched", 0) or 0),
                "average_price": float(report.get("averagePriceMatched", 0) or 0),
                "size_placed":   float(report.get("sizePlaced", 0) or stake),
            }

        except Exception as exc:
            logger.error("place_bet error market=%s sel=%s: %s", market_id, selection_id, exc)
            return {"status": "ERROR", "error": str(exc)}

    # ── Método interno JSON-RPC ───────────────────────────────────────────────

    def _api(self, url: str, method: str, params: dict) -> list | dict:
        """
        Llamada genérica al JSON-RPC de Betfair.
        Lanza RuntimeError si hay errores de API o autenticación.
        """
        if not self.session_token:
            raise RuntimeError("No autenticado. Llama a login() primero.")

        payload = {
            "jsonrpc": "2.0",
            "method":  f"SportsAPING/v1.0/{method}",
            "params":  params,
            "id":      1,
        }

        resp = requests.post(
            url,
            json=payload,
            headers={
                "X-Application":   self.app_key,
                "X-Authentication": self.session_token,
                "Content-Type":    "application/json",
                "Accept":          "application/json",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"Betfair API error: {err.get('message', err)}")

        return data.get("result", [])
