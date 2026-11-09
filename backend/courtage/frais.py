"""Calcul pur (sans base de données) des frais d'un ordre : courtage, change et TOB."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import BaremeDonnees, RegleDonnees

CENTIME = Decimal("0.01")


@dataclass(frozen=True)
class DetailFrais:
    courtage: Decimal
    change: Decimal
    tob: Decimal
    total: Decimal


def _arrondi(montant: Decimal) -> Decimal:
    return montant.quantize(CENTIME, rounding=ROUND_HALF_UP)


def _regle(bareme: BaremeDonnees, place: str) -> RegleDonnees:
    for regle in bareme.regles:
        if place in regle.places:
            return regle
    raise ValueError(f"Aucune règle de courtage pour la place {place!r}")


def calculer_frais(
    bareme_donnees: BaremeDonnees,
    place: str,
    devise: str,
    type_titre: str,
    quantite: int,
    prix: Decimal,
    taux_eur: Decimal,
) -> DetailFrais:
    """Frais en EUR d'un ordre. `taux_eur` : EUR pour 1 unité de `devise` (1 si EUR)."""
    regle = _regle(bareme_donnees, place)
    if regle.devise != devise:
        raise ValueError(f"Devise {devise} incompatible avec la règle ({regle.devise})")
    montant = quantite * prix
    montant_eur = montant * taux_eur

    # Courtage dans la devise de la règle, puis converti.
    brut = max(quantite * regle.par_action + montant * regle.pourcentage, regle.minimum)
    if regle.maximum_pourcentage is not None:
        brut = min(brut, montant * regle.maximum_pourcentage)
    if regle.maximum is not None:
        brut = min(brut, regle.maximum)
    courtage = _arrondi(brut * taux_eur)

    change = Decimal("0.00")
    if devise != "EUR":
        change = _arrondi(
            max(montant_eur * bareme_donnees.change_pourcentage, bareme_donnees.change_minimum)
        )

    tob = Decimal("0.00")
    for ligne in bareme_donnees.tob:
        if ligne.type_titre == type_titre:
            tob = _arrondi(min(montant_eur * ligne.taux, ligne.plafond))
            break

    return DetailFrais(courtage=courtage, change=change, tob=tob, total=courtage + change + tob)
