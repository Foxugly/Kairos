from django.test import TestCase, override_settings

from marche.models import StatutValeur, TypeTitre, Valeur
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from marche.admin import ValeurAdmin
from marche.tests.test_modeles import creer_valeur
from marche.tests.test_proposer_univers import lancer


class ReferenceTests(TestCase):
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
