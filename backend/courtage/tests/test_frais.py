from decimal import Decimal

from django.test import SimpleTestCase

from courtage.frais import calculer_frais
from courtage.models import BaremeDonnees, RegleDonnees, TobDonnees

D = Decimal

# Valeurs inventées pour les tests, sans rapport avec un courtier réel.
BAREME = BaremeDonnees(
    broker="test",
    nom="Test",
    change_pourcentage=D("0.001"),
    change_minimum=D("2.00"),
    glissement=D("0.001"),
    regles=(
        RegleDonnees(("NYSE", "NASDAQ"), "USD", D("0.01"), D("0"), D("1.00"), D("0.01"), None),
        RegleDonnees(("XPAR",), "EUR", D("0"), D("0.002"), D("3.00"), None, D("20.00")),
    ),
    tob=(
        TobDonnees("action", D("0.0035"), D("1600.00")),
        TobDonnees("etf", D("0.0012"), D("1300.00")),
    ),
)


def frais(place, devise, type_titre, quantite, prix, taux="1"):
    return calculer_frais(BAREME, place, devise, type_titre, quantite, D(prix), D(taux))


class CalculerFraisTests(SimpleTestCase):
    def test_us_minimum_puis_par_action(self):
        # 10 x 0,01 = 0,10 < minimum 1,00 USD ; montant 1000 USD = 500 EUR.
        f = frais("NYSE", "USD", "action", 10, "100", "0.5")
        self.assertEqual(f.courtage, D("0.50"))  # 1,00 USD x 0,5
        self.assertEqual(f.change, D("2.00"))  # 500 EUR x 0,1 % = 0,50 < minimum
        self.assertEqual(f.tob, D("1.75"))  # 500 x 0,35 %
        self.assertEqual(f.total, D("4.25"))

    def test_us_par_action_depasse_minimum(self):
        f = frais("NASDAQ", "USD", "action", 500, "100", "1")
        self.assertEqual(f.courtage, D("5.00"))

    def test_us_plafond_pourcentage(self):
        # 1000 x 0,01 = 10 > 1 % de 100 USD = 1 : plafonné.
        f = frais("NYSE", "USD", "action", 1000, "0.10", "1")
        self.assertEqual(f.courtage, D("1.00"))

    def test_euronext_pourcentage_avec_minimum(self):
        self.assertEqual(frais("XPAR", "EUR", "action", 10, "100").courtage, D("3.00"))
        self.assertEqual(frais("XPAR", "EUR", "action", 50, "100").courtage, D("10.00"))

    def test_plafond_absolu(self):
        self.assertEqual(frais("XPAR", "EUR", "action", 1000, "100").courtage, D("20.00"))

    def test_change_seulement_hors_eur(self):
        self.assertEqual(frais("XPAR", "EUR", "action", 10, "100").change, D("0.00"))
        f = frais("NYSE", "USD", "action", 1000, "100", "1")
        self.assertEqual(f.change, D("100.00"))  # 100 000 x 0,1 %

    def test_tob_plafonnee(self):
        self.assertEqual(frais("XPAR", "EUR", "action", 10000, "100").tob, D("1600.00"))
        self.assertEqual(frais("XPAR", "EUR", "etf", 10000, "100").tob, D("1200.00"))
        self.assertEqual(frais("XPAR", "EUR", "etf", 100000, "100").tob, D("1300.00"))

    def test_arrondi_demi_superieur(self):
        bareme = BaremeDonnees(
            "t", "t", D("0"), D("0"), D("0"),
            (RegleDonnees(("XPAR",), "EUR", D("0"), D("0.001"), D("0.10"), None, None),),
            (TobDonnees("action", D("0.001"), D("100")),),
        )
        f = calculer_frais(bareme, "XPAR", "EUR", "action", 1, D("125"), D("1"))
        self.assertEqual(f.courtage, D("0.13"))  # 0,125 -> 0,13
        self.assertEqual(f.tob, D("0.13"))
        self.assertEqual(f.total, D("0.26"))

    def test_place_inconnue(self):
        with self.assertRaises(ValueError):
            frais("XMIL", "EUR", "action", 1, "10")
