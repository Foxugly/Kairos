"""Source de cours Yahoo Finance, via yfinance."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

import yfinance

from .cours import BougieBrute

logger = logging.getLogger(__name__)

_CHAMPS = ["Open", "High", "Low", "Close", "Volume"]
_QUATRE_DECIMALES = Decimal("0.0001")


def _decimal(valeur: float) -> Decimal:
    return Decimal(str(valeur)).quantize(_QUATRE_DECIMALES)


class SourceYahoo:
    code = "yahoo"

    def __init__(self) -> None:
        self.erreurs: dict[str, str] = {}

    def bougies(
        self, tickers: list[str], intervalle: str, depuis: datetime
    ) -> dict[str, list[BougieBrute]]:
        self.erreurs = {}
        if not tickers:
            return {}
        try:
            donnees = yfinance.download(
                tickers, group_by="ticker", interval=intervalle, start=depuis,
                progress=False, auto_adjust=False,
            )
        except Exception as exc:  # réseau, limitation, format : jamais d'exception vers l'appelant
            logger.warning("Yahoo : échec du téléchargement (%s)", exc)
            self.erreurs = {t: f"téléchargement impossible : {exc}" for t in tickers}
            return {}
        resultat: dict[str, list[BougieBrute]] = {}
        for ticker in tickers:
            try:
                resultat[ticker] = self._extraire(donnees[ticker])
            except Exception as exc:  # ticker absent ou colonnes inattendues
                self.erreurs[ticker] = f"aucune donnée : {exc!r}"
        return resultat

    @staticmethod
    def _extraire(table) -> list[BougieBrute]:
        table = table[_CHAMPS].dropna()  # lignes incomplètes (NaN) écartées
        bougies = []
        for instant, ligne in table.iterrows():
            debut = instant.to_pydatetime()
            debut = debut.replace(tzinfo=UTC) if debut.tzinfo is None else debut.astimezone(UTC)
            bougies.append(BougieBrute(
                debut=debut,
                ouverture=_decimal(ligne["Open"]), haut=_decimal(ligne["High"]),
                bas=_decimal(ligne["Low"]), cloture=_decimal(ligne["Close"]),
                volume=int(ligne["Volume"]),
            ))
        return bougies

    def taux_eur(self, devise: str) -> Decimal:
        if devise == "EUR":
            return Decimal(1)
        if devise != "USD":
            raise ValueError(f"Devise non gérée : {devise}")
        donnees = yfinance.download(
            "EURUSD=X", period="5d", interval="1d", progress=False, auto_adjust=False,
            group_by="ticker",
        )
        cours = donnees["EURUSD=X"]["Close"].dropna()
        if cours.empty:
            raise ValueError("Aucun cours EURUSD=X")
        # EURUSD=X = dollars pour 1 euro ; on veut des euros pour 1 dollar.
        return (Decimal(1) / Decimal(str(cours.iloc[-1]))).quantize(Decimal("0.000001"))
