from decimal import Decimal

from django.test import SimpleTestCase

from analyse.indicateurs import moyenne_mobile, rsi


def _d(valeurs):
    return [Decimal(str(v)) for v in valeurs]


class MoyenneMobileTests(SimpleTestCase):
    def test_moyenne_de_trois_points(self):
        self.assertEqual(moyenne_mobile(_d([1, 2, 3]), 3), Decimal("2"))

    def test_utilise_les_n_derniers_points(self):
        self.assertEqual(moyenne_mobile(_d([100, 1, 2, 3]), 3), Decimal("2"))

    def test_pas_assez_de_points(self):
        self.assertIsNone(moyenne_mobile(_d([1, 2]), 3))


class RsiTests(SimpleTestCase):
    def test_serie_toujours_haussiere(self):
        self.assertEqual(rsi(_d(range(1, 20)), 14), Decimal("100"))

    def test_pas_assez_de_points(self):
        self.assertIsNone(rsi(_d(range(1, 15)), 14))

    def test_valeur_de_reference_calculee_a_la_main(self):
        # n=3, cours 10, 11, 10, 12, 11 -> variations +1, -1, +2, -1.
        # Moyenne simple des 3 premières : gain (1+0+2)/3 = 1, perte (0+1+0)/3 = 1/3.
        # Lissage de Wilder avec la 4e variation (-1) :
        # gain = (1*2 + 0)/3 = 2/3 ; perte = ((1/3)*2 + 1)/3 = 5/9.
        # RS = (2/3)/(5/9) = 1,2 ; RSI = 100 - 100/2,2 = 54,545... -> 54,55.
        self.assertEqual(rsi(_d([10, 11, 10, 12, 11]), 3), Decimal("54.55"))
