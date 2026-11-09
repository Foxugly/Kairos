from datetime import date
from decimal import Decimal

from django.test import TestCase

from courtage.models import Bareme, BaremeDonnees, RegleCourtage, TauxTob


class BaremeTests(TestCase):
    def test_en_vigueur_selon_la_date(self):
        ancien = Bareme.objects.create(broker="test", nom="Ancien", valide_depuis=date(2020, 1, 1))
        nouveau = Bareme.objects.create(broker="test", nom="Nouveau", valide_depuis=date(2024, 6, 1))
        self.assertEqual(Bareme.en_vigueur("test", date(2023, 12, 31)), ancien)
        self.assertEqual(Bareme.en_vigueur("test", date(2024, 6, 1)), nouveau)
        with self.assertRaisesMessage(Bareme.DoesNotExist, "aucun barème test en vigueur le 2019-01-01"):
            Bareme.en_vigueur("test", date(2019, 1, 1))

    def test_donnees_fige(self):
        b = Bareme.objects.create(broker="test", nom="B", valide_depuis=date(2020, 1, 1))
        RegleCourtage.objects.create(
            bareme=b, places="XPAR, XAMS", devise="EUR", pourcentage=Decimal("0.0005"),
            minimum=Decimal("3"),
        )
        TauxTob.objects.create(
            bareme=b, type_titre="action", taux=Decimal("0.0035"), plafond=Decimal("1600")
        )
        d = b.donnees()
        self.assertIsInstance(d, BaremeDonnees)
        self.assertEqual(d.regles[0].places, ("XPAR", "XAMS"))
        self.assertIsNone(d.regles[0].maximum)
        self.assertEqual(d.tob[0].plafond, Decimal("1600.00"))
        hash(d)
        with self.assertRaises(AttributeError):
            d.broker = "autre"


class BaremeIbkrTests(TestCase):
    def test_bareme_ibkr_charge_par_la_migration(self):
        from courtage.frais import calculer_frais

        d = Bareme.en_vigueur("ibkr", date(2026, 12, 1)).donnees()
        self.assertIn("2026-11-09", Bareme.en_vigueur("ibkr", date(2026, 12, 1)).notes)
        f = calculer_frais(d, "NYSE", "USD", "action", 10, Decimal("100"), Decimal("0.9"))
        self.assertEqual(f.courtage, Decimal("0.90"))
        paris = {p for r in d.regles for p in r.places}
        self.assertEqual(paris, {"NASDAQ", "NYSE", "XPAR", "XAMS", "XBRU", "XETR", "XMIL", "XMAD", "XHEL", "XDUB"})
