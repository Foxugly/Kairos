from datetime import UTC, datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from decimal import Decimal

from marche.models import Bougie, StatutValeur, TauxChange
from marche.tests.test_releve import SourceFactice, brute, valeur
from unittest import mock
from marche.tests.outils import repartir_de_zero

J1 = datetime(2026, 11, 5, tzinfo=UTC)
J2 = datetime(2026, 11, 6, tzinfo=UTC)


def lancer(source, *args):
    sortie = StringIO()
    with mock.patch("marche.management.commands.historique.source_cours", return_value=source):
        call_command("historique", *args, stdout=sortie)
    return sortie.getvalue()


class HistoriqueTests(TestCase):
    def setUp(self):
        repartir_de_zero()

    def test_enregistre_sans_doublon_et_compte_les_erreurs(self):
        valeur("AAPL", "NASDAQ", "USD")
        ref = valeur("IWDA.AS", "XAMS", "EUR", StatutValeur.INACTIVE)
        ref.reference = True
        ref.save()
        valeur("KO", "NYSE", "USD")
        valeur("PROP", "NYSE", "USD", StatutValeur.PROPOSEE)
        source = SourceFactice(
            bougies={("AAPL", "1d"): [brute(J1), brute(J2)], ("IWDA.AS", "1d"): [brute(J1)]},
            erreurs={"KO": "introuvable"},
        )
        sortie = lancer(source, "--jours", "400")
        self.assertIn("3 bougies pour 2 valeurs, 1 en erreur", sortie)
        self.assertEqual(Bougie.objects.filter(intervalle="1d").count(), 3)
        self.assertEqual(sorted(source.appels[0][0]), ["AAPL", "IWDA.AS", "KO"])
        lancer(source)
        self.assertEqual(Bougie.objects.count(), 3)

    def test_option_ticker(self):
        valeur("AAPL", "NASDAQ", "USD")
        valeur("MSFT", "NASDAQ", "USD")
        source = SourceFactice(bougies={("AAPL", "1d"): [brute(J1)]})
        lancer(source, "--ticker", "AAPL")
        self.assertEqual(source.appels[0][0], ["AAPL"])
        self.assertEqual(Bougie.objects.count(), 1)

    def test_taux_usd_journaliers_si_une_valeur_usd(self):
        valeur("AAPL", "NASDAQ", "USD")
        source = SourceFactice(bougies={("AAPL", "1d"): [brute(J1)]})
        source.taux = {"USD": [(J1, Decimal("0.8")), (J2, Decimal("0.81"))]}
        sortie = lancer(source)
        self.assertIn("2 taux USD journaliers", sortie)
        self.assertEqual(
            list(TauxChange.objects.order_by("instant").values_list("instant", "taux")),
            [(J1, Decimal("0.8")), (J2, Decimal("0.81"))],
        )
        lancer(source)
        self.assertEqual(TauxChange.objects.count(), 2)

    def test_pas_de_taux_sans_valeur_usd(self):
        valeur("TTE.PA", "XPAR", "EUR")
        source = SourceFactice(bougies={("TTE.PA", "1d"): [brute(J1)]})
        source.taux = {"USD": [(J1, Decimal("0.8"))]}
        lancer(source)
        self.assertFalse(TauxChange.objects.exists())
