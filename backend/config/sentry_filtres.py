"""Ce que Kairos laisse partir vers Sentry.

Kairos ne manipule aucune donnée personnelle (cours de bourse et flux
publics). Restent la règle de la flotte (OPERATIONS.md
§3.25 : ni secret ni donnée personnelle chez Sentry) et le bruit : pas de
corps de requête, pas de variables locales, pas de cookies, pas de query
string, et pas d'erreur `DisallowedHost` (les robots qui appellent l'IP).
"""

from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import DisallowedHost

#: Les seuls en-têtes de requête transmis.
ENTETES_PERMIS = frozenset({
    "accept",
    "accept-language",
    "content-length",
    "content-type",
    "host",
    "user-agent",
    "x-forwarded-proto",
})


def masquer_url(url):
    """URL sans query string ni fragment."""
    if not isinstance(url, str):
        return url
    morceaux = urlsplit(url)
    return urlunsplit((morceaux.scheme, morceaux.netloc, morceaux.path, "", ""))


def _nettoyer(evenement):
    requete = evenement.get("request")
    if isinstance(requete, dict):
        entetes = requete.get("headers") or {}
        evenement["request"] = {
            "method": requete.get("method"),
            "url": masquer_url(requete.get("url")),
            "headers": {
                nom: valeur for nom, valeur in entetes.items()
                if str(nom).lower() in ENTETES_PERMIS
            } if isinstance(entetes, dict) else {},
        }
    utilisateur = evenement.get("user")
    if isinstance(utilisateur, dict) and utilisateur.get("id") is not None:
        evenement["user"] = {"id": str(utilisateur["id"])}
    else:
        evenement.pop("user", None)
    return evenement


def avant_envoi(evenement, indice):
    """`before_send` : erreurs et messages."""
    erreur = (indice or {}).get("exc_info", (None, None))[1]
    if isinstance(erreur, DisallowedHost):
        return None
    return _nettoyer(evenement)


def avant_transaction(evenement, indice):
    """`before_send_transaction` : mesures de performance."""
    return _nettoyer(evenement)


def reglages_sentry():
    """Options de `sentry_sdk.init`, partagées par les réglages et les tests."""
    return {
        "send_default_pii": False,
        "max_request_body_size": "never",
        "include_local_variables": False,
        "before_send": avant_envoi,
        "before_send_transaction": avant_transaction,
    }
