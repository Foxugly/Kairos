"""Relevé des cours : interroge la source pour les valeurs à relever et enregistre bougies et taux."""

import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sources.cours import SourceCours
from sources.registre import source_cours

from django.db import DatabaseError, transaction

from .models import Bougie, TauxChange, Valeur
from .seances import FUSEAU_PLACE, HORAIRES_PLACE, en_seance

logger = logging.getLogger(__name__)

_DELAI_APRES_FERMETURE = timedelta(minutes=30)
_FERMETURE_PAR_DEFAUT = time(17, 30)
_FENETRE_JOURNALIERE = timedelta(minutes=90)  # durée pendant laquelle la 1d est tentée
_VALIDITE_TAUX = timedelta(minutes=30)
_CHAMPS_MAJ = ["ouverture", "haut", "bas", "cloture", "volume"]


def _dans_la_fenetre(place: str, instant: datetime) -> bool:
    """En séance, ou fermée depuis moins de 30 min (pour que la dernière bougie soit relevée)."""
    return en_seance(place, instant) or en_seance(place, instant - _DELAI_APRES_FERMETURE)


def _journee_a_relever(valeur: Valeur, maintenant: datetime) -> bool:
    """Vrai si la clôture est définitive (30 min après la fermeture) et sans bougie `1d` du jour.

    La clôture est provisoire juste après la fermeture (enchère, retard de la source). La 1d n'est
    tentée que pendant 90 min à partir de là : un jour férié coûte quelques requêtes, pas un appel
    à chaque cycle jusqu'à minuit (un jour manqué est rattrapé le lendemain, fenêtre de 30 jours).
    """
    local = maintenant.astimezone(ZoneInfo(FUSEAU_PLACE[valeur.place]))
    if local.weekday() >= 5:
        return False
    fermeture = HORAIRES_PLACE.get(valeur.place, (None, _FERMETURE_PAR_DEFAUT))[1]
    apres = timedelta(hours=local.hour, minutes=local.minute) - timedelta(
        hours=fermeture.hour, minutes=fermeture.minute
    )
    if not _DELAI_APRES_FERMETURE <= apres < _DELAI_APRES_FERMETURE + _FENETRE_JOURNALIERE:
        return False
    # Yahoo date la bougie journalière par la date locale de la séance, sans fuseau : on la lit
    # comme minuit UTC de ce jour (convention des bougies `1d`), quelle que soit la place.
    minuit = datetime(local.year, local.month, local.day, tzinfo=UTC)
    return not valeur.bougies.filter(
        intervalle="1d", debut__gte=minuit, debut__lt=minuit + timedelta(days=1)
    ).exists()


def _enregistrer(valeur: Valeur, intervalle: str, brutes) -> int:
    """Enregistre (ou met à jour) les bougies d'une valeur ; rend leur nombre."""
    Bougie.objects.bulk_create(
        [
            Bougie(
                valeur=valeur, intervalle=intervalle, debut=b.debut, ouverture=b.ouverture,
                haut=b.haut, bas=b.bas, cloture=b.cloture, volume=b.volume,
            )
            for b in brutes
        ],
        update_conflicts=True,
        unique_fields=["valeur", "intervalle", "debut"],
        update_fields=_CHAMPS_MAJ,
    )
    return len(brutes)


def enregistrer_isole(valeurs, intervalle: str, par_ticker: dict, erreurs: dict) -> int:
    """Enregistre valeur par valeur : une erreur en base sur l'une n'empêche pas les autres."""
    total = 0
    for v in valeurs:
        try:
            with transaction.atomic():
                total += _enregistrer(v, intervalle, par_ticker.get(v.ticker, []))
        except DatabaseError as exc:
            logger.warning("Enregistrement impossible pour %s (%s)", v.ticker, exc)
            erreurs[v.ticker] = f"enregistrement impossible : {exc}"
    return total


def relever_cours(maintenant: datetime, source: SourceCours | None = None) -> dict:
    """Relève les bougies `5m` (valeurs en séance) et `1d` (après la fermeture) puis le taux USD.

    Idempotent. Rend {"bougies": nombre enregistré, "valeurs": nombre de valeurs interrogées,
    "erreurs": {ticker: message}} ; un ticker en échec n'empêche pas les autres.
    """
    source = source or source_cours()
    actives = list(Valeur.objects.a_relever())
    erreurs: dict[str, str] = {}
    total = 0

    en_cours = [v for v in actives if _dans_la_fenetre(v.place, maintenant)]
    if en_cours:
        # Une seule requête, depuis la plus ancienne reprise (l'enregistrement est idempotent).
        departs = []
        for v in en_cours:
            derniere = v.bougies.filter(intervalle="5m").order_by("-debut").first()
            # Plafonné à 2 jours : au-delà de 60 jours Yahoo refuse l'intraday pour tout le lot.
            plancher = maintenant - timedelta(days=2)
            departs.append(max(derniere.debut, plancher) if derniere else plancher)
        par_ticker = source.bougies([v.ticker for v in en_cours], "5m", min(departs))
        erreurs.update(source.erreurs)
        total += enregistrer_isole(en_cours, "5m", par_ticker, erreurs)

    journalieres = [v for v in actives if _journee_a_relever(v, maintenant)]
    if journalieres:
        par_ticker = source.bougies(
            [v.ticker for v in journalieres], "1d", maintenant - timedelta(days=30)
        )
        erreurs.update(source.erreurs)
        total += enregistrer_isole(journalieres, "1d", par_ticker, erreurs)

    interrogees = en_cours + [v for v in journalieres if v not in en_cours]
    taux_recent = TauxChange.objects.filter(
        devise="USD", instant__gt=maintenant - _VALIDITE_TAUX
    ).exists()
    if any(v.devise == "USD" for v in interrogees) and not taux_recent:
        try:
            TauxChange.objects.update_or_create(
                devise="USD", instant=maintenant, defaults={"taux": source.taux_eur("USD")}
            )
        except Exception as exc:  # le taux manquant ne doit pas faire perdre les bougies
            logger.warning("Taux USD indisponible (%s)", exc)
            erreurs["USD"] = str(exc)

    if interrogees and all(v.ticker in erreurs for v in interrogees):
        # Panne totale : une erreur (et non un avertissement) pour que Sentry crée l'événement.
        logger.error("Relevé des cours : les %d valeurs interrogées ont toutes échoué", len(interrogees))
    return {"bougies": total, "valeurs": len(interrogees), "erreurs": erreurs}
