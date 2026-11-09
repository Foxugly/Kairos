"""Backtest des règles techniques sur l'historique journalier, en code pur (aucun accès base).

Mêmes fonctions que le cycle : `signaux_du_jour`, `stops`, `decider` et l'exécution du broker simulé.
Chaque jour J (union des séances de toutes les valeurs ; une valeur sans bougie ce jour-là n'est pas
cotable) : l'indice est acheté à l'ouverture du premier jour ; les stops se contrôlent sur le plus bas de J
(sortie au niveau du stop, ou à l'ouverture si elle est déjà en dessous ; ordres en séance au taux USD
d'avant J, valorisation au taux de J) ; les ordres issus de la clôture de
la séance précédente de la valeur s'exécutent à l'ouverture de J ; le plus haut des positions est mis à
jour (après les stops) ; les signaux se calculent à la clôture de J ; le portefeuille est valorisé.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from analyse.signaux import BougieJour, Signal, signaux_du_jour
from courtage.broker import Execution, execution_simulee
from courtage.frais import CENTIME, DetailFrais
from courtage.models import BaremeDonnees

from .execution import HISTORIQUE
from .strategie import UN, Cotation, PositionVue, Regles, decider, niveau_stop, stops

FRACTION = Decimal("0.0001")


@dataclass(frozen=True)
class OrdreBacktest:
    jour: date
    ticker: str
    sens: str  # "achat" ou "vente"
    quantite: int
    prix: Decimal
    taux_eur: Decimal
    montant_eur: Decimal
    frais: DetailFrais
    motif: str


@dataclass
class Rapport:
    """Fractions au dix-millième (0,0512 = 5,12 %) ; montants en EUR."""

    debut: date
    fin: date
    valeur_finale: Decimal
    performance: Decimal
    performance_indice: Decimal
    ecart: Decimal
    nb_positions: int
    taux_gagnantes: Decimal  # positions fermées en gain / positions fermées (0 si aucune)
    frais_total: Decimal  # ordres du portefeuille, hors achat de l'indice
    tob_total: Decimal
    perte_max: Decimal  # plus forte baisse depuis un sommet
    courbe: list[tuple[date, Decimal, Decimal]]  # (jour, total, total de l'indice) à la clôture
    ordres: list[OrdreBacktest] = field(default_factory=list)
    indice_ordre: OrdreBacktest | None = None


@dataclass
class _Position:
    quantite: int
    prix_entree: Decimal
    plus_haut: Decimal
    cout_eur: Decimal  # montant payé + frais


def perte_max(totaux: list[Decimal]) -> Decimal:
    """Plus forte baisse relative depuis un sommet de la courbe, en fraction."""
    sommet, pire = None, Decimal(0)
    for total in totaux:
        sommet = total if sommet is None else max(sommet, total)
        if sommet > 0:
            pire = max(pire, (sommet - total) / sommet)
    return pire.quantize(FRACTION, ROUND_HALF_UP)


def rejouer(
    series: dict[str, list[BougieJour]],
    meta: dict[str, tuple[str, str, str]],
    taux_usd: dict[date, Decimal],
    regles: Regles,
    bareme: BaremeDonnees,
    capital: Decimal,
    indice: str,
    debut: date | None = None,
) -> Rapport:
    """Rejoue les règles sur `series` (bougies 1d triées par jour, indice compris).

    `meta` : (devise, place, type_titre) par ticker. `taux_usd` : EUR pour 1 USD par jour ; le plus
    récent à la date ou avant s'applique. `debut` : les bougies antérieures ne servent qu'aux signaux.
    """
    return _Rejeu(series, meta, taux_usd, regles, bareme, capital, indice, debut).derouler()


class _Rejeu:
    def __init__(self, series, meta, taux_usd, regles, bareme, capital, indice, debut):
        self.series = series
        self.meta = meta
        self.taux_usd = taux_usd
        self.dates_taux = sorted(taux_usd)
        self.regles = regles
        self.bareme = bareme
        self.capital = capital
        self.indice = indice
        self.rang = {t: {b.jour: i for i, b in enumerate(bougies)} for t, bougies in series.items()}
        self.univers = sorted(t for t in series if t != indice)
        self.jours = sorted(
            {b.jour for bougies in series.values() for b in bougies if debut is None or b.jour >= debut}
        )
        if not self.jours:
            raise ValueError("aucune bougie sur la période")

        self.liquidites = capital
        self.positions: dict[str, _Position] = {}
        # Signaux de la dernière clôture de chaque valeur, exécutés à sa séance suivante.
        self.en_attente: dict[str, list[Signal]] = {}
        self.derniers: dict[str, Decimal] = {}  # dernière clôture connue
        self.ordres: list[OrdreBacktest] = []
        self.resultats: list[Decimal] = []  # produit de sortie − coût d'entrée des positions fermées
        self.indice_ordre: OrdreBacktest | None = None
        self.indice_quantite = 0
        self.indice_liquidites = capital
        self.courbe: list[tuple[date, Decimal, Decimal]] = []

    def derouler(self) -> Rapport:
        for jour in self.jours:
            if self.indice_ordre is None:
                self._acheter_indice(jour)
            stoppees = self._stops(jour)
            self._decisions(jour, stoppees)
            self._plus_hauts(jour)
            self._signaux(jour)
            self._valoriser(jour)
        return self._rapport()

    # -- cours ---------------------------------------------------------------------------------------

    def _bougie(self, ticker: str, jour: date) -> BougieJour | None:
        i = self.rang.get(ticker, {}).get(jour)  # l'indice peut n'avoir aucune bougie
        return None if i is None else self.series[ticker][i]

    def _taux(self, devise: str, jour: date, en_seance: bool) -> Decimal | None:
        """Taux le plus récent connu : à la clôture de J, celui de J ; en séance, celui d'avant J
        (le taux de J est sa clôture, inconnu à l'ouverture)."""
        if devise == "EUR":
            return UN
        i = (bisect_left if en_seance else bisect_right)(self.dates_taux, jour)
        return self.taux_usd[self.dates_taux[i - 1]] if i else None

    def _cotation(self, ticker: str, prix: Decimal, jour: date) -> Cotation | None:
        """Cotation pour un ordre en séance (ouverture ou stop) : taux d'avant J."""
        devise, place, type_titre = self.meta[ticker]
        taux = self._taux(devise, jour, en_seance=True)
        if taux is None:
            return None
        return Cotation(prix=prix, devise=devise, place=place, type_titre=type_titre, taux_eur=taux)

    def _titres(self, jour: date, a_l_ouverture: bool) -> Decimal:
        total = Decimal(0)
        for ticker, p in self.positions.items():
            b = self._bougie(ticker, jour)
            cours = b.ouverture if a_l_ouverture and b is not None else self.derniers[ticker]
            # Une position n'a pu être achetée qu'avec un taux : il en existe un à cette date.
            total += p.quantite * cours * self._taux(self.meta[ticker][0], jour, en_seance=a_l_ouverture)
        return total.quantize(CENTIME, ROUND_HALF_UP)

    # -- ordres --------------------------------------------------------------------------------------

    def _ordre(self, jour, ticker, sens, quantite, ex: Execution, motif) -> OrdreBacktest:
        return OrdreBacktest(
            jour=jour, ticker=ticker, sens=sens, quantite=quantite, prix=ex.prix, taux_eur=ex.taux_eur,
            montant_eur=ex.montant_eur, frais=ex.frais, motif=motif,
        )

    def _acheter_indice(self, jour: date):
        b = self._bougie(self.indice, jour)
        cotation = b and self._cotation(self.indice, b.ouverture, jour)
        if not cotation:
            return
        # Comme le cycle : quantité entière, on descend jusqu'à tenir dans le capital, frais compris.
        quantite = int(self.capital // (cotation.prix * cotation.taux_eur))
        while quantite >= 1:
            ex = execution_simulee(self.bareme, "achat", cotation, quantite)
            if ex.montant_eur + ex.frais.total <= self.capital:
                break
            quantite -= 1
        if quantite < 1:
            return
        self.indice_quantite = quantite
        self.indice_liquidites = self.capital - ex.montant_eur - ex.frais.total
        self.indice_ordre = self._ordre(jour, self.indice, "achat", quantite, ex, "achat de l'indice")

    def _acheter(self, jour: date, ticker: str, cotation: Cotation, quantite: int, motif: str):
        ex = execution_simulee(self.bareme, "achat", cotation, quantite)
        cout = ex.montant_eur + ex.frais.total
        if cout > self.liquidites:
            return  # comme le cycle : refusé à l'exécution (glissement arrondi)
        self.liquidites -= cout
        self.positions[ticker] = _Position(quantite, ex.prix, ex.prix, cout)
        self.ordres.append(self._ordre(jour, ticker, "achat", quantite, ex, motif))

    def _vendre(self, jour: date, ticker: str, cotation: Cotation, motif: str):
        p = self.positions.pop(ticker)
        ex = execution_simulee(self.bareme, "vente", cotation, p.quantite)
        produit = ex.montant_eur - ex.frais.total
        self.liquidites += produit
        self.resultats.append(produit - p.cout_eur)
        self.ordres.append(self._ordre(jour, ticker, "vente", p.quantite, ex, motif))

    @staticmethod
    def _vue(ticker: str, p: _Position) -> PositionVue:
        return PositionVue(ticker, p.quantite, p.prix_entree, p.plus_haut)

    # -- étapes du jour ------------------------------------------------------------------------------

    def _stops(self, jour: date) -> set[str]:
        """Ventes sur stop touché par le plus bas du jour ; rend les valeurs vendues."""
        au_plus_bas = {}
        for ticker in self.positions:
            b = self._bougie(ticker, jour)
            cotation = b and self._cotation(ticker, b.bas, jour)
            if cotation:
                au_plus_bas[ticker] = cotation
        vues = [self._vue(t, p) for t, p in self.positions.items()]
        vendues = set()
        for intention in stops(vues, au_plus_bas, self.regles):
            ticker = intention.ticker
            p = self.positions[ticker]
            # Le cours descend jusqu'au stop, sauf ouverture déjà en dessous (gap) : exécution à l'ouverture.
            prix = min(self._bougie(ticker, jour).ouverture, niveau_stop(self._vue(ticker, p), self.regles))
            cotation = replace(au_plus_bas[ticker], prix=prix)
            # Motif relu au prix de sortie : « stop suiveur » si c'est lui qui a été atteint en premier.
            motif = stops([self._vue(ticker, p)], {ticker: cotation}, self.regles)[0].motif
            self._vendre(jour, ticker, cotation, motif)
            vendues.add(ticker)
        return vendues

    def _decisions(self, jour: date, stoppees: set[str]):
        signaux, marche = {}, {}
        for ticker in list(self.en_attente):
            b = self._bougie(ticker, jour)
            if b is None:
                continue
            # Consommés à la séance suivante de la valeur, exécutés ou non (jamais d'ordre d'avant-hier).
            liste = self.en_attente.pop(ticker)
            cotation = self._cotation(ticker, b.ouverture, jour)
            if ticker in stoppees or cotation is None:
                continue
            signaux[ticker] = liste
            marche[ticker] = cotation
        if not signaux:
            return
        total = self.liquidites + self._titres(jour, a_l_ouverture=True)
        vues = [self._vue(t, p) for t, p in self.positions.items()]
        for intention in decider(self.liquidites, total, vues, signaux, marche, self.regles, self.bareme):
            ticker = intention.ticker
            if intention.action == "vendre":
                self._vendre(jour, ticker, marche[ticker], intention.motif)
            elif intention.action == "acheter":
                self._acheter(jour, ticker, marche[ticker], intention.quantite, intention.motif)

    def _plus_hauts(self, jour: date):
        for ticker, p in self.positions.items():
            b = self._bougie(ticker, jour)
            if b is not None and b.haut > p.plus_haut:
                p.plus_haut = b.haut

    def _signaux(self, jour: date):
        for ticker in self.univers:
            i = self.rang[ticker].get(jour)
            if i is None:
                continue
            # Même fenêtre que le cycle : les HISTORIQUE dernières bougies jusqu'à J inclus.
            liste = signaux_du_jour(self.series[ticker][max(0, i + 1 - HISTORIQUE) : i + 1])
            if liste:
                self.en_attente[ticker] = liste
            else:
                self.en_attente.pop(ticker, None)

    def _valoriser(self, jour: date):
        for ticker in self.series:
            b = self._bougie(ticker, jour)
            if b is not None:
                self.derniers[ticker] = b.cloture
        total = self.liquidites + self._titres(jour, a_l_ouverture=False)
        indice_total = self.capital
        if self.indice_ordre is not None:
            cours = self.derniers[self.indice] * self._taux(self.meta[self.indice][0], jour, en_seance=False)
            indice_total = self.indice_liquidites + (self.indice_quantite * cours).quantize(
                CENTIME, ROUND_HALF_UP
            )
        self.courbe.append((jour, total, indice_total))

    def _rapport(self) -> Rapport:
        _, final, final_indice = self.courbe[-1]
        performance = ((final - self.capital) / self.capital).quantize(FRACTION, ROUND_HALF_UP)
        performance_indice = ((final_indice - self.capital) / self.capital).quantize(FRACTION, ROUND_HALF_UP)
        gagnantes = sum(1 for r in self.resultats if r > 0)
        return Rapport(
            debut=self.jours[0],
            fin=self.jours[-1],
            valeur_finale=final,
            performance=performance,
            performance_indice=performance_indice,
            ecart=performance - performance_indice,
            nb_positions=sum(1 for o in self.ordres if o.sens == "achat"),
            taux_gagnantes=(
                (Decimal(gagnantes) / len(self.resultats)).quantize(FRACTION, ROUND_HALF_UP)
                if self.resultats else Decimal(0)
            ),
            frais_total=sum((o.frais.total for o in self.ordres), Decimal(0)),
            tob_total=sum((o.frais.tob for o in self.ordres), Decimal(0)),
            perte_max=perte_max([total for _, total, _ in self.courbe]),
            courbe=self.courbe,
            ordres=self.ordres,
            indice_ordre=self.indice_ordre,
        )
