import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase

from config import settings as module_reglages


class SanteTests(TestCase):
    def test_sante_ok(self):
        reponse = self.client.get("/health/")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["status"], "ok")
        self.assertTrue(reponse.json()["checks"]["db"]["ok"])

    def test_sante_503_quand_la_base_manque(self):
        with mock.patch("config.sante.connection.cursor", side_effect=DatabaseError):
            reponse = self.client.get("/health/")
        self.assertEqual(reponse.status_code, 503)
        self.assertEqual(reponse.json()["status"], "degraded")
        self.assertFalse(reponse.json()["checks"]["db"]["ok"])


class ReglagesTests(SimpleTestCase):
    def test_csrf_lisible_par_angular(self):
        self.assertEqual(settings.CSRF_COOKIE_NAME, "XSRF-TOKEN")
        self.assertEqual(settings.CSRF_HEADER_NAME, "HTTP_X_XSRF_TOKEN")
        self.assertFalse(settings.CSRF_COOKIE_HTTPONLY)

    def test_univers_max(self):
        self.assertEqual(settings.UNIVERS_MAX, 100)

    def test_version_par_defaut(self):
        self.assertTrue(settings.VERSION)


class VersionTests(SimpleTestCase):
    def test_version_depuis_l_environnement_d_abord(self):
        with mock.patch.dict(os.environ, {"SENTRY_RELEASE": " abc123 "}):
            self.assertEqual(module_reglages._version_deployee(), "abc123")

    def test_version_depuis_le_fichier_release(self):
        with mock.patch.dict(os.environ, {"SENTRY_RELEASE": ""}), mock.patch.object(
            Path, "read_text", return_value="def456\n"
        ):
            self.assertEqual(module_reglages._version_deployee(), "def456")

    def test_version_vide_sans_rien(self):
        with mock.patch.dict(os.environ, {"SENTRY_RELEASE": ""}), mock.patch.object(
            Path, "read_text", side_effect=FileNotFoundError
        ):
            self.assertEqual(module_reglages._version_deployee(), "")
