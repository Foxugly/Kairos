"""Stratégie du portefeuille simulé, en code pur : partagée par le cycle et le backtest.

Aucun accès base : les entrées sont des dataclasses figées (voir `Regles.depuis` pour les lire
sur un `Portefeuille`). Toutes les fractions sont des fractions (0,05 = 5 %).
"""

from dataclasses import dataclass
from decimal import Decimal

from analyse.signaux import Sens, Signal, score
from courtage.frais import calculer_frais
from courtage.models import BaremeDonnees

UN = Decimal(1)


@dataclass(frozen=True)
class Regles:
    part_max: Decimal
    positions_max: int
    stop_perte: Decimal
    seuil_suiveur: Decimal
    ecart_suiveur: Decimal
    frais_max_relatifs: Decimal
    score_achat: int

    @classmethod
    def depuis(cls, portefeuille) -> "Regles":
        """Lit les champs de règles d'un `Portefeuille` (ou de tout objet qui les expose)."""
        return cls(
            part_max=portefeuille.part_max,
            positions_max=portefeuille.positions_max,
            stop_perte=portefeuille.stop_perte,
            seuil_suiveur=portefeuille.seuil_suiveur,
            ecart_suiveur=portefeuille.ecart_suiveur,
            frais_max_relatifs=portefeuille.frais_max_relatifs,
            score_achat=portefeuille.score_achat,
        )


@dataclass(frozen=True)
class PositionVue:
    ticker: str
    quantite: int
    prix_entree: Decimal
    plus_haut: Decimal


@dataclass(frozen=True)
class Cotation:
    """Cours exploitable maintenant : prix récent et taux EUR présents."""

    prix: Decimal
    devise: str
    place: str
    type_titre: str
    taux_eur: Decimal


Marche = dict[str, Cotation]


@dataclass(frozen=True)
class Intention:
    ticker: str
    action: str  # "acheter", "vendre" ou "refuser"
    quantite: int
    motif: str


def _pourcent(fraction: Decimal) -> str:
    """0,05 -> « 5 » ; 0,025 -> « 2,5 »."""
    texte = format((fraction * 100).normalize(), "f")
    return texte.replace(".", ",")


def stops(positions: list[PositionVue], marche: Marche, regles: Regles) -> list[Intention]:
    """Ventes déclenchées par le stop-loss ou le stop suiveur ; valeur sans cours : on garde."""
    ventes = []
    for p in positions:
        cotation = marche.get(p.ticker)
        if cotation is None:
            continue
        prix = cotation.prix
        if prix <= p.prix_entree * (UN - regles.stop_perte):
            motif = f"stop-loss −{_pourcent(regles.stop_perte)} %"
        elif (
            p.plus_haut >= p.prix_entree * (UN + regles.seuil_suiveur)
            and prix <= p.plus_haut * (UN - regles.ecart_suiveur)
        ):
            motif = "stop suiveur"
        else:
            continue
        ventes.append(Intention(p.ticker, "vendre", p.quantite, motif))
    return ventes


def decider(
    liquidites: Decimal,
    total: Decimal,
    positions: list[PositionVue],
    signaux: dict[str, list[Signal]],
    marche: Marche,
    regles: Regles,
    bareme: BaremeDonnees,
) -> list[Intention]:
    """Ventes sur signal (score <= −1), puis achats sous contraintes de liquidités et de frais.

    `positions` : celles qui restent ouvertes après application de `stops` par l'appelant, pour qu'une
    position déjà vendue sur stop ne soit pas vendue deux fois. Les positions ouvertes comptent toutes
    pour `positions_max` (le produit des ventes n'est pas encore disponible). Une valeur détenue sans cours
    est gardée ; les liquidités ne sont jamais négatives.
    """
    intentions = []
    detenus = {p.ticker for p in positions}

    for p in sorted(positions, key=lambda p: p.ticker):
        if p.ticker not in marche:
            continue
        s = score(signaux.get(p.ticker, []))
        if s <= -1:
            intentions.append(Intention(p.ticker, "vendre", p.quantite, f"signal de vente (score −{-s})"))

    candidats = []
    for ticker, liste in signaux.items():
        if ticker in detenus:
            continue
        s = score(liste)
        if s >= regles.score_achat and not any(x.sens is Sens.VENTE for x in liste):
            candidats.append((-s, ticker))
    candidats.sort()

    restantes = liquidites
    ouvertes = len(positions)
    for _, ticker in candidats:
        refus, quantite, cout = _evaluer_achat(
            ticker, restantes, total, ouvertes, marche, regles, bareme
        )
        if refus is not None:
            intentions.append(Intention(ticker, "refuser", 0, refus))
            continue
        restantes -= cout
        ouvertes += 1
        intentions.append(Intention(ticker, "acheter", quantite, "signaux d'achat"))
    return intentions


def _evaluer_achat(ticker, restantes, total, ouvertes, marche, regles, bareme):
    """Renvoie (motif de refus ou None, quantité, coût en EUR frais d'achat compris)."""
    cotation = marche.get(ticker)
    if cotation is None:
        return "pas de cours récent", 0, Decimal(0)
    if ouvertes >= regles.positions_max:
        return f"{regles.positions_max} positions déjà ouvertes", 0, Decimal(0)

    prix = cotation.prix * (UN + bareme.glissement)
    unitaire = prix * cotation.taux_eur
    plafond = regles.part_max * total
    quantite = int(min(plafond, restantes) // unitaire)
    if quantite < 1:
        if restantes < unitaire:
            return "liquidités insuffisantes", 0, Decimal(0)
        return f"une action dépasse {_pourcent(regles.part_max)} % du portefeuille", 0, Decimal(0)

    def frais_achat(q):
        return calculer_frais(
            bareme, cotation.place, cotation.devise, cotation.type_titre, q, prix, cotation.taux_eur
        )

    try:
        # Les frais d'achat s'ajoutent au montant : on réduit la quantité jusqu'à tenir dans les liquidités.
        while quantite >= 1 and quantite * unitaire + frais_achat(quantite).total > restantes:
            quantite -= 1
        if quantite < 1:
            return "liquidités insuffisantes", 0, Decimal(0)
        achat = frais_achat(quantite)
        revente = calculer_frais(
            bareme, cotation.place, cotation.devise, cotation.type_titre, quantite, prix, cotation.taux_eur
        )
    except ValueError as erreur:
        return str(erreur), 0, Decimal(0)

    montant = quantite * unitaire
    aller_retour = achat.total + revente.total
    if aller_retour > regles.frais_max_relatifs * montant:
        pct = _pourcent((aller_retour / montant).quantize(Decimal("0.0001")))
        return f"frais aller-retour trop élevés ({pct} %)", 0, Decimal(0)
    return None, quantite, montant + achat.total
