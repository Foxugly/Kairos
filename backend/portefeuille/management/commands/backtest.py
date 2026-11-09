from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from analyse.signaux import BougieJour
from courtage.models import Bareme
from marche.models import Bougie, TauxChange, Valeur
from portefeuille.backtest import Rapport, rejouer
from portefeuille.models import Portefeuille, ResultatBacktest
from portefeuille.strategie import Regles

# Bougies lues avant `--depuis`, pour que les signaux du premier jour aient leur historique (≈ 120 séances).
AMORCE = timedelta(days=200)


def _pourcent(fraction: Decimal, signe: bool = True) -> str:
    return f"{fraction * 100:{'+' if signe else ''}.2f} %".replace(".", ",")


def _euros(montant: Decimal) -> str:
    return f"{montant:,.2f} €".replace(",", " ").replace(".", ",")


def taux_usd_journaliers() -> dict[date, Decimal]:
    """Taux USD de clôture par jour (chargés par `historique`, à minuit UTC).

    Les taux relevés en séance par le cycle sont écartés : ils ne remplacent jamais la clôture du jour.
    """
    return {
        instant.date(): taux
        for instant, taux in TauxChange.objects.filter(devise="USD").values_list("instant", "taux")
        if instant.astimezone(UTC).time() == time(0)
    }


def _il_y_a_cinq_ans() -> date:
    aujourdhui = date.today()
    try:
        return aujourdhui.replace(year=aujourdhui.year - 5)
    except ValueError:  # 29 février
        return aujourdhui.replace(year=aujourdhui.year - 5, day=28)


class Command(BaseCommand):
    help = "Rejoue les règles techniques d'un portefeuille sur les bougies 1d en base (voir `historique`)."

    def add_arguments(self, parser):
        parser.add_argument("--depuis", type=date.fromisoformat, help="AAAA-MM-JJ (défaut : il y a 5 ans)")
        parser.add_argument("--portefeuille", default="Technique")

    def handle(self, *args, **options):
        depuis = options["depuis"] or _il_y_a_cinq_ans()
        try:
            p = Portefeuille.objects.select_related("indice").get(nom=options["portefeuille"])
        except Portefeuille.DoesNotExist:
            raise CommandError(f"portefeuille inconnu : {options['portefeuille']}") from None
        # Le barème du jour vaut pour toute la période : aucun barème historique n'est saisi.
        try:
            bareme = Bareme.en_vigueur(p.bareme_broker, date.today())
        except IndexError:
            raise CommandError(f"aucun barème {p.bareme_broker} en vigueur") from None

        valeurs = list(Valeur.objects.actives().filter(reference=False)) + [p.indice]
        series = self._series(valeurs, depuis)
        if not any(b.jour >= depuis for bougies in series.values() for b in bougies):
            raise CommandError("aucune bougie 1d sur la période : lancer `manage.py historique` d'abord")
        taux_usd = taux_usd_journaliers()
        meta = {v.ticker: (v.devise, v.place, v.type_titre) for v in valeurs}
        regles = Regles.depuis(p)
        rapport = rejouer(
            series, meta, taux_usd, regles, bareme.donnees(), p.capital_initial, p.indice.ticker,
            debut=depuis,
        )
        self._enregistrer(p, regles, bareme, rapport)
        nb_valeurs = sum(1 for ticker in series if ticker != p.indice.ticker)
        self._afficher(p, bareme, rapport, nb_valeurs)

    @staticmethod
    def _series(valeurs, depuis: date) -> dict[str, list[BougieJour]]:
        series: dict[str, list[BougieJour]] = {}
        debut = datetime(depuis.year, depuis.month, depuis.day, tzinfo=UTC) - AMORCE
        lignes = (
            Bougie.objects.filter(valeur__in=valeurs, intervalle="1d", debut__gte=debut)
            .order_by("valeur__ticker", "debut")
            .values_list("valeur__ticker", "debut", "ouverture", "haut", "bas", "cloture")
        )
        for ticker, instant, ouverture, haut, bas, cloture in lignes:
            series.setdefault(ticker, []).append(BougieJour(instant.date(), ouverture, haut, bas, cloture))
        return series

    @staticmethod
    def _enregistrer(p, regles: Regles, bareme: Bareme, r: Rapport):
        ResultatBacktest.objects.create(
            portefeuille=p, regles={k: str(v) for k, v in asdict(regles).items()},
            capital=p.capital_initial, indice=p.indice.ticker, bareme=bareme.nom,
            debut=r.debut, fin=r.fin, valeur_finale=r.valeur_finale, performance=r.performance,
            performance_indice=r.performance_indice, ecart=r.ecart, nb_positions=r.nb_positions,
            taux_gagnantes=r.taux_gagnantes, frais_total=r.frais_total, tob_total=r.tob_total,
            perte_max=r.perte_max,
            courbe=[[jour.isoformat(), str(total), str(indice)] for jour, total, indice in r.courbe],
        )

    def _afficher(self, p, bareme: Bareme, r: Rapport, nb_valeurs: int):
        lignes = [
            f"Backtest du portefeuille {p.nom} du {r.debut} au {r.fin} ({len(r.courbe)} séances, "
            f"{nb_valeurs} valeurs)",
            f"Barème : {bareme.nom} — barème en vigueur aujourd'hui, appliqué à toute la période",
            f"Capital initial      : {_euros(p.capital_initial)}",
            f"Valeur finale        : {_euros(r.valeur_finale)}",
            f"Performance          : {_pourcent(r.performance)}",
            f"Indice ({p.indice.ticker})  : {_pourcent(r.performance_indice)}",
            f"Écart                : {_pourcent(r.ecart)}",
            f"Positions prises     : {r.nb_positions}",
            f"Positions gagnantes  : {_pourcent(r.taux_gagnantes, signe=False)} des positions fermées",
            f"Frais totaux         : {_euros(r.frais_total)} (dont TOB {_euros(r.tob_total)}), hors achat de "
            "l'indice, compté dans sa performance",
            f"Perte maximale       : {_pourcent(r.perte_max, signe=False)} depuis un sommet",
        ]
        self.stdout.write("\n".join(lignes))
