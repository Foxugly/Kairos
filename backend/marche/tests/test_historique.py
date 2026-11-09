from datetime import UTC, datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from marche.models import Bougie, StatutValeur
from marche.tests.test_releve import SourceFactice, brute, valeur
from unittest import mock

J1 = datetime(2026, 11, 5, tzinfo=UTC)
J2 = datetime(2026, 11, 6, tzinfo=UTC)


def lancer(source, *args):
    sortie = StringIO()
    with mock.patch("marche.management.commands.historique.source_cours", return_value=source):
        call_command("historique", *args, stdout=sortie)
    return sortie.getvalue()


class HistoriqueTests(TestCase):
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
