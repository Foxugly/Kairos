"""Indicateurs techniques en code pur (Decimal, aucun accès base)."""

from decimal import ROUND_HALF_UP, Decimal

CENTIEME = Decimal("0.01")


def moyenne_mobile(cours: list[Decimal], n: int) -> Decimal | None:
    """Moyenne simple des n derniers cours ; None s'il y a moins de n points."""
    if n <= 0 or len(cours) < n:
        return None
    return sum(cours[-n:], Decimal(0)) / n


def rsi(cours: list[Decimal], n: int = 14) -> Decimal | None:
    """RSI de Wilder au centième ; None sous n+1 points, 100 s'il n'y a aucune baisse."""
    if n <= 0 or len(cours) < n + 1:
        return None
    variations = [b - a for a, b in zip(cours, cours[1:])]
    gains = [max(v, Decimal(0)) for v in variations]
    pertes = [max(-v, Decimal(0)) for v in variations]
    # Première moyenne : moyenne simple des n premières variations, puis lissage de Wilder.
    gain = sum(gains[:n], Decimal(0)) / n
    perte = sum(pertes[:n], Decimal(0)) / n
    for g, p in zip(gains[n:], pertes[n:]):
        gain = (gain * (n - 1) + g) / n
        perte = (perte * (n - 1) + p) / n
    if perte == 0:
        return Decimal(100)
    force_relative = gain / perte
    return (100 - 100 / (1 + force_relative)).quantize(CENTIEME, rounding=ROUND_HALF_UP)
