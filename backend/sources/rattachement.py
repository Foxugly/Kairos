"""Rattachement d'un texte aux valeurs qu'il cite."""

import re
from collections.abc import Iterable

from marche.models import Valeur

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})


def _normaliser(texte: str) -> str:
    return texte.translate(_APOSTROPHES)


def _motifs(valeur: Valeur) -> re.Pattern:
    """Un motif par valeur : alias en mot entier, puis les formes `$T`, `(T)`, `NASDAQ: T`.

    Pas de `\b` : il se comporte mal aux bords d'un alias qui finit par un point ou une
    apostrophe. Les lookarounds traitent lettres (accentuées comprises) et chiffres comme
    caractères de mot.
    """
    morceaux = []
    for alias in _normaliser(valeur.alias).split(","):
        alias = alias.strip()
        if alias:
            morceaux.append(rf"(?<!\w){re.escape(alias)}(?!\w)")
    ticker = re.escape(valeur.ticker)
    morceaux.append(rf"\${ticker}(?!\w|\.\w)")
    morceaux.append(rf"\({ticker}\)")
    morceaux.append(rf"\b(?:NASDAQ|NYSE):\s*{ticker}(?!\w|\.\w)")
    return re.compile("|".join(morceaux))  # sensible à la casse volontairement


def valeurs_citees(texte: str, valeurs: Iterable[Valeur]) -> set[Valeur]:
    texte = _normaliser(texte)
    return {valeur for valeur in valeurs if _motifs(valeur).search(texte)}
