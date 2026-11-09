"""Relevé des cours : interroge la source pour les valeurs actives et enregistre bougies et taux."""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sources.cours import SourceCours
from sources.registre import source_cours

from .models import Bougie, TauxChange, Valeur
from .seances import FUSEAU_PLACE, HORAIRES_PLACE, en_seance

logger = logging.getLogger(__name__)

_DELAI_APRES_FERMETURE = timedelta(minutes=30)
_FERMETURE_PAR_DEFAUT = time(17, 30)
_CHAMPS_MAJ = ["ouverture", "haut", "bas", "cloture", "volume"]


def _dans_la_fenetre(place: str, instant: datetime) -> bool:
    """En séance, ou fermée depuis moins de 30 min (pour que la dernière bougie soit relevée)."""
    return en_seance(place, instant) or en_seance(place, instant - _DELAI_APRES_FERMETURE)


def _journee_a_relever(valeur: Valeur, maintenant: datetime) -> bool:
    """Vrai si la place est close pour la journée (jour ouvré, après la fermeture) et sans bougie `1d` du jour."""
    local = maintenant.astimezone(ZoneInfo(FUSEAU_PLACE[valeur.place]))
    if local.weekday() >= 5:
        return False
    if local.time() < HORAIRES_PLACE.get(valeur.place, (None, _FERMETURE_PAR_DEFAUT))[1]:
        return False
    # La bougie journalière de Yahoo commence à minuit local de la séance.
    minuit = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return not valeur.bougies.filter(
        intervalle="1d", debut__gte=minuit, debut__lt=minuit + timedelta(days=1)
    ).exists()


def _enregistrer(valeur: Valeur, intervalle: str, brutes) -> int:
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


def relever_cours(maintenant: datetime, source: SourceCours | None = None) -> dict:
    """Relève les bougies `5m` (valeurs en séance) et `1d` (après la fermeture) puis le taux USD.

    Idempotent. Rend {"bougies": nombre enregistré, "valeurs": nombre de valeurs interrogées,
    "erreurs": {ticker: message}} ; un ticker en échec n'empêche pas les autres.
    """
    source = source or source_cours()
    actives = list(Valeur.objects.actives())
    erreurs: dict[str, str] = {}
    total = 0

    en_cours = [v for v in actives if _dans_la_fenetre(v.place, maintenant)]
    if en_cours:
        # Une seule requête, depuis la plus ancienne reprise (l'enregistrement est idempotent).
        departs = []
        for v in en_cours:
            derniere = v.bougies.filter(intervalle="5m").order_by("-debut").first()
            departs.append(derniere.debut if derniere else maintenant - timedelta(days=2))
        par_ticker = source.bougies([v.ticker for v in en_cours], "5m", min(departs))
        erreurs.update(source.erreurs)
        for v in en_cours:
            total += _enregistrer(v, "5m", par_ticker.get(v.ticker, []))

    journalieres = [v for v in actives if _journee_a_relever(v, maintenant)]
    if journalieres:
        par_ticker = source.bougies(
            [v.ticker for v in journalieres], "1d", maintenant - timedelta(days=30)
        )
        erreurs.update(source.erreurs)
        for v in journalieres:
            total += _enregistrer(v, "1d", par_ticker.get(v.ticker, []))

    interrogees = en_cours + [v for v in journalieres if v not in en_cours]
    if any(v.devise == "USD" for v in interrogees):
        try:
            TauxChange.objects.update_or_create(
                devise="USD", instant=maintenant, defaults={"taux": source.taux_eur("USD")}
            )
        except Exception as exc:  # le taux manquant ne doit pas faire perdre les bougies
            logger.warning("Taux USD indisponible (%s)", exc)
            erreurs["USD"] = str(exc)

    return {"bougies": total, "valeurs": len(interrogees), "erreurs": erreurs}
