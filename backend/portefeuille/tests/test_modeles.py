from datetime import UTC, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from marche.models import Valeur
from portefeuille.models import Portefeuille, Position


class PortefeuillesDepartTests(TestCase):
    def test_deux_portefeuilles_crees_par_la_migration(self):
        ia = Portefeuille.objects.get(nom="IA")
        technique = Portefeuille.objects.get(nom="Technique")
        self.assertTrue(ia.utilise_ia)
        self.assertFalse(technique.utilise_ia)
        for p in (ia, technique):
            self.assertEqual(p.capital_initial, Decimal("10000"))
            self.assertEqual(p.liquidites, Decimal("10000"))
            self.assertEqual(p.indice.ticker, "IWDA.AS")
            self.assertEqual(p.bareme_broker, "ibkr")
            self.assertEqual(p.broker, "simule")

    def test_valeurs_par_defaut_des_regles(self):
        p = Portefeuille.objects.get(nom="IA")
        self.assertEqual(p.part_max, Decimal("0.05"))
        self.assertEqual(p.positions_max, 20)
        self.assertEqual(p.score_achat, 2)
        self.assertEqual(p.budget_ia_mensuel, Decimal("40"))


class PositionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.portefeuille = Portefeuille.objects.get(nom="Technique")
        cls.valeur = Valeur.objects.create(ticker="TTE.PA", nom="TotalEnergies", place="XPAR", devise="EUR")

    def creer(self, **kw):
        base = dict(
            portefeuille=self.portefeuille,
            valeur=self.valeur,
            quantite=10,
            prix_entree=Decimal("50.0000"),
            taux_entree=Decimal("1"),
            cout_entree_eur=Decimal("503.00"),
            plus_haut=Decimal("50.0000"),
            ouverte_le=datetime(2026, 11, 10, tzinfo=UTC),
        )
        base.update(kw)
        return Position.objects.create(**base)

    def test_deux_positions_ouvertes_sur_la_meme_valeur_refusees(self):
        self.creer()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.creer()

    def test_une_ouverte_et_une_fermee_acceptees(self):
        self.creer(fermee_le=datetime(2026, 11, 12, tzinfo=UTC))
        self.creer()
        self.assertEqual(Position.objects.count(), 2)

    def test_resultat_position_fermee(self):
        p = self.creer(
            fermee_le=datetime(2026, 11, 12, tzinfo=UTC),
            prix_sortie=Decimal("55.0000"),
            produit_sortie_eur=Decimal("546.50"),
        )
        self.assertEqual(p.resultat_eur, Decimal("43.50"))

    def test_resultat_position_ouverte_est_none(self):
        self.assertIsNone(self.creer().resultat_eur)
