"""Cotations exploitables maintenant : place en séance, cours et taux récents (sinon la valeur est absente)."""

from datetime import datetime, timedelta
from decimal import Decimal

from marche.models import Bougie, TauxChange, Valeur
from marche.seances import en_seance

from .strategie import Cotation, Marche

FRAICHEUR_COURS = timedelta(minutes=30)
FRAICHEUR_TAUX = timedelta(hours=24)


def taux_recent(devise: str, maintenant: datetime) -> Decimal | None:
    """EUR pour 1 unité de `devise` relevé depuis moins de 24 h ; 1 pour l'euro."""
    if devise == "EUR":
        return Decimal(1)
    taux = (
        TauxChange.objects.filter(
            devise=devise, instant__gt=maintenant - FRAICHEUR_TAUX, instant__lte=maintenant
        )
        .order_by("-instant")
        .first()
    )
    return taux.taux if taux else None


def marche_et_absences(maintenant: datetime) -> tuple[Marche, dict[str, str]]:
    """Cotations exploitables, et pour chaque autre valeur relevée la raison de son absence.

    Jamais d'ordre sur un cours périmé : une valeur sans bougie 5m de moins de 30 min est absente.
    """
    cotations: Marche = {}
    absences: dict[str, str] = {}
    taux: dict[str, Decimal | None] = {}
    for valeur in Valeur.objects.a_relever():
        if not en_seance(valeur.place, maintenant):
            absences[valeur.ticker] = "place fermée"
            continue
        derniere = (
            Bougie.objects.filter(
                valeur=valeur, intervalle="5m",
                debut__gt=maintenant - FRAICHEUR_COURS, debut__lte=maintenant,
            )
            .order_by("-debut")
            .first()
        )
        if derniere is None:
            absences[valeur.ticker] = "pas de cours récent"
            continue
        if valeur.devise not in taux:
            taux[valeur.devise] = taux_recent(valeur.devise, maintenant)
        if taux[valeur.devise] is None:
            absences[valeur.ticker] = f"pas de taux {valeur.devise} récent"
            continue
        cotations[valeur.ticker] = Cotation(
            prix=derniere.cloture, devise=valeur.devise, place=valeur.place,
            type_titre=valeur.type_titre, taux_eur=taux[valeur.devise],
            bas=derniere.bas, haut=derniere.haut,
        )
    return cotations, absences


def marche(maintenant: datetime) -> Marche:
    return marche_et_absences(maintenant)[0]
