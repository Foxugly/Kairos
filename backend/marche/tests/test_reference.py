from django.test import TestCase, override_settings

from marche.models import StatutValeur, TypeTitre, Valeur
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from marche.admin import ValeurAdmin
from marche.tests.test_modeles import creer_valeur
from marche.tests.test_proposer_univers import lancer
from marche.tests.outils import repartir_de_zero


class ReferenceTests(TestCase):
    def setUp(self):
        repartir_de_zero()

    def test_defauts(self):
        v = creer_valeur("TTE.PA")
        self.assertFalse(v.reference)
        self.assertEqual(v.type_titre, TypeTitre.ACTION)

    def test_a_relever_inclut_la_reference_inactive_et_exclut_la_proposee(self):
        active = creer_valeur("A.PA", StatutValeur.ACTIVE)
        ref = creer_valeur("IWDA.AS", StatutValeur.INACTIVE)
        ref.reference = True
        ref.save()
        proposee = creer_valeur("P.PA")
        a_relever = set(Valeur.objects.a_relever())
        self.assertEqual(a_relever, {active, ref})
        self.assertNotIn(proposee, a_relever)

    def test_a_relever_inclut_une_valeur_inactive_detenue(self):
        from datetime import UTC, datetime
        from decimal import Decimal

        from portefeuille.models import Portefeuille, Position

        ref = creer_valeur("IWDA.AS", StatutValeur.ACTIVE)
        ref.reference = True
        ref.save()
        detenue = creer_valeur("D.PA", StatutValeur.INACTIVE)
        vendue = creer_valeur("V.PA", StatutValeur.INACTIVE)
        creer_valeur("N.PA", StatutValeur.INACTIVE)
        p = Portefeuille.objects.create(nom="T", indice=ref)
        instant = datetime(2026, 11, 2, tzinfo=UTC)
        for valeur, fermee in ((detenue, None), (vendue, instant)):
            Position.objects.create(
                portefeuille=p, valeur=valeur, quantite=1, prix_entree=Decimal(1), taux_entree=Decimal(1),
                cout_entree_eur=Decimal(1), plus_haut=Decimal(1), ouverte_le=instant, fermee_le=fermee,
            )
        autre = Portefeuille.objects.create(nom="U", indice=ref)
        Position.objects.create(
            portefeuille=autre, valeur=detenue, quantite=1, prix_entree=Decimal(1), taux_entree=Decimal(1),
            cout_entree_eur=Decimal(1), plus_haut=Decimal(1), ouverte_le=instant,
        )
        # Une valeur désactivée encore détenue reste relevée, une seule fois ; vendue, elle ne l'est plus.
        self.assertEqual(list(Valeur.objects.a_relever().order_by("ticker")), [detenue, ref])

    def test_proposer_univers_cree_iwda(self):
        lancer()
        iwda = Valeur.objects.get(ticker="IWDA.AS")
        self.assertTrue(iwda.reference)
        self.assertEqual(iwda.type_titre, TypeTitre.ETF)
        self.assertEqual((iwda.place, iwda.devise, iwda.alias), ("XAMS", "EUR", ""))
        self.assertFalse(iwda.imposee)
        self.assertEqual(Valeur.objects.filter(reference=True).count(), 1)
        self.assertEqual(Valeur.objects.get(ticker="AAPL").type_titre, TypeTitre.ACTION)


class ActiverReferenceTests(TestCase):
    def setUp(self):
        repartir_de_zero()

    def lancer(self, queryset):
        requete = RequestFactory().post("/")
        requete.user = get_user_model().objects.create_superuser("a@b.fr", "x")
        requete.session = {}
        requete._messages = FallbackStorage(requete)
        ValeurAdmin(Valeur, admin.site).activer(requete, queryset)

    @override_settings(UNIVERS_MAX=100)
    def test_la_reference_n_est_pas_comptee(self):
        for i in range(99):
            creer_valeur(f"A{i}.PA", StatutValeur.ACTIVE)
        ref = creer_valeur("IWDA.AS", StatutValeur.ACTIVE)
        ref.reference = True
        ref.save()
        v = creer_valeur("N.PA")
        self.lancer(Valeur.objects.filter(pk=v.pk))
        v.refresh_from_db()
        self.assertEqual(v.statut, StatutValeur.ACTIVE)  # 100 hors référence
