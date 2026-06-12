# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
injury_adjuster.py — Ajuste de probabilidades por bajas de jugadores.

Sin API externa: el usuario introduce manualmente las ausencias conocidas.
Los factores de impacto están calibrados con literatura cuantitativa de fútbol
(Goumas 2017, Gelade & Dobson 2007, ajuste propio sobre datos de Premier League).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# (role, position) → reducción porcentual de la win-prob del equipo afectado
# La reducción se aplica multiplicativamente: win_prob *= (1 - factor)
IMPACT_FACTORS: dict[tuple[str, str], float] = {
    ("STAR", "FWD"): 0.11,
    ("STAR", "MID"): 0.08,
    ("STAR", "DEF"): 0.07,
    ("STAR", "GK"):  0.06,
    ("KEY",  "FWD"): 0.06,
    ("KEY",  "MID"): 0.05,
    ("KEY",  "DEF"): 0.05,
    ("KEY",  "GK"):  0.05,
    ("ROLE", "FWD"): 0.025,
    ("ROLE", "MID"): 0.020,
    ("ROLE", "DEF"): 0.020,
    ("ROLE", "GK"):  0.030,
}

Role     = Literal["STAR", "KEY", "ROLE"]
Position = Literal["GK", "DEF", "MID", "FWD"]

ROLE_LABELS = {
    "STAR": "Estrella (−10% aprox.)",
    "KEY":  "Titular clave (−5% aprox.)",
    "ROLE": "Rotación (−2% aprox.)",
}
POS_LABELS = {
    "GK":  "Portero",
    "DEF": "Defensa",
    "MID": "Centrocampista",
    "FWD": "Delantero",
}


@dataclass
class PlayerAbsence:
    player_name: str
    team:        str       # "home" | "away"
    role:        Role
    position:    Position
    reason:      str = "Lesión/Suspensión"

    def impact(self) -> float:
        return IMPACT_FACTORS.get((self.role, self.position), 0.02)

    def label(self) -> str:
        team_str = "Local" if self.team == "home" else "Visitante"
        return (
            f"{team_str}: {self.player_name} "
            f"({POS_LABELS[self.position]}, {self.role}) "
            f"— {self.reason}  [−{self.impact()*100:.1f}%]"
        )


@dataclass
class InjuryAdjuster:
    absences: list[PlayerAbsence] = field(default_factory=list)
    MAX_IMPACT: float = 0.25   # máximo 25% reducción acumulada por equipo

    def add(self, absence: PlayerAbsence) -> None:
        self.absences.append(absence)

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.absences):
            self.absences.pop(index)

    def clear(self) -> None:
        self.absences.clear()

    def has_absences(self) -> bool:
        return bool(self.absences)

    def adjust_probs(
        self,
        home_prob: float,
        draw_prob: float,
        away_prob: float,
    ) -> tuple[float, float, float]:
        """
        Aplica el impacto de las bajas y re-normaliza a suma=1.

        Modelo:
        - La prob perdida por el equipo con bajas se redistribuye:
          40% va al rival, 60% va al empate.
        - draw_prob se usa como base (bug fix: antes se ignoraba completamente).
        """
        if not self.absences:
            return home_prob, draw_prob, away_prob

        hi = self._team_impact("home")
        ai = self._team_impact("away")

        # Probabilidad perdida por cada equipo
        lost_h = home_prob * hi
        lost_a = away_prob * ai

        # Redistribución conservadora: 40% al rival, 60% al empate
        h = home_prob - lost_h + lost_a * 0.40
        a = away_prob - lost_a + lost_h * 0.40
        d = draw_prob + lost_h * 0.60 + lost_a * 0.60

        # Clamp y re-normalizar
        h = max(0.01, h)
        d = max(0.01, d)
        a = max(0.01, a)

        total = h + d + a
        return round(h / total, 4), round(d / total, 4), round(a / total, 4)

    def _team_impact(self, team: str) -> float:
        team_abs = sorted(
            [ab for ab in self.absences if ab.team == team],
            key=lambda x: -x.impact(),
        )
        if not team_abs:
            return 0.0
        # Diminishing returns: 2ª baja pesa 75%, 3ª 56%, etc.
        raw = sum(ab.impact() * (0.75 ** i) for i, ab in enumerate(team_abs))
        return min(raw, self.MAX_IMPACT)

    def summary_lines(self) -> list[str]:
        return [ab.label() for ab in self.absences]

    def impact_summary(self, home_prob: float, draw_prob: float, away_prob: float) -> str:
        if not self.absences:
            return "Sin bajas introducidas."
        adj_h, adj_d, adj_a = self.adjust_probs(home_prob, draw_prob, away_prob)
        lines = [
            f"Base: {home_prob*100:.1f}% / {draw_prob*100:.1f}% / {away_prob*100:.1f}%",
            f"Ajustado: {adj_h*100:.1f}% / {adj_d*100:.1f}% / {adj_a*100:.1f}%",
            "—",
        ]
        lines += self.summary_lines()
        return "\n".join(lines)
