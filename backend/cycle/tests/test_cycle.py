from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from cycle import deroulement
from cycle.models import Cycle, StatutCycle, Verrou


class LancerTests(TestCase):
    def test_etapes_dans_l_ordre_et_journal(self):
        appels = []

        def a(maintenant):
            appels.append(("a", maintenant))
            return {"n": 1}

        def b(maintenant):
            appels.append(("b", maintenant))
            return {"n": 2}

        now = timezone.now()
        with mock.patch.object(deroulement, "ETAPES", [("a", a), ("b", b)]):
            cycle = deroulement.lancer(now)
        self.assertEqual(appels, [("a", now), ("b", now)])
        self.assertEqual(cycle.statut, StatutCycle.TERMINE)
        self.assertEqual(cycle.journal, {"a": {"n": 1}, "b": {"n": 2}})
        self.assertIsNotNone(cycle.fin)

    def test_ligne_verrou_manquante_recreee(self):
        Verrou.objects.all().delete()
        with mock.patch.object(deroulement, "ETAPES", []):
            cycle = deroulement.lancer(timezone.now())
        self.assertEqual(cycle.statut, StatutCycle.TERMINE)
        self.assertTrue(Verrou.objects.filter(pk=1).exists())

    def test_etape_qui_leve_n_arrete_pas_les_suivantes(self):
        def a(maintenant):
            raise RuntimeError("panne")

        with (
            mock.patch.object(deroulement, "ETAPES", [("a", a), ("b", lambda m: {"ok": True})]),
            mock.patch.object(deroulement.sentry_sdk, "capture_exception") as sentry,
        ):
            cycle = deroulement.lancer()
        self.assertEqual(cycle.statut, StatutCycle.EN_ERREUR)
        self.assertEqual(cycle.journal["a"], {"erreur": "panne"})
        self.assertEqual(cycle.journal["b"], {"ok": True})
        sentry.assert_called_once()

    def test_resultat_non_serialisable_converti(self):
        now = timezone.now()
        with mock.patch.object(deroulement, "ETAPES", [("a", lambda m: {"quand": m})]):
            cycle = deroulement.lancer(now)
        cycle.refresh_from_db()
        self.assertIsInstance(cycle.journal["a"]["quand"], str)

    def test_cycle_recent_en_cours_bloque(self):
        now = timezone.now()
        Cycle.objects.create(debut=now - timedelta(minutes=3))
        etape = mock.Mock(return_value={})
        with mock.patch.object(deroulement, "ETAPES", [("a", etape)]):
            self.assertIsNone(deroulement.lancer(now))
        etape.assert_not_called()
        self.assertEqual(Cycle.objects.count(), 1)

    def test_cycle_ancien_abandonne(self):
        now = timezone.now()
        vieux = Cycle.objects.create(debut=now - timedelta(minutes=11))
        with mock.patch.object(deroulement, "ETAPES", [("a", lambda m: {})]):
            cycle = deroulement.lancer(now)
        vieux.refresh_from_db()
        self.assertEqual(vieux.statut, StatutCycle.ABANDONNE)
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle.statut, StatutCycle.TERMINE)

    def test_purge_a_30_jours(self):
        now = timezone.now()
        ancien = Cycle.objects.create(debut=now - timedelta(days=31), statut=StatutCycle.TERMINE)
        with mock.patch.object(deroulement, "ETAPES", []):
            deroulement.lancer(now)
        self.assertFalse(Cycle.objects.filter(pk=ancien.pk).exists())
