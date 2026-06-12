# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/telegram_bot.py — Telegram Bot interactivo para AlphaBet.

Long-polling sin webhook ni dependencias externas.

Comandos:
  /ping              → test rápido de conectividad
  /start /ayuda      → bienvenida + lista de comandos
  /combinadas        → mejor combinada IA del análisis actual
  /picks             → picks VERDE activos
  /roi               → ROI real del tracker de picks
  /live              → marcadores en tiempo real de picks activos
  /estado            → resumen del último análisis
  /quiniela          → picks de la jornada oficial
  /calendario        → próximos partidos del análisis con hora y pick IA
  /alertas           → alertas proactivas de valor (on/off)
  /notificaciones    → resúmenes automáticos mañana/noche (on/off/config)
  /debug             → estado interno del caché
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from datetime import datetime
from datetime import date as _date
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

_AYUDA_HTML = (
    "🤖 <b>AlphaBet Bot</b>\n"
    "\n"
    "📊 <b>Análisis</b>\n"
    "/picks — Picks 🟢 VERDE activos del análisis\n"
    "/combinadas — Mejor combinada IA del momento\n"
    "/quiniela — Picks de la jornada oficial\n"
    "/calendario — Próximos partidos con hora y pick IA\n"
    "/estado — Resumen del último análisis\n"
    "/live — Marcadores en tiempo real de picks activos\n"
    "\n"
    "📈 <b>Rendimiento</b>\n"
    "/roi — ROI real, P&amp;L y bankroll del tracker\n"
    "/clv — Closing Line Value (tu ventaja real)\n"
    "/riesgo — Protector de banca: estado del stake\n"
    "\n"
    "💰 <b>Apuestas (desde móvil)</b>\n"
    "/apostar — Ver picks activos y guardar en tracker\n"
    "/resultado — Liquidar un pick: /resultado 42 win\n"
    "\n"
    "🔔 <b>Notificaciones</b>\n"
    "/alertas — Alertas de valor en tiempo real (on/off)\n"
    "/notificaciones — Resúmenes automáticos diarios (on/off)\n"
    "\n"
    "⚙️ <b>Sistema</b>\n"
    "/refresh — Actualiza datos desde la app\n"
    "/ayuda — Esta ayuda\n"
    "\n"
    "<i>Ejemplos:\n"
    "  /alertas on 8 — activa alertas con edge ≥ 8%\n"
    "  /resultado 42 win — marca pick #42 como ganado\n"
    "  /notificaciones on 08:30 22:00 — horarios personalizados</i>"
)


# ── Helpers HTML ───────────────────────────────────────────────────────────────

def _esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _b(t) -> str:  return f"<b>{t}</b>"
def _c(t) -> str:  return f"<code>{t}</code>"
def _i(t) -> str:  return f"<i>{t}</i>"


def _combo_reason(combo: dict) -> str:
    """Genera una línea de razonamiento para la combinada."""
    ev       = float(combo.get("ev", 0) or 0)
    avg_edge = float(combo.get("avg_edge", 0) or 0)
    avg_rel  = float(combo.get("avg_reliability", 0) or 0)
    legs     = combo.get("legs", [])

    markets = [l.get("market_type", "1X2") for l in legs]
    if all(m == "goals" for m in markets):
        prefix = "Goles"
    elif "goals" in markets:
        prefix = "Mixta resultado+goles"
    else:
        prefix = "1X2"

    parts: list[str] = []
    if avg_rel >= 70:
        parts.append("alta fiabilidad")
    elif avg_rel >= 50:
        parts.append("fiabilidad media")

    if avg_edge >= 0.08:
        parts.append("ventaja sólida vs mercado")
    elif avg_edge >= 0.03:
        parts.append("ligera ventaja vs mercado")

    if ev >= 0.10:
        parts.append("EV excepcional")
    elif ev >= 0.05:
        parts.append("EV positivo")

    body = " · ".join(parts) if parts else "combinada equilibrada"
    return f"📋 {_i(_esc(prefix + ': ' + body))}"


def _leg_prob_line(leg: dict) -> str:
    """Línea de probabilidades del modelo para un leg (vacía si no hay datos)."""
    market = leg.get("market_type", "1X2")
    if market == "goals":
        p_over = float(leg.get("p_over25", 0) or 0)
        if p_over < 0.01:
            return ""
        return f"   📊 Over2.5 {p_over:.0%} · Under {1 - p_over:.0%}"
    ph  = float(leg.get("p_home", 0) or 0)
    pd_ = float(leg.get("p_draw", 0) or 0)
    pa  = float(leg.get("p_away", 0) or 0)
    if ph + pd_ + pa < 0.01:
        return ""
    return f"   📊 Casa {ph:.0%} · Emp {pd_:.0%} · Vis {pa:.0%}"


# ── Bot ────────────────────────────────────────────────────────────────────────

class TelegramBot:
    """Bot de Telegram con long-polling."""

    def __init__(self, token: str) -> None:
        self.token          = token.strip()
        self._stop_event    = threading.Event()
        self._thread:       Optional[threading.Thread] = None
        self._data_cb:      Optional[Callable[[], dict]] = None
        self._status_cb:    Optional[Callable[[str], None]] = None
        self._refresh_cb:   Optional[Callable[[], None]] = None
        self._storage                    = None   # Storage instance para escrituras
        self._offset:       int = 0
        self.last_error:    str = ""
        self.bot_username:  str = ""

        # ── Callbacks inline (botones) ────────────────────────────────────────
        self._pending_callbacks: dict[str, dict] = {}  # token → pick_data
        self._cb_counter:        int = 0

        self._value_alerts_enabled:  bool  = False
        self._value_edge_threshold:  float = 0.05
        self._value_alerts_chat_id:  Optional[int] = None

        # ── Notificaciones automáticas ────────────────────────────────────────
        self._notif_enabled:     bool          = False
        self._notif_chat_id:     Optional[int] = None
        self._notif_morning:     str           = "09:00"   # HH:MM
        self._notif_evening:     str           = "23:00"   # HH:MM
        self._last_morning_sent: Optional[_date] = None
        self._last_evening_sent: Optional[_date] = None

    # ── Registro de callbacks ─────────────────────────────────────────────────

    def set_data_provider(self, cb: Callable[[], dict]) -> None:
        self._data_cb = cb

    def set_status_callback(self, cb: Callable[[str], None]) -> None:
        """cb(mensaje) se llama desde el hilo del bot para actualizar la UI."""
        self._status_cb = cb

    def set_refresh_callback(self, cb: Callable[[], None]) -> None:
        """cb() pide al hilo principal que actualice el caché de datos."""
        self._refresh_cb = cb

    def set_storage(self, storage) -> None:
        """Inyecta la instancia de Storage para permitir escrituras desde Telegram."""
        self._storage = storage

    def _notify(self, msg: str) -> None:
        logger.info("Bot: %s", msg)
        if self._status_cb:
            try:
                self._status_cb(msg)
            except Exception:
                pass

    # ── Control ───────────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        if not self.token or ":" not in self.token:
            raise ValueError("Token de Telegram inválido — créalo en @BotFather.")
        self._stop_event.clear()
        self.last_error = ""
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="tg-bot-poll"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._notify("Bot detenido.")

    # ── Arranque del hilo ─────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        # 1. Verificar token
        self._notify("Verificando token…")
        if not self._verify_token():
            self._notify("❌ Token inválido. Comprueba el Bot Token en ⚙️ Strategy.")
            return

        # 2. Eliminar webhook (causa más común de que getUpdates no funcione)
        self._notify(f"✓ Bot @{self.bot_username} conectado. Eliminando webhook…")
        self._delete_webhook()
        self._notify("✅ Listo — escuchando comandos. Escríbeme /ping para probar.")

        # 3. Bucle principal
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates(self._offset, timeout=25)
                for upd in updates:
                    try:
                        self._dispatch(upd)
                    except Exception as exc:
                        logger.warning("dispatch error update=%s: %s",
                                       upd.get("update_id"), exc)
                    self._offset = upd["update_id"] + 1
                # Comprobar notificaciones programadas después de cada ciclo
                self._check_scheduled_notifications()
            except Exception as exc:
                self.last_error = str(exc)
                self._notify(f"⚠ Error de conexión: {exc}")
                self._stop_event.wait(5)

    # ── Telegram API helpers ──────────────────────────────────────────────────

    def _verify_token(self) -> bool:
        """Comprueba que el token es válido y guarda el username del bot."""
        try:
            resp = requests.get(
                _API.format(token=self.token, method="getMe"),
                timeout=10,
            )
            data = resp.json()
            if resp.ok and data.get("ok"):
                self.bot_username = data["result"].get("username", "?")
                return True
            self.last_error = data.get("description", "Token inválido")
        except Exception as exc:
            self.last_error = str(exc)
        return False

    def _delete_webhook(self) -> None:
        """Elimina cualquier webhook existente (necesario para que getUpdates funcione)."""
        try:
            resp = requests.post(
                _API.format(token=self.token, method="deleteWebhook"),
                json={"drop_pending_updates": False},
                timeout=10,
            )
            if resp.ok:
                logger.info("Webhook eliminado: %s", resp.json().get("description"))
        except Exception as exc:
            logger.warning("deleteWebhook error: %s", exc)

    def _get_updates(self, offset: int, timeout: int = 25) -> list[dict]:
        try:
            resp = requests.get(
                _API.format(token=self.token, method="getUpdates"),
                params={
                    "offset":          offset,
                    "timeout":         timeout,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=timeout + 5,
            )
            if resp.ok:
                return resp.json().get("result", [])
            # Mostrar el error real de Telegram
            err = resp.json().get("description", f"HTTP {resp.status_code}")
            self._notify(f"⚠ getUpdates: {err}")
        except requests.exceptions.ReadTimeout:
            pass   # normal si no hay mensajes en el periodo
        except Exception as exc:
            raise exc
        return []

    def _send_html(self, chat_id: int, text: str) -> bool:
        """Envía con HTML. Devuelve True si tuvo éxito."""
        try:
            resp = requests.post(
                _API.format(token=self.token, method="sendMessage"),
                json={
                    "chat_id":    chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                },
                timeout=12,
            )
            if resp.ok and resp.json().get("ok"):
                return True

            # Falló con HTML → intentar texto plano
            import re
            plain = re.sub(r"<[^>]+>", "", text)
            resp2 = requests.post(
                _API.format(token=self.token, method="sendMessage"),
                json={"chat_id": chat_id, "text": plain},
                timeout=10,
            )
            if resp2.ok and resp2.json().get("ok"):
                return True

            err = resp.json().get("description", f"HTTP {resp.status_code}")
            self._notify(f"⚠ No se pudo enviar mensaje: {err}")
            return False

        except Exception as exc:
            self._notify(f"⚠ Error al enviar: {exc}")
            return False

    # ── Helpers para botones inline ───────────────────────────────────────────

    def _store_callback(self, data: dict) -> str:
        """Guarda datos de pick para recuperarlos al pulsar un botón. Devuelve token."""
        if len(self._pending_callbacks) >= 100:
            for k in list(self._pending_callbacks.keys())[:20]:
                del self._pending_callbacks[k]
        self._cb_counter = (self._cb_counter + 1) % 99999
        token = str(self._cb_counter)
        self._pending_callbacks[token] = data
        return token

    def _answer_callback(self, callback_query_id: str, text: str = "",
                         show_alert: bool = False) -> None:
        """Confirma un callback_query (quita el spinner del botón)."""
        try:
            requests.post(
                _API.format(token=self.token, method="answerCallbackQuery"),
                json={
                    "callback_query_id": callback_query_id,
                    "text":              text,
                    "show_alert":        show_alert,
                },
                timeout=5,
            )
        except Exception as exc:
            logger.warning("answerCallbackQuery error: %s", exc)

    def _edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        """Reemplaza el texto de un mensaje existente (quita botones también)."""
        try:
            requests.post(
                _API.format(token=self.token, method="editMessageText"),
                json={
                    "chat_id":    chat_id,
                    "message_id": message_id,
                    "text":       text,
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                },
                timeout=8,
            )
        except Exception as exc:
            logger.warning("editMessageText error: %s", exc)

    def _remove_reply_markup(self, chat_id: int, message_id: int) -> None:
        """Elimina los botones de un mensaje sin cambiar su texto."""
        try:
            requests.post(
                _API.format(token=self.token, method="editMessageReplyMarkup"),
                json={
                    "chat_id":      chat_id,
                    "message_id":   message_id,
                    "reply_markup": {},
                },
                timeout=5,
            )
        except Exception as exc:
            logger.warning("editMessageReplyMarkup error: %s", exc)

    def _send_html_kb(self, chat_id: int, text: str,
                      keyboard: list[list[dict]]) -> Optional[int]:
        """Envía mensaje con teclado inline. Devuelve message_id o None."""
        try:
            resp = requests.post(
                _API.format(token=self.token, method="sendMessage"),
                json={
                    "chat_id":      chat_id,
                    "text":         text,
                    "parse_mode":   "HTML",
                    "link_preview_options": {"is_disabled": True},
                    "reply_markup": {"inline_keyboard": keyboard},
                },
                timeout=12,
            )
            if resp.ok and resp.json().get("ok"):
                return resp.json()["result"]["message_id"]
            err = resp.json().get("description", f"HTTP {resp.status_code}")
            logger.warning("_send_html_kb failed: %s", err)
        except Exception as exc:
            logger.warning("_send_html_kb error: %s", exc)
        return None

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def _dispatch(self, upd: dict) -> None:
        # ── Botones inline (callback_query) ───────────────────────────────────
        cbq = upd.get("callback_query")
        if cbq:
            self._handle_callback(cbq)
            return

        msg      = upd.get("message") or upd.get("edited_message") or {}
        raw_txt  = (msg.get("text") or "").strip()
        chat_id  = msg.get("chat", {}).get("id")
        chat_type = msg.get("chat", {}).get("type", "private")  # private/group/supergroup

        if not chat_id or not raw_txt.startswith("/"):
            return

        # ── Extraer el comando y destinatario ─────────────────────────────────
        # En grupos los comandos pueden venir como /comando@nombrelbot
        cmd_full = raw_txt.split()[0].lower()           # "/picks@mifootballbot"
        at_pos   = cmd_full.find("@")

        if at_pos != -1:
            target_bot = cmd_full[at_pos + 1:]          # "mifootballbot"
            cmd        = cmd_full[:at_pos]               # "/picks"
            # Si el comando va dirigido a otro bot, ignorarlo
            if (self.bot_username and
                    target_bot.lower() != self.bot_username.lower()):
                logger.debug(
                    "Ignorando comando %s dirigido a @%s (somos @%s)",
                    cmd_full, target_bot, self.bot_username,
                )
                return
        else:
            cmd = cmd_full                               # "/picks" sin @

        self._notify(
            f"Comando: {cmd}  chat_id={chat_id}  tipo={chat_type}"
        )

        # Comandos con argumentos (manejan su propio parsing)
        if cmd == "/alertas":
            parts = raw_txt.split()
            args  = parts[1:]
            self._cmd_alertas(int(chat_id), args)
            return

        if cmd == "/notificaciones":
            parts = raw_txt.split()
            args  = parts[1:]
            self._cmd_notificaciones(int(chat_id), args)
            return

        if cmd == "/apostar":
            parts = raw_txt.split()
            args  = parts[1:]
            self._cmd_apostar(int(chat_id), args)
            return

        if cmd == "/resultado":
            parts = raw_txt.split()
            args  = parts[1:]
            self._cmd_resultado(int(chat_id), args)
            return

        handlers: dict[str, Callable[[int], None]] = {
            "/refresh":     self._cmd_refresh,
            "/start":       self._cmd_ayuda,
            "/ayuda":       self._cmd_ayuda,
            "/combinadas":  self._cmd_combinadas,
            "/picks":       self._cmd_picks,
            "/roi":         self._cmd_roi,
            "/clv":         self._cmd_clv,
            "/riesgo":      self._cmd_riesgo,
            "/live":        self._cmd_live,
            "/estado":      self._cmd_estado,
            "/quiniela":    self._cmd_quiniela,
            "/calendario":  self._cmd_calendario,
        }

        fn = handlers.get(cmd)
        if fn:
            fn(int(chat_id))
        else:
            self._send_html(
                int(chat_id),
                f"Comando no reconocido: {_c(_esc(cmd))}\n"
                "Usa /ayuda para ver los comandos disponibles.",
            )

    # ── Comandos ──────────────────────────────────────────────────────────────

    def _get_data(self) -> dict:
        try:
            return self._data_cb() if self._data_cb else {}
        except Exception as exc:
            logger.warning("data provider error: %s", exc)
            return {}

    def _cmd_ping(self, chat_id: int) -> None:
        ok = self._send_html(chat_id, "🏓 Pong! Bot activo y recibiendo comandos.")
        self._notify("✓ /ping respondido" if ok else "✗ /ping falló al enviar")

    def _cmd_refresh(self, chat_id: int) -> None:
        """Solicita al hilo principal que actualice el caché y confirma."""
        if self._refresh_cb:
            try:
                self._refresh_cb()
                # Esperar brevemente a que el hilo principal ejecute la actualización
                import time
                time.sleep(0.6)
                self._send_html(
                    chat_id,
                    "🔄 <b>Caché actualizado.</b>\n"
                    "Ahora prueba /combinadas, /picks o /quiniela.",
                )
                self._notify("✓ /refresh ejecutado")
            except Exception as exc:
                self._send_html(chat_id, f"⚠ Error al refrescar: {_esc(str(exc))}")
        else:
            self._send_html(
                chat_id,
                "⚠ No hay callback de refresco configurado.\n"
                "Reinicia el bot desde la app.",
            )

    def _cmd_ayuda(self, chat_id: int) -> None:
        self._send_html(chat_id, _AYUDA_HTML)

    def _cmd_combinadas(self, chat_id: int) -> None:
        data       = self._get_data()
        bot_combos = data.get("bot_combos", [])

        # Fallback al combo del Portfolio Builder si no hay combinadas IA
        if not bot_combos:
            snap = data.get("combo_snapshot")
            if snap and snap.get("legs"):
                bot_combos = [{
                    "label":         "Combinada",
                    "n_legs":        len(snap["legs"]),
                    "combined_odds": snap.get("total_odds", 0),
                    "combined_prob": 0,
                    "ev":            0,
                    "legs":          snap["legs"],
                }]

        if not bot_combos:
            self._send_html(
                chat_id,
                "⚠️ <b>Sin combinadas disponibles.</b>\n\n"
                "Pasos:\n"
                "1. Pulsa ▶ Run Analysis en la app\n"
                "2. Ve a ⚡ Combinadas IA y pulsa Generar\n"
                "3. Escribe /refresh aquí\n"
                "4. Prueba /combinadas de nuevo",
            )
            return

        risk_icons = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
        out_lines: list[str] = []

        for combo in bot_combos[:3]:          # máximo 3 combinadas
            label    = _esc(combo.get("label", ""))
            n_legs   = combo.get("n_legs", 0)
            c_odds   = float(combo.get("combined_odds", 0) or 0)
            c_prob   = float(combo.get("combined_prob", 0) or 0)
            ev       = float(combo.get("ev", 0) or 0)
            avg_rel  = float(combo.get("avg_reliability", 0) or 0)

            out_lines.append(
                f"{'─'*22}\n"
                f"⚽ {_b(label)} · {n_legs} patas\n"
                f"🎯 Cuota: {_c(f'{c_odds:.2f}')}  "
                f"P(acierto): {_c(f'{c_prob:.1%}')}  "
                f"EV: {_c(f'{ev:+.1%}')}\n"
                f"{_combo_reason(combo)}\n"
            )

            for i, leg in enumerate(combo.get("legs", []), 1):
                icon      = risk_icons.get(leg.get("risk", ""), "⚪")
                odds_str  = f"{float(leg.get('odds', 0)):.2f}"
                edge      = float(leg.get("edge", 0) or 0)
                rel       = int(leg.get("reliability", 0) or 0)
                prob_line = _leg_prob_line(leg)
                leg_text  = (
                    f"{i}. {_b(_esc(leg.get('match', '?')))}\n"
                    f"   {icon} {_b(_esc(leg.get('pick', '?')))} @ {_c(odds_str)}"
                    f"  Edge {_c(f'{edge:+.1%}')}"
                    f"  Fiab {_c(f'{rel}/99')}"
                )
                if prob_line:
                    leg_text += f"\n{prob_line}"
                out_lines.append(leg_text)
            out_lines.append("")

        self._send_html(chat_id, "\n".join(out_lines))

    def _cmd_picks(self, chat_id: int) -> None:
        data  = self._get_data()
        picks = data.get("results_green", [])

        if not picks:
            self._send_html(
                chat_id,
                "⚠️ <b>Sin picks VERDE disponibles.</b>\n"
                "Ejecuta el análisis en la app.",
            )
            return

        shown = picks[:12]
        lines = [f"🟢 {_b('PICKS VERDE')} · {len(picks)} picks activos\n"]

        for p in shown:
            odds  = float(p.get("odds", 0) or 0)
            edge  = float(p.get("edge", 0) or 0)
            ev    = float(p.get("ev", 0) or 0)
            rel   = int(p.get("reliability_score", 0) or 0)
            home  = _esc(p.get("home_team", "?"))
            away  = _esc(p.get("away_team", "?"))
            pick  = _esc(p.get("pick", "?"))
            lines.append(
                f"• {_b(f'{home} vs {away}')}\n"
                f"  {pick} @ {_c(f'{odds:.2f}')}  "
                f"Edge {_c(f'{edge:+.1%}')}  "
                f"EV {_c(f'{ev:+.1%}')}  "
                f"Fiab {_c(f'{rel}/99')}"
            )

        if len(picks) > 12:
            lines.append(f"\n{_i(f'… y {len(picks)-12} más en la app')}")
        self._send_html(chat_id, "\n".join(lines))

    def _cmd_estado(self, chat_id: int) -> None:
        data = self._get_data()
        bt   = data.get("backtest_summary", {})
        ts   = _esc(data.get("last_analysis", "—"))
        n_t  = data.get("n_total", 0)
        n_p  = data.get("n_picks", 0)

        if not bt:
            self._send_html(
                chat_id,
                "ℹ️ <b>No se ha ejecutado ningún análisis todavía.</b>\n"
                "Pulsa ▶ Run Analysis en la app.",
            )
            return

        lines = [f"📊 {_b('ESTADO DEL ANÁLISIS')}", f"⏱ {_c(ts)}", ""]
        for div, d in bt.items():
            pure_tag = "✓ puro" if d.get("pure_wf") else "pseudo-OOS"
            roi  = d.get("roi", 0)
            std  = d.get("roi_std", 0)
            lines.append(
                f"• {_b(_esc(div))} ({_i(pure_tag)})\n"
                f"  ROI {_c(f'{roi:+.1%}')}  "
                f"σ={_c(f'{std:.1%}')}  "
                f"· {d.get('bets', 0)} apuestas"
            )

        lines += [
            "",
            f"🔭 Fixtures totales: {_c(str(n_t))}",
            f"🎯 Picks VERDE activos: {_c(str(n_p))}",
        ]
        self._send_html(chat_id, "\n".join(lines))

    def _cmd_quiniela(self, chat_id: int) -> None:
        data = self._get_data()
        rows = data.get("quiniela_picks", [])
        info = data.get("quiniela_info", {})

        if not rows:
            self._send_html(
                chat_id,
                "⚠️ <b>Quiniela no cargada.</b>\n"
                "Ve a ⚽ Quiniela IA → 📋 Cargar Jornada Oficial.",
            )
            return

        src_icons = {"ml": "🤖", "odds_api": "📈", "elo": "📡", "claude": "🧠"}
        jornada   = _esc(info.get("jornada", "?"))
        fecha     = _esc(info.get("fecha", ""))
        header    = f"⚽ {_b('QUINIELA IA')} · Jornada {jornada}"
        if fecha:
            header += f" · {fecha}"
        lines     = [header + "\n"]

        for r in rows:
            icon = src_icons.get(r.get("p_source"), "❓")
            num  = str(r.get("num", "?")).rjust(2)
            home = _esc(str(r.get("home", "?"))[:18])
            away = _esc(str(r.get("away", "?"))[:18])
            pick = _b(_esc(r.get("pick", "?")))
            lines.append(f"{num}. {home} — {away}  {pick} {icon}")

        # ── Resumen ────────────────────────────────────────────────────────────
        pick_counts = Counter(r.get("pick", "") for r in rows)
        src_counts  = Counter(r.get("p_source", "") for r in rows if r.get("p_source"))

        ones    = pick_counts.get("1", 0)
        draws   = pick_counts.get("X", 0)
        twos    = pick_counts.get("2", 0)
        doubles = sum(pick_counts.get(k, 0) for k in ["1X", "X2", "12"])
        triples = pick_counts.get("1X2", 0)
        dist_parts: list[str] = []
        if ones:    dist_parts.append(f"1→{ones}")
        if draws:   dist_parts.append(f"X→{draws}")
        if twos:    dist_parts.append(f"2→{twos}")
        if doubles: dist_parts.append(f"Dobles→{doubles}")
        if triples: dist_parts.append(f"Triples→{triples}")

        _src_lbl = {"ml": "ML🤖", "odds_api": "Odds📈", "elo": "ELO📡",
                    "club_elo": "ClubELO📡", "claude": "IA🧠"}
        src_parts = [f"{_src_lbl.get(s, _esc(s))}×{n}" for s, n in src_counts.most_common()]

        favoritos = equilibrados = coberturas = 0
        for r in rows:
            pick = r.get("pick", "1")
            ph   = float(r.get("p_home", 0) or 0)
            pd_  = float(r.get("p_draw", 0) or 0)
            pa   = float(r.get("p_away", 0) or 0)
            if pick in ("1X", "X2", "12", "1X2"):
                coberturas += 1
            elif ph + pd_ + pa < 0.01:
                equilibrados += 1
            else:
                p_max = max(ph, pd_, pa)
                if p_max >= 0.55:
                    favoritos += 1
                elif p_max >= 0.40:
                    equilibrados += 1
                else:
                    coberturas += 1

        conf_parts: list[str] = []
        if favoritos:    conf_parts.append(f"{favoritos} favoritos")
        if equilibrados: conf_parts.append(f"{equilibrados} equilibrados")
        if coberturas:   conf_parts.append(f"{coberturas} coberturas")

        lines.append("")
        lines.append("─" * 14)
        if dist_parts:
            lines.append("📊 " + " · ".join(dist_parts))
        if src_parts:
            lines.append("🔬 " + " · ".join(src_parts))
        if conf_parts:
            lines.append("💡 " + " · ".join(conf_parts))

        # ── Stats finales ───────────────────────────────────────────────────────
        coste = info.get("coste", "?")
        prob  = info.get("prob", "?")
        combs = info.get("combinaciones", "?")
        lines += [
            "",
            f"💶 {_c(str(combs))} combinaciones · Coste: {_c(f'{coste} €')}",
            f"🎰 P(pleno): {_c(str(prob))}",
        ]
        self._send_html(chat_id, "\n".join(lines))

    def _cmd_calendario(self, chat_id: int) -> None:
        """
        /calendario — Próximos partidos del análisis con fecha, hora y pick IA.

        Muestra los fixtures futuros agrupados por fecha (máximo 7 días,
        máximo 20 partidos en total para no saturar el chat).
        Incluye hora, liga, pick IA, cuotas, probabilidades y edge.
        """
        data     = self._get_data()
        fixtures = data.get("upcoming_fixtures", [])

        if not fixtures:
            self._send_html(
                chat_id,
                "📅 <b>Calendario vacío.</b>\n\n"
                "Aún no hay fixtures próximos del análisis.\n"
                "Pasos:\n"
                "1. Pulsa ▶ Run Analysis en la app\n"
                "2. Escribe /refresh aquí\n"
                "3. Prueba /calendario de nuevo",
            )
            return

        # ── Agrupar por fecha ──────────────────────────────────────────────────
        from collections import defaultdict as _dd
        by_date: dict[str, list[dict]] = _dd(list)
        for f in fixtures:
            d = str(f.get("date", ""))[:10]
            if d:
                by_date[d].append(f)

        # Ordenar fechas y limitar a 7 días y 20 partidos
        sorted_dates = sorted(by_date.keys())[:7]
        risk_icon = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴", "CLAUDE": "🧠"}

        lines: list[str] = [f"📅 {_b('CALENDARIO DE ANÁLISIS')}\n"]
        total_shown = 0

        for d in sorted_dates:
            if total_shown >= 20:
                break

            # Cabecera de fecha
            try:
                from datetime import datetime as _dt
                dt_obj = _dt.strptime(d, "%Y-%m-%d")
                day_names = [
                    "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom",
                ]
                day_name  = day_names[dt_obj.weekday()]
                fecha_str = f"{day_name} {dt_obj.day}/{dt_obj.month:02d}"
            except Exception:
                fecha_str = d

            lines.append(f"📆 {_b(_esc(fecha_str))}")

            for f in by_date[d]:
                if total_shown >= 20:
                    break

                home   = _esc(str(f.get("home_team", "?"))[:18])
                away   = _esc(str(f.get("away_team", "?"))[:18])
                pick   = _esc(str(f.get("pick", "?")))
                liga   = _esc(str(f.get("league", ""))[:10])
                hora   = str(f.get("time", ""))
                odds   = f.get("odds")
                p_h    = float(f.get("p_home", 0) or 0)
                p_d    = float(f.get("p_draw", 0) or 0)
                p_a    = float(f.get("p_away", 0) or 0)
                edge   = float(f.get("edge", 0) or 0)
                risk   = str(f.get("risk_light", ""))
                r_icon = risk_icon.get(risk, "⚪")

                hora_str  = f"🕐{hora}  " if hora else ""
                odds_str  = f" @ {_c(f'{float(odds):.2f}')}" if odds else ""
                edge_str  = f"  edge {_c(f'{edge*100:+.1f}%')}" if edge else ""
                probs_str = (
                    f"   📊 1:{p_h:.0%} X:{p_d:.0%} 2:{p_a:.0%}"
                    if (p_h + p_d + p_a) > 0.01 else ""
                )

                lines.append(
                    f"  {hora_str}{r_icon} {_b(f'{home} vs {away}')}"
                    f"\n    {liga}  {_b(pick)}{odds_str}{edge_str}"
                )
                if probs_str:
                    lines.append(probs_str)

                total_shown += 1

            lines.append("")   # espacio entre días

        # Nota al pie si se truncó
        total_fixtures = len(fixtures)
        if total_shown < total_fixtures:
            lines.append(
                _i(f"Mostrando {total_shown} de {total_fixtures} partidos. "
                   "Ver todos en 📅 Calendario de la app.")
            )
        else:
            lines.append(_i(f"Total: {total_shown} partido{'s' if total_shown != 1 else ''}."))

        self._send_html(chat_id, "\n".join(lines))

    def _cmd_debug(self, chat_id: int) -> None:
        data       = self._get_data()
        n_picks    = data.get("n_picks", 0)
        n_total    = data.get("n_total", 0)
        n_quiniela = len(data.get("quiniela_picks", []))
        last_ts    = _esc(data.get("last_analysis", "—"))
        bt_divs    = list(data.get("backtest_summary", {}).keys())
        bot_combos = data.get("bot_combos", [])
        n_combos   = len(bot_combos)
        combo_snap = data.get("combo_snapshot")

        lines = [
            f"🔧 {_b('DEBUG — estado del caché')}",
            "",
            f"Último análisis: {_c(last_ts)}",
            f"Fixtures totales: {_c(str(n_total))}",
            f"Picks VERDE: {_c(str(n_picks))}",
            f"Combinadas IA: {_c(str(n_combos) + ' disponibles') if n_combos else '❌ ninguna'}",
            f"Combo Portfolio: {'✅' if combo_snap and combo_snap.get('legs') else '❌'}",
            f"Ligas backtest: {_c(_esc(str(bt_divs)) if bt_divs else 'ninguna')}",
            f"Quiniela: {_c(str(n_quiniela) + ' partidos') if n_quiniela else _c('no cargada')}",
            "",
            _i("Si combinadas = 0 → ve a ⚡ Combinadas IA y pulsa Generar, luego /refresh"),
        ]
        self._send_html(chat_id, "\n".join(lines))

    def _cmd_roi(self, chat_id: int) -> None:
        """ROI real del tracker de picks (picks liquidados en storage)."""
        data        = self._get_data()
        all_picks   = data.get("all_picks", [])

        if not all_picks:
            self._send_html(
                chat_id,
                "⚠️ <b>Sin picks en el tracker.</b>\n"
                "Ve a 📋 Resultados en la app y guarda algunos picks primero.",
            )
            return

        settled  = [p for p in all_picks if p.get("status") in ("WIN", "LOSS")]
        wins     = [p for p in settled if p.get("status") == "WIN"]
        losses   = [p for p in settled if p.get("status") == "LOSS"]
        pending  = [p for p in all_picks if p.get("status") == "PENDING"]

        hit_rate = len(wins) / len(settled) * 100 if settled else 0.0
        total_pnl_units = sum(float(p.get("pnl") or 0) for p in settled)

        # P&L en euros si hay bankroll configurado
        bankroll = float(data.get("bankroll_eur", 0) or 0)
        if bankroll > 0:
            pnl_str = f"{total_pnl_units * bankroll:+.2f}€"
        else:
            pnl_str = f"{total_pnl_units:+.4f}u"

        total_risk = sum(
            float(p.get("bankroll_pct") or 0) / 100.0
            for p in settled if p.get("bankroll_pct") is not None
        )
        roi = (total_pnl_units / total_risk * 100) if total_risk > 0 else 0.0

        # CLV medio
        clv_vals = [float(p["clv"]) for p in all_picks if p.get("clv") is not None]
        clv_line = ""
        if clv_vals:
            clv_avg = sum(clv_vals) / len(clv_vals)
            clv_pos = sum(1 for v in clv_vals if v > 0) / len(clv_vals) * 100
            sign    = "+" if clv_avg >= 0 else ""
            clv_line = (
                f"\n📐 CLV medio: {_c(f'{sign}{clv_avg*100:.2f}%')}  "
                f"Picks CLV+: {_c(f'{clv_pos:.0f}%')}"
            )

        roi_icon = "📈" if roi >= 0 else "📉"
        lines = [
            f"📊 {_b('ROI REAL DEL TRACKER')}\n",
            f"🎯 Picks guardados: {_c(str(len(all_picks)))}",
            f"✅ WIN: {_c(str(len(wins)))}  "
            f"❌ LOSS: {_c(str(len(losses)))}  "
            f"⏳ PEND: {_c(str(len(pending)))}",
            f"🎲 Tasa de acierto: {_c(f'{hit_rate:.1f}%')}",
            f"{roi_icon} ROI real: {_c(f'{roi:+.2f}%')}",
            f"💶 P&L total: {_c(pnl_str)}",
            (f"🏦 Bankroll: {_c(f'{bankroll:.0f}€')}" if bankroll > 0 else ""),
            clv_line,
        ]
        self._send_html(chat_id, "\n".join(l for l in lines if l))

    def _cmd_clv(self, chat_id: int) -> None:
        """Closing Line Value — la métrica que valida si tienes ventaja real."""
        if not self._storage:
            self._send_html(chat_id, "⚠️ Sin acceso a la base de datos.")
            return
        try:
            picks = self._storage.load_model_picks(limit=500)
        except Exception:
            picks = []
        clv_vals = [float(p["clv"]) for p in picks if p.get("clv") is not None]
        if not clv_vals:
            self._send_html(
                chat_id,
                "📐 <b>CLV (Closing Line Value)</b>\n\n"
                "Aún no hay CLV registrado.\n"
                "Se captura solo al obtener la cuota de cierre de tus picks "
                "(análisis con The Odds API activada).",
            )
            return
        avg  = sum(clv_vals) / len(clv_vals)
        pos  = sum(1 for v in clv_vals if v > 0) / len(clv_vals) * 100
        icon = "📈" if avg >= 0 else "📉"
        sign = "+" if avg >= 0 else ""
        verdict = ("✅ Bates al mercado — señal de ventaja real."
                   if avg > 0 else
                   "⚠️ Por debajo del cierre — revisa el momento de entrada.")
        self._send_html(
            chat_id,
            f"{icon} <b>CLV (Closing Line Value)</b>\n\n"
            f"Medio: {_c(f'{sign}{avg*100:.2f}%')}\n"
            f"Picks CLV+: {_c(f'{pos:.0f}%')}  ({len(clv_vals)} con dato)\n"
            f"Mejor: {_c(f'{max(clv_vals)*100:+.1f}%')}  "
            f"Peor: {_c(f'{min(clv_vals)*100:+.1f}%')}\n\n"
            f"<i>{verdict}</i>",
        )

    def _cmd_riesgo(self, chat_id: int) -> None:
        """Estado del protector de banca (circuit breaker): ¿debo apostar ahora?"""
        if not self._storage:
            self._send_html(chat_id, "⚠️ Sin acceso a la base de datos.")
            return
        try:
            picks = self._storage.load_model_picks(limit=200)   # id DESC
        except Exception:
            picks = []
        # Orden cronológico (antiguo→reciente) para racha y drawdown correctos
        settled_pnl = [
            float(p["pnl"]) for p in reversed(picks)
            if p.get("status") in ("WIN", "LOSS") and p.get("pnl") is not None
        ]
        bankroll = float(self._get_data().get("bankroll_eur", 0) or 0)
        try:
            from .risk_guard import compute_risk_state
            st = compute_risk_state(settled_pnl, bankroll)
        except Exception as exc:
            self._send_html(chat_id, f"⚠️ No se pudo calcular el riesgo: {_esc(str(exc))}")
            return
        icon = {"NORMAL": "🟢", "REDUCED": "🟡", "PAUSED": "🔴"}.get(st.mode, "⚪")
        mode_txt = {
            "NORMAL":  "NORMAL — stake completo",
            "REDUCED": "REDUCIDO — stake a la mitad",
            "PAUSED":  "EN PAUSA — no apostar",
        }.get(st.mode, st.mode)
        dd_txt = f"{st.drawdown_pct*100:.0f}%" if bankroll > 0 else "n/d (sin bankroll)"
        self._send_html(
            chat_id,
            f"{icon} <b>Protector de banca</b>\n\n"
            f"Estado: {_b(mode_txt)}\n"
            f"Multiplicador de stake: {_c(f'×{st.multiplier:g}')}\n"
            f"Racha de pérdidas: {_c(str(st.loss_streak))}\n"
            f"Drawdown: {_c(dd_txt)}\n\n"
            f"<i>{_esc(st.reason)}</i>",
        )

    def _cmd_live(self, chat_id: int) -> None:
        """Marcadores en tiempo real de picks PENDING activos."""
        from .auto_settler import (
            _DIV_TO_ESPN, _FALLBACK_ORDER, _get, _team_match, pick_is_win,
        )
        data    = self._get_data()
        picks   = data.get("today_picks", [])

        if not picks:
            self._send_html(
                chat_id,
                "ℹ️ <b>Sin picks PENDING para hoy.</b>\n"
                "Guarda picks en 📋 Resultados antes de ejecutar /live.",
            )
            return

        today_str = datetime.now().strftime("%Y%m%d")
        _ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

        # Cargar eventos ESPN del día (todas las ligas conocidas)
        all_events: list[dict] = []
        seen_leagues: set[str] = set()
        for p in picks:
            lg = str(p.get("league", ""))
            espn_id = _DIV_TO_ESPN.get(lg)
            if espn_id and espn_id not in seen_leagues:
                seen_leagues.add(espn_id)
                url  = f"{_ESPN_BASE}/{espn_id}/scoreboard"
                data_e = _get(url, {"dates": today_str})
                all_events.extend(data_e.get("events", []))

        # Fallback: si no se encontró nada, consultar las ligas top
        if not all_events:
            for eid in _FALLBACK_ORDER[:5]:
                url  = f"{_ESPN_BASE}/{eid}/scoreboard"
                data_e = _get(url, {"dates": today_str})
                all_events.extend(data_e.get("events", []))

        lines = [f"🟢 {_b('LIVE SCORES')} · {len(picks)} picks activos\n"]
        found = 0

        for p in picks:
            home     = str(p.get("home_team", ""))
            away     = str(p.get("away_team", ""))
            pick_val = str(p.get("pick", ""))
            odds     = p.get("odds")

            # Buscar el partido en los eventos ESPN
            match_info = None
            for ev in all_events:
                comps = ev.get("competitions", [])
                if not comps:
                    continue
                comp = comps[0]
                competitors = comp.get("competitors", [])
                hc = next((c for c in competitors if c.get("homeAway") == "home"), None)
                ac = next((c for c in competitors if c.get("homeAway") == "away"), None)
                if not hc or not ac:
                    continue
                hn = hc.get("team", {}).get("displayName", "")
                an = ac.get("team", {}).get("displayName", "")
                if _team_match(home, hn) and _team_match(away, an):
                    try:
                        hg = int(hc.get("score", "") or 0)
                        ag = int(ac.get("score", "") or 0)
                    except (ValueError, TypeError):
                        hg = ag = 0
                    status_type = comp.get("status", {}).get("type", {})
                    display     = status_type.get("shortDetail", "")
                    completed   = status_type.get("completed", False)
                    state_name  = status_type.get("name", "")
                    match_info  = {
                        "home_goals": hg, "away_goals": ag,
                        "display": display, "completed": completed,
                        "result": "H" if hg > ag else ("D" if hg == ag else "A"),
                    }
                    break

            odds_str = f"@ {_c(f'{float(odds):.2f}')}" if odds else ""
            home_s   = _esc(home[:18])
            away_s   = _esc(away[:18])

            if match_info:
                found += 1
                hg, ag = match_info["home_goals"], match_info["away_goals"]
                score  = f"{hg}–{ag}"
                label  = _esc(match_info["display"] or ("FT" if match_info["completed"] else ""))
                win    = pick_is_win(pick_val, match_info)
                result_icon = (
                    "✅" if win is True else
                    "❌" if win is False else "➖"
                )
                if match_info["completed"]:
                    label = f"FT {score}"
                lines.append(
                    f"• {_b(f'{home_s} vs {away_s}')}\n"
                    f"  {_b(pick_val)} {odds_str} · {_c(score)} {_i(label)} {result_icon}"
                )
            else:
                lines.append(
                    f"• {_b(f'{home_s} vs {away_s}')}\n"
                    f"  {_b(pick_val)} {odds_str} · {_i('Sin datos ESPN')}"
                )

        if found == 0:
            lines.append(
                f"\n{_i('No se encontraron partidos en directo. '
                        'Puede que aún no hayan empezado.')}"
            )

        self._send_html(chat_id, "\n".join(lines))

    # ── Notificaciones automáticas ─────────────────────────────────────────────

    def _check_scheduled_notifications(self) -> None:
        """
        Comprueba si toca enviar el resumen matutino o nocturno.
        Llamado después de cada ciclo de long-polling (~25 s).
        """
        if not self._notif_enabled or self._notif_chat_id is None:
            return

        now   = datetime.now()
        today = now.date()
        hm    = now.strftime("%H:%M")

        # Margen de ±2 minutos para no perder la ventana
        def _in_window(target: str) -> bool:
            try:
                th, tm = map(int, target.split(":"))
                diff = abs(now.hour * 60 + now.minute - (th * 60 + tm))
                return diff <= 2
            except Exception:
                return False

        if _in_window(self._notif_morning) and self._last_morning_sent != today:
            self._last_morning_sent = today
            try:
                self._send_morning_summary(self._notif_chat_id)
            except Exception as exc:
                logger.warning("morning summary error: %s", exc)

        if _in_window(self._notif_evening) and self._last_evening_sent != today:
            self._last_evening_sent = today
            try:
                self._send_evening_summary(self._notif_chat_id)
            except Exception as exc:
                logger.warning("evening summary error: %s", exc)

    def _send_morning_summary(self, chat_id: int) -> None:
        """Resumen matutino: picks activos para hoy."""
        data        = self._get_data()
        today_picks = data.get("today_picks", [])
        last_ts     = _esc(data.get("last_analysis", "—"))

        fecha = datetime.now().strftime("%A %d/%m").capitalize()

        if not today_picks:
            self._send_html(
                chat_id,
                f"🌅 <b>Buenos días</b> · {_esc(fecha)}\n\n"
                f"Sin picks activos para hoy.\n"
                f"Último análisis: {_c(last_ts)}\n\n"
                f"{_i('Pulsa ▶ Run Analysis en la app para buscar nuevas oportunidades.')}",
            )
            return

        lines = [
            f"🌅 <b>Buenos días</b> · {_esc(fecha)}",
            f"Tienes <b>{len(today_picks)}</b> pick{'s' if len(today_picks) != 1 else ''} para hoy:\n",
        ]
        for p in today_picks:
            home  = _esc(str(p.get("home_team", ""))[:20])
            away  = _esc(str(p.get("away_team", ""))[:20])
            pick  = _esc(str(p.get("pick", "")))
            odds  = p.get("odds")
            edge  = p.get("edge")
            odds_s = f" @ {_c(f'{float(odds):.2f}')}" if odds else ""
            edge_s = f"  Edge {_c(f'{float(edge)*100:+.1f}%')}" if edge else ""
            lines.append(f"• {_b(f'{home} vs {away}')}\n  {_b(pick)}{odds_s}{edge_s}")

        lines += [
            "",
            f"{_i('Usa /live para marcadores en tiempo real · /picks para todos los picks')}",
        ]
        self._send_html(chat_id, "\n".join(lines))

    def _send_evening_summary(self, chat_id: int) -> None:
        """Resumen nocturno: resultados de picks liquidados hoy."""
        data           = self._get_data()
        today_results  = data.get("today_results", [])
        today_picks    = data.get("today_picks", [])   # aún pendientes

        fecha = datetime.now().strftime("%A %d/%m").capitalize()

        if not today_results and not today_picks:
            self._send_html(
                chat_id,
                f"🌙 <b>Buenas noches</b> · {_esc(fecha)}\n\n"
                f"{_i('No hubo picks activos hoy.')}",
            )
            return

        wins   = [p for p in today_results if p.get("status") == "WIN"]
        losses = [p for p in today_results if p.get("status") == "LOSS"]

        # P&L del día
        bankroll  = float(data.get("bankroll_eur", 0) or 0)
        day_pnl_u = sum(float(p.get("pnl") or 0) for p in today_results)
        if bankroll > 0:
            pnl_str = f"{day_pnl_u * bankroll:+.2f}€"
        else:
            pnl_str = f"{day_pnl_u:+.4f}u"

        pnl_icon = "📈" if day_pnl_u >= 0 else "📉"

        lines = [
            f"🌙 <b>Resumen del día</b> · {_esc(fecha)}\n",
        ]

        for p in today_results:
            home  = _esc(str(p.get("home_team", ""))[:18])
            away  = _esc(str(p.get("away_team", ""))[:18])
            pick  = _esc(str(p.get("pick", "")))
            pnl   = float(p.get("pnl") or 0)
            icon  = "✅" if p.get("status") == "WIN" else "❌"
            p_str = (
                f"{pnl * bankroll:+.2f}€" if bankroll > 0
                else f"{pnl:+.4f}u"
            )
            lines.append(
                f"{icon} {_b(f'{home} vs {away}')}\n"
                f"   {_b(pick)} · {_c(p_str)}"
            )

        if today_picks:
            lines.append(
                f"\n⏳ {len(today_picks)} pick{'s' if len(today_picks) != 1 else ''} "
                f"sin liquidar (usa /live o 📋 Resultados en la app)"
            )

        if today_results:
            lines += [
                "",
                f"{'─'*14}",
                f"✅ {len(wins)} WIN  ❌ {len(losses)} LOSS",
                f"{pnl_icon} P&L del día: {_b(_c(pnl_str))}",
            ]

        self._send_html(chat_id, "\n".join(lines))

    def _cmd_notificaciones(self, chat_id: int, args: list[str]) -> None:
        """
        Configura los resúmenes automáticos diarios.

        Uso:
          /notificaciones              → muestra estado actual
          /notificaciones on           → activa con horarios por defecto (09:00 y 23:00)
          /notificaciones on 08:30 22:00 → activa con horarios personalizados
          /notificaciones off          → desactiva
          /notificaciones ahora        → envía el resumen matutino/nocturno inmediatamente (test)
        """
        if not args:
            # Mostrar estado
            estado = "🔔 <b>activadas</b>" if self._notif_enabled else "🔕 <b>desactivadas</b>"
            self._send_html(
                chat_id,
                f"📅 Notificaciones automáticas: {estado}\n"
                f"🌅 Resumen matutino: {_c(self._notif_morning)}\n"
                f"🌙 Resumen nocturno: {_c(self._notif_evening)}\n\n"
                "Uso:\n"
                "  /notificaciones on — activa (09:00 y 23:00)\n"
                "  /notificaciones on 08:30 22:00 — horarios propios\n"
                "  /notificaciones off — desactiva\n"
                "  /notificaciones ahora — test inmediato",
            )
            return

        cmd = args[0].lower()

        if cmd == "off":
            self._notif_enabled = False
            self._send_html(chat_id, "🔕 Notificaciones automáticas <b>desactivadas</b>.")
            return

        if cmd == "ahora":
            # Test inmediato: envía ambos resúmenes ahora mismo
            self._send_html(chat_id, "🧪 Enviando resúmenes de prueba…")
            self._send_morning_summary(chat_id)
            self._send_evening_summary(chat_id)
            return

        if cmd == "on":
            # Parsear horarios opcionales
            morning = "09:00"
            evening = "23:00"
            if len(args) >= 2:
                morning = args[1]
            if len(args) >= 3:
                evening = args[2]

            # Validar formato HH:MM
            def _valid_time(t: str) -> bool:
                try:
                    h, m = map(int, t.split(":"))
                    return 0 <= h <= 23 and 0 <= m <= 59
                except Exception:
                    return False

            if not _valid_time(morning) or not _valid_time(evening):
                self._send_html(
                    chat_id,
                    "⚠ Formato de hora inválido. Usa HH:MM, por ejemplo: 09:00 o 22:30",
                )
                return

            self._notif_enabled  = True
            self._notif_chat_id  = chat_id
            self._notif_morning  = morning
            self._notif_evening  = evening
            # Resetear para que no se salte el próximo envío
            self._last_morning_sent = None
            self._last_evening_sent = None

            self._send_html(
                chat_id,
                f"🔔 Notificaciones automáticas <b>activadas</b>.\n"
                f"🌅 Resumen matutino: {_c(morning)}\n"
                f"🌙 Resumen nocturno: {_c(evening)}\n\n"
                f"{_i('Recibirás un resumen cada día a esas horas.')}",
            )
            return

        # Comando no reconocido
        self._send_html(
            chat_id,
            f"Opción no reconocida: {_c(_esc(cmd))}\n"
            "Usa /notificaciones sin argumentos para ver las opciones.",
        )

    def _cmd_alertas(self, chat_id: int, args: list[str]) -> None:
        if not args or args[0].lower() not in ("on", "off"):
            # Mostrar estado actual
            estado = "🔔 <b>activadas</b>" if self._value_alerts_enabled else "🔕 <b>desactivadas</b>"
            umbral = f"<code>{self._value_edge_threshold:.0%}</code>"
            self._send_html(
                chat_id,
                f"📊 Alertas de valor: {estado}\n"
                f"Umbral de edge: {umbral}\n\n"
                "Uso:\n"
                "  /alertas on — activa con umbral por defecto (5%)\n"
                "  /alertas on 8 — activa con umbral del 8%\n"
                "  /alertas off — desactiva",
            )
            return

        if args[0].lower() == "off":
            self._value_alerts_enabled = False
            self._send_html(chat_id, "🔕 Alertas de valor <b>desactivadas</b>.")
            return

        # on [threshold]
        threshold = 0.05
        if len(args) > 1:
            try:
                threshold = float(args[1].replace("%", "")) / 100
            except ValueError:
                pass

        self._value_alerts_enabled = True
        self._value_edge_threshold = threshold
        self._value_alerts_chat_id = chat_id
        self._send_html(
            chat_id,
            f"🔔 Alertas de valor <b>activadas</b>.\n"
            f"Umbral de edge: <code>{threshold:.0%}</code>\n"
            f"Recibirás una alerta cuando aparezca un pick nuevo con edge ≥ {threshold:.0%}.",
        )

    # ── API pública para envíos directos desde la app ─────────────────────────

    def notify_value_pick(self, pick: dict) -> None:
        """Llamado desde app.py cuando un nuevo pick de alto valor aparece."""
        if not self._value_alerts_enabled:
            return
        edge = float(pick.get("edge", 0) or 0)
        if edge < self._value_edge_threshold:
            return

        home  = pick.get("home_team", "?")
        away  = pick.get("away_team", "?")
        p     = pick.get("pick", "?")
        odds  = float(pick.get("odds", 0) or 0)
        ev    = float(pick.get("ev", 0) or 0)
        rel   = int(pick.get("reliability_score", 0) or 0)
        risk  = pick.get("risk_light", "")
        risk_icons = {"VERDE": "⚡ VERDE", "AMARILLO": "⚠️ AMARILLO", "ROJO": "🔴 ROJO"}

        bp = float(pick.get("bankroll_pct", 2.0) or 2.0)
        win_pnl = (odds - 1) * bp / 100

        msg = (
            f"🎯 {_b('NUEVA OPORTUNIDAD DE VALOR')}\n\n"
            f"{_b(_esc(f'{home} vs {away}'))}\n"
            f"  📌 Pick: {_b(_esc(p))} @ {_c(f'{odds:.2f}')}\n"
            f"  📈 Edge: {_c(f'{edge:+.1%}')}  EV: {_c(f'{ev:+.1%}')}\n"
            f"  🔒 Fiabilidad: {_c(f'{rel}/99')}  {risk_icons.get(risk, '')}\n"
            f"  💶 Stake: {_c(f'{bp}%')} del bankroll  →  +{win_pnl:.4f}u si WIN"
        )

        if self._value_alerts_chat_id is None:
            self._notify(msg)
            return

        # Construir botones inline si hay storage disponible
        if self._storage:
            token = self._store_callback({
                "home_team":   str(home),
                "away_team":   str(away),
                "pick":        str(p),
                "odds":        odds,
                "edge":        edge,
                "model_prob":  pick.get("model_prob"),
                "bankroll_pct": bp,
                "league":      str(pick.get("league", "")),
                "date":        str(pick.get("date", "")),
                "signal":      "VERDE",
            })
            keyboard = [[
                {"text": "✅ Guardar pick", "callback_data": f"save_pick:{token}"},
                {"text": "❌ Ignorar",       "callback_data": f"skip:{token}"},
            ]]
            self._send_html_kb(self._value_alerts_chat_id, msg, keyboard)
        else:
            self._send_html(self._value_alerts_chat_id, msg)

    # ── Handler de botones inline ─────────────────────────────────────────────

    def _handle_callback(self, cbq: dict) -> None:
        """Procesa la pulsación de un botón inline."""
        callback_id = str(cbq.get("id", ""))
        data        = str(cbq.get("data", ""))
        msg_obj     = cbq.get("message", {})
        chat_id     = msg_obj.get("chat", {}).get("id")
        message_id  = msg_obj.get("message_id")

        if not chat_id or not data:
            self._answer_callback(callback_id)
            return

        chat_id = int(chat_id)
        parts   = data.split(":", 2)
        action  = parts[0]

        self._notify(f"Callback: {data}  chat_id={chat_id}")

        # ── save_pick: guardar pick del análisis en el tracker ────────────────
        if action == "save_pick":
            token     = parts[1] if len(parts) > 1 else ""
            pick_data = self._pending_callbacks.get(token)
            if not pick_data:
                self._answer_callback(
                    callback_id,
                    "⚠ Datos expirados. Usa /apostar para ver los picks actuales.",
                    show_alert=True,
                )
                return
            if not self._storage:
                self._answer_callback(callback_id, "⚠ Sin acceso a BD.", show_alert=True)
                return
            try:
                new_id    = self._storage.save_model_pick(pick_data)
                home      = _esc(str(pick_data.get("home_team", "?")))
                away      = _esc(str(pick_data.get("away_team", "?")))
                pick_str  = _esc(str(pick_data.get("pick", "?")))
                odds_val  = float(pick_data.get("odds", 0))
                bp        = float(pick_data.get("bankroll_pct", 2.0) or 2.0)
                self._answer_callback(callback_id, f"✅ Pick #{new_id} guardado")
                if message_id:
                    self._edit_message_text(
                        chat_id, message_id,
                        f"✅ <b>Pick guardado</b> · #{new_id}\n"
                        f"{_b(f'{home} vs {away}')}\n"
                        f"{_b(pick_str)} @ {_c(f'{odds_val:.2f}')}  "
                        f"Stake {_c(f'{bp}%')}\n"
                        f"{_i('Usa /pendientes para liquidarlo cuando acabe el partido.')}",
                    )
                del self._pending_callbacks[token]
            except Exception as exc:
                self._answer_callback(callback_id, f"❌ Error: {exc}", show_alert=True)

        # ── settle: liquidar pick PENDING como WIN o LOSS ─────────────────────
        elif action == "settle":
            pick_id_str = parts[1] if len(parts) > 1 else ""
            status      = parts[2].upper() if len(parts) > 2 else ""
            if not pick_id_str.isdigit() or status not in ("WIN", "LOSS"):
                self._answer_callback(callback_id, "❌ Datos inválidos.", show_alert=True)
                return
            if not self._storage:
                self._answer_callback(callback_id, "⚠ Sin acceso a BD.", show_alert=True)
                return
            pick_id = int(pick_id_str)
            try:
                pending = self._storage.load_model_picks(limit=300, status="PENDING")
                pick    = next((p for p in pending if p["id"] == pick_id), None)
                if not pick:
                    self._answer_callback(
                        callback_id, "⚠ Pick no encontrado (quizá ya liquidado).",
                        show_alert=True,
                    )
                    return
                odds = float(pick.get("odds") or 1.0)
                bp   = float(pick.get("bankroll_pct") or 2.0) / 100.0
                pnl  = (odds - 1) * bp if status == "WIN" else -bp
                self._storage.update_pick_result(pick_id, status, pnl)

                icon     = "✅" if status == "WIN" else "❌"
                # P&L en euros si hay bankroll
                data_d   = self._get_data()
                bankroll = float(data_d.get("bankroll_eur", 0) or 0)
                pnl_str  = (f"{pnl * bankroll:+.2f}€" if bankroll > 0
                            else f"{pnl:+.4f}u")
                home_s   = _esc(str(pick.get("home_team", "?"))[:22])
                away_s   = _esc(str(pick.get("away_team", "?"))[:22])
                pick_s   = _esc(str(pick.get("pick", "?")))

                self._answer_callback(callback_id, f"{icon} {status} registrado")
                if message_id:
                    self._edit_message_text(
                        chat_id, message_id,
                        f"{icon} <b>{status}</b> · Pick #{pick_id}\n"
                        f"{_b(f'{home_s} vs {away_s}')}\n"
                        f"{_b(pick_s)} @ {_c(f'{odds:.2f}')}\n"
                        f"P&amp;L: {_b(_c(pnl_str))}",
                    )
            except Exception as exc:
                self._answer_callback(callback_id, f"❌ Error: {exc}", show_alert=True)

        # ── skip: ignorar alerta de valor ─────────────────────────────────────
        elif action == "skip":
            token = parts[1] if len(parts) > 1 else ""
            if token in self._pending_callbacks:
                del self._pending_callbacks[token]
            self._answer_callback(callback_id, "Ignorado")
            if message_id:
                self._remove_reply_markup(chat_id, message_id)

        else:
            self._answer_callback(callback_id)

    # ── Nuevos comandos (apuestas desde móvil) ────────────────────────────────

    def _cmd_pendientes(self, chat_id: int) -> None:
        """Lista los picks PENDING del tracker con botones [WIN] [LOSS]."""
        if not self._storage:
            self._send_html(
                chat_id,
                "⚠️ <b>Sin acceso a la base de datos.</b>\n"
                "El bot necesita la referencia de Storage — comprueba la configuración en la app.",
            )
            return
        try:
            pending = self._storage.load_model_picks(limit=20, status="PENDING")
        except Exception as exc:
            self._send_html(chat_id, f"❌ Error al cargar picks: {_esc(str(exc))}")
            return

        if not pending:
            self._send_html(
                chat_id,
                "⏳ <b>Sin picks pendientes.</b>\n\n"
                "Guarda picks desde la app (📋 Resultados) o usa /apostar.",
            )
            return

        self._send_html(
            chat_id,
            f"⏳ {_b('PICKS PENDIENTES')} · {len(pending)} sin liquidar\n"
            f"{_i('Pulsa WIN o LOSS en cada uno para liquidarlo:')}",
        )

        # Mandar cada pick en mensaje separado con sus botones
        data_d   = self._get_data()
        bankroll = float(data_d.get("bankroll_eur", 0) or 0)

        for p in pending[:10]:
            pick_id = p.get("id")
            home    = _esc(str(p.get("home_team", "?"))[:20])
            away    = _esc(str(p.get("away_team", "?"))[:20])
            pick    = _esc(str(p.get("pick", "?")))
            odds    = float(p.get("odds", 0) or 0)
            edge    = float(p.get("edge", 0) or 0)
            bp      = float(p.get("bankroll_pct") or 2.0) / 100.0
            saved   = _esc(str(p.get("saved_at", ""))[:10])

            win_pnl  = (odds - 1) * bp
            loss_pnl = -bp
            if bankroll > 0:
                win_str  = f"✅ WIN (+{win_pnl * bankroll:.2f}€)"
                loss_str = f"❌ LOSS ({loss_pnl * bankroll:.2f}€)"
            else:
                win_str  = f"✅ WIN (+{win_pnl:.4f}u)"
                loss_str = f"❌ LOSS ({loss_pnl:.4f}u)"

            text = (
                f"🎯 {_b(f'#{pick_id}')} · {_i(saved)}\n"
                f"{_b(f'{home} vs {away}')}\n"
                f"{_b(pick)} @ {_c(f'{odds:.2f}')}  "
                f"Edge {_c(f'{edge:+.1%}')}"
            )
            keyboard = [[
                {"text": win_str,  "callback_data": f"settle:{pick_id}:WIN"},
                {"text": loss_str, "callback_data": f"settle:{pick_id}:LOSS"},
            ]]
            self._send_html_kb(chat_id, text, keyboard)

        if len(pending) > 10:
            self._send_html(
                chat_id,
                _i(f"Mostrando 10 de {len(pending)}. Ver todos en 📋 Resultados de la app."),
            )

    def _cmd_apostar(self, chat_id: int, args: list[str]) -> None:
        """
        Muestra picks VERDE del análisis para registrarlos en el tracker.

        Sin args → lista hasta 8 picks con botones [Guardar] o [WIN/LOSS].
        Con args → /resultado equivalente si se pasa «ID win|loss».
        """
        data     = self._get_data()
        picks    = data.get("results_green", [])
        bankroll = float(data.get("bankroll_eur", 0) or 0)

        if not picks:
            self._send_html(
                chat_id,
                "⚠️ <b>Sin picks VERDE disponibles.</b>\n"
                "Ejecuta ▶ Run Analysis en la app y después /refresh.",
            )
            return

        self._send_html(
            chat_id,
            f"💰 {_b('REGISTRAR APUESTA')} — picks activos:\n"
            f"{_i('Elige uno para guardarlo en el tracker o liquidarlo:')}",
        )

        for p in picks[:8]:
            pick_id = p.get("id")           # ya en tracker → int
            home    = _esc(str(p.get("home_team", "?"))[:20])
            away    = _esc(str(p.get("away_team", "?"))[:20])
            pick    = _esc(str(p.get("pick", "?")))
            odds    = float(p.get("odds", 0) or 0)
            edge    = float(p.get("edge", 0) or 0)
            ev      = float(p.get("ev", 0) or 0)
            rel     = int(p.get("reliability_score", 0) or 0)
            bp_pct  = float(p.get("bankroll_pct", 2.0) or 2.0)
            bp      = bp_pct / 100.0

            win_pnl  = (odds - 1) * bp
            loss_pnl = -bp
            if bankroll > 0:
                win_str  = f"✅ WIN +{win_pnl * bankroll:.2f}€"
                loss_str = f"❌ LOSS {loss_pnl * bankroll:.2f}€"
            else:
                win_str  = f"✅ WIN +{win_pnl:.4f}u"
                loss_str = f"❌ LOSS {loss_pnl:.4f}u"

            text = (
                f"⚽ {_b(f'{home} vs {away}')}\n"
                f"{_b(pick)} @ {_c(f'{odds:.2f}')}"
                f"  Edge {_c(f'{edge:+.1%}')}"
                f"  EV {_c(f'{ev:+.1%}')}"
                f"  Fiab {_c(f'{rel}/99')}"
                f"\n  Stake: {_c(f'{bp_pct}%')} del bankroll"
            )

            if pick_id and self._storage:
                # El pick ya está en el tracker → ofrecer liquidar
                keyboard = [[
                    {"text": win_str,  "callback_data": f"settle:{pick_id}:WIN"},
                    {"text": loss_str, "callback_data": f"settle:{pick_id}:LOSS"},
                ]]
            elif self._storage:
                # Pick del análisis no guardado → ofrecer guardar
                token = self._store_callback({
                    "home_team":   str(p.get("home_team", "")),
                    "away_team":   str(p.get("away_team", "")),
                    "pick":        str(p.get("pick", "")),
                    "odds":        odds,
                    "edge":        float(p.get("edge", 0) or 0),
                    "model_prob":  p.get("model_prob"),
                    "bankroll_pct": bp_pct,
                    "league":      str(p.get("league", "")),
                    "date":        str(p.get("date", "")),
                    "signal":      "VERDE",
                })
                keyboard = [[
                    {"text": "💾 Guardar en tracker", "callback_data": f"save_pick:{token}"},
                    {"text": "❌ Ignorar",            "callback_data": f"skip:{token}"},
                ]]
            else:
                # Sin storage → mostrar solo info, sin botones
                self._send_html(chat_id, text)
                continue

            self._send_html_kb(chat_id, text, keyboard)

        if len(picks) > 8:
            self._send_html(
                chat_id,
                _i(f"Mostrando 8 de {len(picks)}. Ver todos con /picks o en la app."),
            )

    def _cmd_resultado(self, chat_id: int, args: list[str]) -> None:
        """
        Liquida un pick del tracker.

        /resultado           → muestra /pendientes
        /resultado 42 win    → marca pick #42 como WIN
        /resultado 42 loss   → marca pick #42 como LOSS
        """
        if not args:
            # Sin args → igual que /pendientes
            self._cmd_pendientes(chat_id)
            return

        if len(args) < 2:
            self._send_html(
                chat_id,
                "ℹ️ Uso: /resultado &lt;id&gt; win|loss\n"
                "Ejemplo: /resultado 42 win\n\n"
                "Usa /pendientes para ver los IDs de tus picks.",
            )
            return

        pick_id_str = args[0]
        status_raw  = args[1].upper()

        if not pick_id_str.isdigit():
            self._send_html(chat_id, f"❌ ID inválido: {_c(_esc(pick_id_str))}")
            return
        if status_raw not in ("WIN", "LOSS"):
            self._send_html(
                chat_id,
                f"❌ Estado inválido: {_c(_esc(status_raw))}\n"
                "Usa <b>win</b> o <b>loss</b>.",
            )
            return

        if not self._storage:
            self._send_html(
                chat_id,
                "⚠️ Sin acceso a la base de datos.\n"
                "Comprueba que el bot esté configurado correctamente en la app.",
            )
            return

        pick_id = int(pick_id_str)
        try:
            pending = self._storage.load_model_picks(limit=300, status="PENDING")
            pick    = next((p for p in pending if p["id"] == pick_id), None)
            if not pick:
                self._send_html(
                    chat_id,
                    f"⚠ Pick #{pick_id} no encontrado entre los PENDING.\n"
                    f"Puede que ya esté liquidado. Usa /roi para ver el historial.",
                )
                return

            odds = float(pick.get("odds") or 1.0)
            bp   = float(pick.get("bankroll_pct") or 2.0) / 100.0
            pnl  = (odds - 1) * bp if status_raw == "WIN" else -bp
            self._storage.update_pick_result(pick_id, status_raw, pnl)

            data_d   = self._get_data()
            bankroll = float(data_d.get("bankroll_eur", 0) or 0)
            pnl_str  = (f"{pnl * bankroll:+.2f}€" if bankroll > 0
                        else f"{pnl:+.4f}u")

            icon   = "✅" if status_raw == "WIN" else "❌"
            home_s = _esc(str(pick.get("home_team", "?"))[:22])
            away_s = _esc(str(pick.get("away_team", "?"))[:22])
            pick_s = _esc(str(pick.get("pick", "?")))

            self._send_html(
                chat_id,
                f"{icon} {_b(status_raw)} registrado — Pick #{pick_id}\n\n"
                f"{_b(f'{home_s} vs {away_s}')}\n"
                f"{_b(pick_s)} @ {_c(f'{odds:.2f}')}\n"
                f"P&amp;L: {_b(_c(pnl_str))}\n\n"
                f"{_i('Usa /roi para ver el resumen actualizado.')}",
            )
            self._notify(f"✓ /resultado #{pick_id} {status_raw}")

        except Exception as exc:
            self._send_html(chat_id, f"❌ Error al liquidar: {_esc(str(exc))}")

    def _cmd_bankroll(self, chat_id: int) -> None:
        """Muestra el estado actual del bankroll y el P&L acumulado."""
        data_d   = self._get_data()
        bankroll = float(data_d.get("bankroll_eur", 0) or 0)

        if not self._storage:
            self._send_html(
                chat_id,
                "⚠️ Sin acceso a base de datos. "
                "Comprueba la configuración del bot en la app.",
            )
            return

        try:
            all_picks = self._storage.load_model_picks(limit=500)
        except Exception as exc:
            self._send_html(chat_id, f"❌ Error: {_esc(str(exc))}")
            return

        settled = [p for p in all_picks if p.get("status") in ("WIN", "LOSS")]
        pending = [p for p in all_picks if p.get("status") == "PENDING"]
        wins    = [p for p in settled if p.get("status") == "WIN"]
        losses  = [p for p in settled if p.get("status") == "LOSS"]

        total_pnl_u = sum(float(p.get("pnl") or 0) for p in settled)
        total_risk  = sum(
            float(p.get("bankroll_pct") or 0) / 100.0
            for p in settled if p.get("bankroll_pct") is not None
        )
        roi = (total_pnl_u / total_risk * 100) if total_risk > 0 else 0.0

        # Stake en riesgo en picks pendientes
        risk_pending_u = sum(
            float(p.get("bankroll_pct") or 0) / 100.0
            for p in pending if p.get("bankroll_pct") is not None
        )

        if bankroll > 0:
            pnl_str   = f"{total_pnl_u * bankroll:+.2f}€"
            br_str    = f"{bankroll:.2f}€"
            curr_str  = f"{(bankroll + total_pnl_u * bankroll):.2f}€"
            risk_str  = f"{risk_pending_u * bankroll:.2f}€"
        else:
            pnl_str   = f"{total_pnl_u:+.4f}u"
            br_str    = "no configurado"
            curr_str  = "—"
            risk_str  = f"{risk_pending_u:.4f}u"

        hit_rate = len(wins) / len(settled) * 100 if settled else 0.0
        roi_icon = "📈" if roi >= 0 else "📉"

        lines = [
            f"💶 {_b('BANKROLL')}",
            "",
            f"Bankroll inicial: {_c(br_str)}",
        ]
        if bankroll > 0:
            lines.append(f"Bankroll actual:  {_c(curr_str)}")
        lines += [
            "",
            f"{roi_icon} ROI real: {_b(_c(f'{roi:+.2f}%'))}",
            f"💶 P&amp;L total: {_b(_c(pnl_str))}",
            "",
            f"✅ WIN: {_c(str(len(wins)))}  "
            f"❌ LOSS: {_c(str(len(losses)))}  "
            f"⏳ PEND: {_c(str(len(pending)))}",
            f"🎲 Tasa de acierto: {_c(f'{hit_rate:.1f}%')}",
        ]
        if pending:
            lines.append(f"🔒 En juego ahora: {_c(risk_str)}")

        lines += [
            "",
            _i("Usa /pendientes para liquidar picks · /roi para el detalle completo"),
        ]
        self._send_html(chat_id, "\n".join(lines))

    # ── API pública para envíos directos desde la app ─────────────────────────

    def send_text(self, chat_id: int | str, text: str) -> None:
        self._send_html(int(chat_id), text)
