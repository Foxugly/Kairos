"""Contrat d'une source de cours : le reste de Kairos ne connaît que ces types, jamais Yahoo."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class BougieBrute:
    debut: datetime  # UTC
    ouverture: Decimal
    haut: Decimal
    bas: Decimal
    cloture: Decimal
    volume: int


class SourceCours(Protocol):
    code: str
    # Raison de l'échec par ticker pour le dernier appel de `bougies` (remis à zéro à chaque appel).
    erreurs: dict[str, str]

    def bougies(
        self, tickers: list[str], intervalle: str, depuis: datetime
    ) -> dict[str, list[BougieBrute]]:
        """Bougies `5m` ou `1d` depuis `depuis`. Un ticker en échec est absent du résultat (voir `erreurs`) ; ne lève jamais."""
        ...

    def taux_eur(self, devise: str) -> Decimal:
        """Valeur en euros d'une unité de `devise` (EUR pour 1 USD, par exemple)."""
        ...

    def taux_journaliers(self, devise: str, depuis: datetime) -> list[tuple[datetime, Decimal]]:
        """Taux de clôture journaliers depuis `depuis` (minuit UTC de la date, EUR pour 1 unité).

        Liste vide en cas d'échec, la raison dans `erreurs[devise]` ; ne lève jamais.
        """
        ...
