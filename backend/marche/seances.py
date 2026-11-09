"""Horaires de séance des places boursières (jours fériés non gérés : un férié ne produit pas de bougie)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

FUSEAU_PLACE: dict[str, str] = {
    "NASDAQ": "America/New_York",
    "NYSE": "America/New_York",
    "XPAR": "Europe/Paris",
    "XAMS": "Europe/Amsterdam",
    "XBRU": "Europe/Brussels",
    "XETR": "Europe/Berlin",
    "XMIL": "Europe/Rome",
    "XMAD": "Europe/Madrid",
    "XHEL": "Europe/Helsinki",
    "XDUB": "Europe/Dublin",
}

# (ouverture, fermeture) en heure locale ; défaut européen 09:00–17:30.
_EUROPE = (time(9, 0), time(17, 30))
HORAIRES_PLACE: dict[str, tuple[time, time]] = {
    "NASDAQ": (time(9, 30), time(16, 0)),
    "NYSE": (time(9, 30), time(16, 0)),
    "XHEL": (time(10, 0), time(18, 30)),
    "XDUB": (time(8, 0), time(16, 30)),
}


def en_seance(place: str, instant: datetime) -> bool:
    """Vrai si la place est ouverte à `instant` (datetime avec fuseau) : lun–ven, ouverture incluse, fermeture exclue."""
    local = instant.astimezone(ZoneInfo(FUSEAU_PLACE[place]))
    if local.weekday() >= 5:
        return False
    ouverture, fermeture = HORAIRES_PLACE.get(place, _EUROPE)
    return ouverture <= local.time() < fermeture
