from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase

from analyse.signaux import BougieJour, Sens, Signal, score, signaux_du_jour


def _bougies(clotures, ecart=Decimal("0.5")):
    debut = date(2026, 1, 1)
    return [
        BougieJour(debut + timedelta(days=i), c, c + ecart, c - ecart, c)
        for i, c in enumerate(clotures)
    ]


def _codes(signaux):
    return {s.code: s.sens for s in signaux}


class SignauxDuJourTests(SimpleTestCase):
    def test_liste_vide(self):
        self.assertEqual(signaux_du_jour([]), [])

    def test_croisement_haussier_le_jour_exact(self):
        # 50 clôtures à 100 puis une forte hausse : MM20 passe au-dessus de MM50 ce jour-là.
        serie = [Decimal(100)] * 50
        avant = signaux_du_jour(_bougies(serie))
        self.assertNotIn("croisement_mm", _codes(avant))
        jour = signaux_du_jour(_bougies(serie + [Decimal(130)]))
        self.assertEqual(_codes(jour)["croisement_mm"], Sens.ACHAT)
        lendemain = signaux_du_jour(_bougies(serie + [Decimal(130), Decimal(131)]))
        self.assertNotIn("croisement_mm", _codes(lendemain))

    def test_croisement_baissier(self):
        serie = [Decimal(100)] * 50 + [Decimal(70)]
        signal = next(s for s in signaux_du_jour(_bougies(serie)) if s.code == "croisement_mm")
        self.assertEqual(signal.sens, Sens.VENTE)
        self.assertIn("MM20", signal.detail)

    def test_cassure_a_la_hausse(self):
        serie = [Decimal(100)] * 20 + [Decimal(101)]
        codes = _codes(signaux_du_jour(_bougies(serie)))
        self.assertEqual(codes["cassure"], Sens.ACHAT)

    def test_cassure_a_la_baisse(self):
        serie = [Decimal(100)] * 20 + [Decimal(99)]
        codes = _codes(signaux_du_jour(_bougies(serie)))
        self.assertEqual(codes["cassure"], Sens.VENTE)

    def test_trente_bougies_sans_croisement(self):
        serie = [Decimal(100 + i) for i in range(30)]
        codes = _codes(signaux_du_jour(_bougies(serie)))
        self.assertNotIn("croisement_mm", codes)
        self.assertEqual(codes["rsi"], Sens.VENTE)
        self.assertEqual(codes["cassure"], Sens.ACHAT)

    def test_rsi_survendu_donne_achat(self):
        serie = [Decimal(200 - i) for i in range(30)]
        self.assertEqual(_codes(signaux_du_jour(_bougies(serie)))["rsi"], Sens.ACHAT)


class ScoreTests(SimpleTestCase):
    def test_score(self):
        a = Signal("rsi", Sens.ACHAT, "x")
        v = Signal("cassure", Sens.VENTE, "y")
        self.assertEqual(score([a, a, v]), 1)
        self.assertEqual(score([]), 0)
