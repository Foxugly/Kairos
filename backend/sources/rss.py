"""Lecture des flux RSS/Atom et enregistrement des nouvelles dédoublonnées."""

import hashlib
import html
import logging
import re
import unicodedata
from calendar import timegm
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import requests
from django.db import IntegrityError, transaction

from marche.models import Valeur

from .models import FluxRss, Nouvelle
from .rattachement import valeurs_citees

logger = logging.getLogger(__name__)

URL_MAX = 1000  # longueur du champ `Nouvelle.url`
USER_AGENT = "Kairos/1.0 (+https://kairos.foxugly.com)"


class FluxIllisible(Exception):
    """Le contenu reçu n'est pas un flux RSS/Atom (page HTML, erreur, etc.)."""


@dataclass
class NouvelleBrute:
    url: str
    titre: str
    resume: str
    publiee: datetime


def _nettoyer(html_brut: str) -> str:
    sans_balises = re.sub(r"<[^>]+>", " ", html_brut or "")
    return re.sub(r"\s+", " ", html.unescape(sans_balises)).strip()


def _date(entree) -> datetime | None:
    horodatage = entree.get("published_parsed") or entree.get("updated_parsed")
    return datetime.fromtimestamp(timegm(horodatage), UTC) if horodatage else None


def lire_flux(contenu: bytes, recu: datetime | None = None) -> list[NouvelleBrute]:
    """`recu` : date donnée aux entrées sans date (par défaut, maintenant)."""
    analyse = feedparser.parse(contenu)
    # Une page HTML ou un message d'erreur ne donne ni entrée ni version de flux reconnue.
    if not analyse.entries and (analyse.bozo or not analyse.version):
        raise FluxIllisible("contenu illisible : ce n'est pas un flux RSS/Atom")
    recu = recu or datetime.now(UTC)
    nouvelles = []
    for entree in analyse.entries:
        titre = _nettoyer(entree.get("title", ""))
        url = entree.get("link", "").strip()
        if not titre or not url or not _normaliser_titre(titre):
            continue
        if len(url) > URL_MAX:
            logger.warning("Nouvelle écartée : URL de %d caractères (max %d)", len(url), URL_MAX)
            continue
        nouvelles.append(NouvelleBrute(
            url=url, titre=titre,
            resume=_nettoyer(entree.get("summary", "")),
            publiee=_date(entree) or recu,
        ))
    return nouvelles


def telecharger(url: str) -> bytes:
    reponse = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
    if reponse.status_code != 200:
        raise requests.HTTPError(f"statut HTTP {reponse.status_code}")
    return reponse.content


def _normaliser_titre(titre: str) -> str:
    """Minuscules, ponctuation retirée, espaces compactés."""
    minuscule = unicodedata.normalize("NFC", titre).lower()
    return " ".join(re.sub(r"[^\w\s]", "", minuscule).split())


def empreinte(titre: str, publiee: datetime) -> str:
    """sha256 du titre normalisé et du jour de publication (UTC).

    Le jour évite d'écarter à jamais les titres qui reviennent (« Wall Street ouvre en
    hausse ») ; deux flux qui reprennent la même dépêche le même jour restent fusionnés.
    """
    jour = publiee.astimezone(UTC).strftime("%Y-%m-%d")
    return hashlib.sha256(f"{_normaliser_titre(titre)}|{jour}".encode()).hexdigest()


def relever_nouvelles(maintenant: datetime, telecharger: Callable[[str], bytes] = telecharger) -> dict:
    valeurs = list(Valeur.objects.actives())
    total = 0
    en_erreur: dict[str, str] = {}
    for flux in FluxRss.objects.filter(actif=True):
        try:
            brutes = lire_flux(telecharger(flux.url), maintenant)
            creees = sum(_enregistrer(flux, brute, valeurs) for brute in brutes)
        except Exception as exc:  # un flux défaillant (réseau, XML, base) n'arrête pas les autres
            message = f"{type(exc).__name__}: {exc}"
            logger.warning("Flux %s : %s", flux.nom, message)
            en_erreur[flux.nom] = message
            FluxRss.objects.filter(pk=flux.pk).update(derniere_erreur=message)
            continue
        total += creees
        FluxRss.objects.filter(pk=flux.pk).update(dernier_releve=maintenant, derniere_erreur="")
    return {"nouvelles": total, "flux_en_erreur": en_erreur}


def _enregistrer(flux: FluxRss, brute: NouvelleBrute, valeurs: list[Valeur]) -> int:
    """Crée la nouvelle si ni son URL ni son titre n'est déjà connu ; rend 1 si créée."""
    cle = empreinte(brute.titre, brute.publiee)
    if Nouvelle.objects.filter(url=brute.url).exists() or Nouvelle.objects.filter(empreinte=cle).exists():
        return 0
    try:
        with transaction.atomic():
            nouvelle = Nouvelle.objects.create(
                url=brute.url, empreinte=cle, titre=brute.titre, resume=brute.resume,
                publiee=brute.publiee, flux=flux,
            )
            nouvelle.valeurs.set(valeurs_citees(f"{brute.titre}\n{brute.resume}", valeurs))
    except IntegrityError:  # doublon créé entre-temps par un relevé concurrent : déjà connue
        return 0
    return 1
