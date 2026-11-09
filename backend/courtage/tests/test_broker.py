from datetime import date
from decimal import Decimal

from django.test import TestCase

from courtage.broker import BrokerSimule, OrdreDemande, broker
from courtage.frais import DetailFrais
from portefeuille.strategie import Cotation

JOUR = date(2026, 11, 10)


def cotation(prix, devise="EUR", place="XPAR", taux="1"):
    return Cotation(
        prix=Decimal(prix), devise=devise, place=place, type_titre="action", taux_eur=Decimal(taux)
    )


class BrokerSimuleTests(TestCase):
    def test_registre(self):
        self.assertIsInstance(broker("simule"), BrokerSimule)
        self.assertEqual(broker("simule").code, "simule")
        with self.assertRaises(KeyError):
            broker("inconnu")

    def test_achat_avec_glissement_defavorable_et_frais_du_bareme(self):
        ordre = OrdreDemande("achat", "TTE.PA", 10, cotation("100"), "ibkr", JOUR)
        execution = BrokerSimule().executer(ordre)
        self.assertEqual(execution.prix, Decimal("100.1000"))
        self.assertEqual(execution.montant_eur, Decimal("1001.00"))
        # Courtage : minimum 3 EUR ; TOB : 0,35 % de 1 001 = 3,5035 -> 3,50.
        self.assertEqual(
            execution.frais,
            DetailFrais(Decimal("3.00"), Decimal("0.00"), Decimal("3.50"), Decimal("6.50")),
        )
        self.assertEqual(BrokerSimule().estimer(ordre), execution.frais)

    def test_vente_avec_glissement_defavorable(self):
        ordre = OrdreDemande("vente", "TTE.PA", 10, cotation("94"), "ibkr", JOUR)
        execution = BrokerSimule().executer(ordre)
        self.assertEqual(execution.prix, Decimal("93.9060"))
        self.assertEqual(execution.montant_eur, Decimal("939.06"))
        self.assertEqual(execution.frais.total, Decimal("6.29"))

    def test_valeur_usd_convertie(self):
        ordre = OrdreDemande("achat", "AAPL", 5, cotation("200", "USD", "NASDAQ", "0.9"), "ibkr", JOUR)
        execution = BrokerSimule().executer(ordre)
        self.assertEqual(execution.prix, Decimal("200.2000"))
        self.assertEqual(execution.taux_eur, Decimal("0.9"))
        self.assertEqual(execution.montant_eur, Decimal("900.90"))
        # Courtage 1 USD -> 0,90 EUR ; change : minimum 2 EUR ; TOB 3,15.
        self.assertEqual(
            execution.frais,
            DetailFrais(Decimal("0.90"), Decimal("2.00"), Decimal("3.15"), Decimal("6.05")),
        )

    def test_place_sans_regle_leve_value_error(self):
        ordre = OrdreDemande("achat", "X", 1, cotation("10", place="XLON"), "ibkr", JOUR)
        with self.assertRaises(ValueError):
            BrokerSimule().estimer(ordre)
