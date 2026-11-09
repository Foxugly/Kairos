"""Choix de la source de cours active (réglage `SOURCE_COURS`)."""

from django.conf import settings

from .cours import SourceCours


def source_cours(code: str | None = None) -> SourceCours:
    code = code or settings.SOURCE_COURS
    if code == "yahoo":
        from .yahoo import SourceYahoo

        return SourceYahoo()
    raise ValueError(f"Source de cours inconnue : {code!r}")
