from datetime import UTC, datetime
from unittest import mock

from django.test import TestCase

from cycle import deroulement
from cycle.models import StatutCycle
from portefeuille.execution import decider_du_jour, executer


class EtapesPlan2Tests(TestCase):
    def test_nouvelles_etapes_apres_la_collecte(self):
        self.assertEqual(
            [nom for nom, _ in deroulement.ETAPES], ["nouvelles", "cours", "decisions", "execution"]
        )
        etapes = dict(deroulement.ETAPES)
        self.assertIs(etapes["decisions"], decider_du_jour)
        self.assertIs(etapes["execution"], executer)

    def test_erreur_dans_l_execution_journalisee(self):
        def panne(maintenant):
            raise RuntimeError("broker en panne")

        # Collecte neutralisée (aucun appel réseau) ; l'étape « decisions » tourne pour de vrai.
        etapes = [
            (nom, {"nouvelles": lambda m: {}, "cours": lambda m: {}, "execution": panne}.get(nom, f))
            for nom, f in deroulement.ETAPES
        ]
        with (
            mock.patch.object(deroulement, "ETAPES", etapes),
            mock.patch.object(deroulement.sentry_sdk, "capture_exception"),
            self.assertLogs("cycle.deroulement", "ERROR"),
        ):
            cycle = deroulement.lancer(datetime(2026, 11, 10, 10, 0, tzinfo=UTC))
        cycle.refresh_from_db()
        self.assertEqual(cycle.statut, StatutCycle.EN_ERREUR)
        self.assertEqual(cycle.journal["execution"], {"erreur": "broker en panne"})
        self.assertIn("decisions", cycle.journal)
