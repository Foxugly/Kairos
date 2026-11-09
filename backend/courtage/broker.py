"""Interface `Broker` et broker simulé : exécution au dernier cours connu, avec glissement et frais."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from portefeuille.strategie import Cotation

from .frais import CENTIME, DetailFrais, calculer_frais
from .models import Bareme, BaremeDonnees

QUATRE_DECIMALES = Decimal("0.0001")


@dataclass(frozen=True)
class OrdreDemande:
    sens: str  # SensOrdre : "achat" ou "vente"
    ticker: str
    quantite: int
    cotation: Cotation
    bareme: str  # Bareme.broker du portefeuille
    jour: date  # choisit le barème en vigueur


@dataclass(frozen=True)
class Execution:
    prix: Decimal  # prix appliqué, dans la devise de la valeur
    taux_eur: Decimal
    montant_eur: Decimal  # hors frais
    frais: DetailFrais


class Broker(Protocol):
    code: str

    def estimer(self, ordre: OrdreDemande) -> DetailFrais: ...

    def executer(self, ordre: OrdreDemande) -> Execution: ...


class BrokerSimule:
    """Exécute sur papier au cours de la cotation, avec le glissement défavorable du barème."""

    code = "simule"

    def _calcul(self, ordre: OrdreDemande) -> Execution:
        bareme: BaremeDonnees = Bareme.en_vigueur(ordre.bareme, ordre.jour).donnees()
        c = ordre.cotation
        sens = Decimal(1) if ordre.sens == "achat" else Decimal(-1)
        prix = (c.prix * (1 + sens * bareme.glissement)).quantize(QUATRE_DECIMALES, ROUND_HALF_UP)
        frais = calculer_frais(bareme, c.place, c.devise, c.type_titre, ordre.quantite, prix, c.taux_eur)
        montant = (ordre.quantite * prix * c.taux_eur).quantize(CENTIME, ROUND_HALF_UP)
        return Execution(prix=prix, taux_eur=c.taux_eur, montant_eur=montant, frais=frais)

    def estimer(self, ordre: OrdreDemande) -> DetailFrais:
        return self._calcul(ordre).frais

    def executer(self, ordre: OrdreDemande) -> Execution:
        return self._calcul(ordre)


_BROKERS: dict[str, Broker] = {BrokerSimule.code: BrokerSimule()}


def broker(code: str) -> Broker:
    """Broker du portefeuille (`Portefeuille.broker`) ; KeyError si inconnu."""
    return _BROKERS[code]
