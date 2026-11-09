from django.test import TestCase

from marche.models import Valeur
from sources.rattachement import valeurs_citees


def v(ticker, alias):
    return Valeur.objects.create(
        ticker=ticker, nom=alias, alias=alias, place="NASDAQ", devise="USD"
    )


class ValeursCiteesTests(TestCase):
    def setUp(self):
        self.toutes = [
            v("AAPL", "Apple"), v("NVDA", "Nvidia"), v("TTE.PA", "TotalEnergies"),
            v("META", "Meta"), v("OR.PA", "L'Oréal"), v("V", "Visa Inc"),
        ]

    def tickers(self, texte):
        return {x.ticker for x in valeurs_citees(texte, self.toutes)}
    def test_alias(self):
        self.assertEqual(self.tickers("Apple bat les attentes"), {"AAPL"})
        self.assertEqual(self.tickers("TotalEnergies relève sa prévision"), {"TTE.PA"})

    def test_mot_entier(self):
        self.assertEqual(self.tickers("pineapple"), set())
        self.assertEqual(self.tickers("metadata"), set())
        self.assertEqual(self.tickers("Appleé"), set())

    def test_sensible_a_la_casse(self):
        self.assertEqual(self.tickers("apple et nvidia"), set())

    def test_formes_ticker(self):
        self.assertEqual(self.tickers("$NVDA grimpe"), {"NVDA"})
        self.assertEqual(self.tickers("Le titre (AAPL) recule"), {"AAPL"})
        self.assertEqual(self.tickers("NASDAQ: NVDA en hausse"), {"NVDA"})
        self.assertEqual(self.tickers("NYSE:V monte"), {"V"})
        self.assertEqual(self.tickers("NVDA seul"), set())

    def test_ticker_en_fin_de_phrase(self):
        self.assertEqual(self.tickers("Wall Street : tout grimpe $NVDA."), {"NVDA"})
        self.assertEqual(self.tickers("Cotation sur NASDAQ: AAPL."), {"AAPL"})
        # `V` reste distinct d'un ticker à suffixe comme `V.PA`.
        self.assertEqual(self.tickers("$V.PA recule"), set())

    def test_forme_parentheses_ignoree_pour_ticker_d_une_lettre(self):
        # « (C) 2026 Reuters » ne doit pas citer Citigroup, ni « (V) » Visa.
        self.assertEqual(self.tickers("(V) monte"), set())
        self.assertEqual(self.tickers("(C) 2026 Reuters"), set())
        self.assertEqual(self.tickers("$V monte"), {"V"})

    def test_apostrophes_typographiques(self):
        self.assertEqual(self.tickers("L’Oréal publie ses comptes"), {"OR.PA"})

    def test_alias_avec_espace(self):
        self.assertEqual(self.tickers("Visa Inc annonce"), {"V"})

    def test_plusieurs_valeurs(self):
        self.assertEqual(self.tickers("Apple et Nvidia"), {"AAPL", "NVDA"})
