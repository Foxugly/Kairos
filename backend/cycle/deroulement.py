"""Déroulement d'un cycle de collecte : verrou, étapes isolées, journal, purge."""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import sentry_sdk
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from marche.releve import relever_cours
from sources.rss import relever_nouvelles

from .models import Cycle, StatutCycle, Verrou

logger = logging.getLogger(__name__)

DUREE_MAX_CYCLE = timedelta(minutes=10)
CONSERVATION = timedelta(days=30)

# Les plans suivants ajoutent leurs étapes ici ; chacune reçoit le `maintenant` du cycle.
ETAPES: list[tuple[str, Callable[[datetime], dict]]] = [
    ("nouvelles", relever_nouvelles),
    ("cours", relever_cours),
]


def _serialisable(resultat):
    """Convertit en JSON ce qui ne l'est pas (dates, Decimal…) pour le journal."""
    return json.loads(json.dumps(resultat, cls=DjangoJSONEncoder, default=str))


def _ouvrir(maintenant: datetime) -> Cycle | None:
    """Contrôle + création sous verrou (court) ; None si un cycle récent tourne déjà."""
    with transaction.atomic():
        # Verrou de ligne sur PostgreSQL (sans effet sur SQLite, où les écritures sont déjà sérialisées).
        Verrou.objects.get_or_create(pk=1)  # la ligne peut manquer (flush, restauration)
        Verrou.objects.select_for_update().get(pk=1)
        en_cours = Cycle.objects.filter(statut=StatutCycle.EN_COURS)
        if en_cours.filter(debut__gt=maintenant - DUREE_MAX_CYCLE).exists():
            return None
        en_cours.update(statut=StatutCycle.ABANDONNE, fin=maintenant)
        return Cycle.objects.create(debut=maintenant)


def lancer(maintenant: datetime | None = None) -> Cycle | None:
    maintenant = maintenant or timezone.now()
    cycle = _ouvrir(maintenant)
    if cycle is None:
        return None

    Cycle.objects.filter(debut__lt=maintenant - CONSERVATION).delete()

    journal: dict = {}
    en_erreur = False
    # Les étapes tournent hors de toute transaction : une panne ne doit pas retenir le verrou.
    for nom, etape in ETAPES:
        try:
            journal[nom] = _serialisable(etape(maintenant))
        except Exception as exc:
            en_erreur = True
            logger.exception("Étape %s en échec", nom)
            sentry_sdk.capture_exception(exc)
            journal[nom] = {"erreur": str(exc) or type(exc).__name__}

    cycle.journal = journal
    cycle.fin = timezone.now()
    cycle.statut = StatutCycle.EN_ERREUR if en_erreur else StatutCycle.TERMINE
    cycle.save(update_fields=["journal", "fin", "statut"])
    return cycle
