"""Signaux techniques du jour (croisement de moyennes, RSI, cassure), en code pur."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from analyse.indicateurs import moyenne_mobile, rsi

MM_COURTE = 20
MM_LONGUE = 50
FENETRE_CASSURE = 20
RSI_SURVENDU = Decimal(30)
RSI_SURACHETE = Decimal(70)


class Sens(Enum):
    ACHAT = "achat"
    VENTE = "vente"


@dataclass(frozen=True)
class Signal:
    code: str  # "croisement_mm", "rsi" ou "cassure"
    sens: Sens
    detail: str


@dataclass
class BougieJour:
    jour: date
    ouverture: Decimal
    haut: Decimal
    bas: Decimal
    cloture: Decimal


def _croisement(clotures: list[Decimal]) -> Signal | None:
    # Il faut aussi les moyennes de la veille : 51 clôtures au minimum.
    if len(clotures) < MM_LONGUE + 1:
        return None
    veille = clotures[:-1]
    courte_v, longue_v = moyenne_mobile(veille, MM_COURTE), moyenne_mobile(veille, MM_LONGUE)
    courte, longue = moyenne_mobile(clotures, MM_COURTE), moyenne_mobile(clotures, MM_LONGUE)
    if courte_v <= longue_v and courte > longue:
        return Signal("croisement_mm", Sens.ACHAT, f"MM{MM_COURTE} passe au-dessus de MM{MM_LONGUE}")
    if courte_v >= longue_v and courte < longue:
        return Signal("croisement_mm", Sens.VENTE, f"MM{MM_COURTE} passe en dessous de MM{MM_LONGUE}")
    return None


def _rsi(clotures: list[Decimal]) -> Signal | None:
    valeur = rsi(clotures)
    if valeur is None:
        return None
    if valeur < RSI_SURVENDU:
        return Signal("rsi", Sens.ACHAT, f"RSI14 à {valeur} : titre survendu (sous {RSI_SURVENDU})")
    if valeur > RSI_SURACHETE:
        return Signal("rsi", Sens.VENTE, f"RSI14 à {valeur} : titre suracheté (au-dessus de {RSI_SURACHETE})")
    return None


def _cassure(bougies: list[BougieJour]) -> Signal | None:
    # Les 20 séances qui précèdent la dernière : 21 bougies au minimum.
    if len(bougies) < FENETRE_CASSURE + 1:
        return None
    precedentes = bougies[-FENETRE_CASSURE - 1 : -1]
    cloture = bougies[-1].cloture
    plus_haut = max(b.haut for b in precedentes)
    plus_bas = min(b.bas for b in precedentes)
    if cloture > plus_haut:
        return Signal("cassure", Sens.ACHAT, f"Clôture au-dessus du plus haut des {FENETRE_CASSURE} séances précédentes")
    if cloture < plus_bas:
        return Signal("cassure", Sens.VENTE, f"Clôture sous le plus bas des {FENETRE_CASSURE} séances précédentes")
    return None


def signaux_du_jour(bougies: list[BougieJour]) -> list[Signal]:
    """Signaux de la dernière bougie ; `bougies` est triée par jour croissant."""
    if not bougies:
        return []
    clotures = [b.cloture for b in bougies]
    candidats = (_croisement(clotures), _rsi(clotures), _cassure(bougies))
    return [s for s in candidats if s is not None]


def score(signaux: list[Signal]) -> int:
    """Somme des signaux : +1 par achat, −1 par vente."""
    return sum(1 if s.sens is Sens.ACHAT else -1 for s in signaux)
