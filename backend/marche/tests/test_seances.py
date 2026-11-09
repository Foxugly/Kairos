from datetime import UTC, datetime

from django.test import SimpleTestCase

from marche.seances import FUSEAU_PLACE, en_seance


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class EnSeanceTests(SimpleTestCase):
    def test_nasdaq_ouvert_et_ferme(self):
        self.assertTrue(en_seance("NASDAQ", utc(2026, 11, 9, 15, 0)))  # 10:00 à New York
        self.assertFalse(en_seance("NASDAQ", utc(2026, 11, 9, 21, 30)))

    def test_paris_et_week_end(self):
        self.assertTrue(en_seance("XPAR", utc(2026, 11, 9, 8, 30)))
        self.assertFalse(en_seance("XPAR", utc(2026, 11, 8, 12, 0)))  # dimanche

    def test_decalage_d_heure(self):
        # New York est déjà à l'heure d'été (09:45), Paris encore à l'heure d'hiver (17:45).
        self.assertTrue(en_seance("NYSE", utc(2026, 3, 9, 13, 45)))
        self.assertFalse(en_seance("XPAR", utc(2026, 3, 9, 16, 45)))

    def test_bornes(self):
        self.assertTrue(en_seance("XPAR", utc(2026, 11, 9, 8, 0)))  # ouverture 09:00 incluse
        self.assertFalse(en_seance("XPAR", utc(2026, 11, 9, 7, 59)))
        self.assertTrue(en_seance("XPAR", utc(2026, 11, 9, 16, 29)))
        self.assertFalse(en_seance("XPAR", utc(2026, 11, 9, 16, 30)))  # fermeture 17:30 exclue

    def test_toutes_les_places_ont_un_fuseau(self):
        from marche.models import Place

        self.assertEqual(set(FUSEAU_PLACE), set(Place.values))
