from datetime import UTC, datetime
from decimal import Decimal

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings

from marche.admin import ValeurAdmin
from marche.models import Bougie, StatutValeur, Valeur


def creer_valeur(ticker, statut=StatutValeur.PROPOSEE):
    return Valeur.objects.create(
        ticker=ticker, nom=ticker, place="XPAR", devise="EUR", statut=statut
    )


class BougieTests(TestCase):
    def test_unicite_valeur_intervalle_debut(self):
        v = creer_valeur("TTE.PA")
        champs = dict(
            valeur=v, intervalle="5m", debut=datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
            ouverture=Decimal("1"), haut=Decimal("2"), bas=Decimal("1"),
            cloture=Decimal("2"), volume=10,
        )
        Bougie.objects.create(**champs)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Bougie.objects.create(**champs)


class ActiverTests(TestCase):
    def lancer(self, queryset):
        requete = RequestFactory().post("/")
        requete.user = get_user_model().objects.create_superuser("a@b.fr", "x")
        requete.session = {}
        requete._messages = messages.storage.fallback.FallbackStorage(requete)
        ValeurAdmin(Valeur, admin.site).activer(requete, queryset)
        return [str(m) for m in requete._messages], [m.level for m in requete._messages]

    @override_settings(UNIVERS_MAX=100)
    def test_refuse_de_depasser_l_univers(self):
        for i in range(99):
            creer_valeur(f"A{i}.PA", StatutValeur.ACTIVE)
        nouvelles = [creer_valeur(f"N{i}.PA") for i in range(3)]
        _, niveaux = self.lancer(Valeur.objects.filter(pk__in=[v.pk for v in nouvelles]))
        self.assertEqual(Valeur.objects.actives().count(), 99)
        self.assertIn(messages.ERROR, niveaux)

    @override_settings(UNIVERS_MAX=100)
    def test_active_une_valeur(self):
        for i in range(99):
            creer_valeur(f"A{i}.PA", StatutValeur.ACTIVE)
        v = creer_valeur("N.PA")
        self.lancer(Valeur.objects.filter(pk=v.pk))
        v.refresh_from_db()
        self.assertEqual(v.statut, StatutValeur.ACTIVE)
        self.assertEqual(Valeur.objects.actives().count(), 100)
