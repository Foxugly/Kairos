from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from marche.models import TauxChange, Valeur
from marche.releve import enregistrer_isole
from sources.registre import source_cours


class Command(BaseCommand):
    help = "Charge l'historique journalier (bougies 1d) des valeurs à relever, et du taux USD si besoin."

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=400)
        parser.add_argument("--ticker", help="Limite le chargement à ce ticker.")

    def handle(self, *args, **options):
        valeurs = Valeur.objects.a_relever()
        if options["ticker"]:
            valeurs = valeurs.filter(ticker=options["ticker"])
        valeurs = list(valeurs)
        if not valeurs:
            raise CommandError("aucune valeur à relever")
        source = source_cours()
        depuis = timezone.now() - timedelta(days=options["jours"])
        # Une seule requête pour toutes les valeurs ; l'enregistrement est idempotent.
        par_ticker = source.bougies([v.ticker for v in valeurs], "1d", depuis)
        erreurs = dict(source.erreurs)
        total = enregistrer_isole(valeurs, "1d", par_ticker, erreurs)
        self.stdout.write(
            f"{total} bougies pour {len(valeurs) - len(erreurs)} valeurs, {len(erreurs)} en erreur"
        )
        if any(v.devise == "USD" for v in valeurs):
            self._taux_usd(source, depuis)

    def _taux_usd(self, source, depuis):
        """Taux USD de clôture de chaque jour (backtest), à minuit UTC de la date comme les bougies 1d."""
        taux = source.taux_journaliers("USD", depuis)
        TauxChange.objects.bulk_create(
            [TauxChange(devise="USD", instant=instant, taux=t) for instant, t in taux],
            update_conflicts=True, unique_fields=["devise", "instant"], update_fields=["taux"],
        )
        erreur = source.erreurs.get("USD")
        self.stdout.write(f"{len(taux)} taux USD journaliers" + (f" ({erreur})" if erreur else ""))
