import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from marche.models import StatutValeur, Valeur
from marche.tests.outils import repartir_de_zero

IMPOSEES = {"AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TTE.PA", "TSLA"}


def lancer(*args):
    sortie = StringIO()
    call_command("proposer_univers", *args, stdout=sortie)
    return sortie.getvalue()


def fichier_csv(contenu):
    dossier = tempfile.mkdtemp()
    chemin = Path(dossier) / "univers.csv"
    chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


class ProposerUniversTests(TestCase):
    def setUp(self):
        repartir_de_zero()

    def test_cree_tout_l_univers(self):
        sortie = lancer()
        total = Valeur.objects.count()
        self.assertTrue(140 <= total <= 160)
        self.assertIn(f"{total} valeurs créées, 0 mises à jour", sortie)
        imposees = Valeur.objects.filter(imposee=True)
        self.assertEqual({v.ticker for v in imposees}, IMPOSEES)
        self.assertTrue(all(v.statut == StatutValeur.ACTIVE for v in imposees))
        autres = Valeur.objects.filter(imposee=False)
        self.assertTrue(all(v.statut == StatutValeur.PROPOSEE for v in autres))

    def test_relance_conserve_le_statut_et_met_a_jour_nom_et_alias(self):
        lancer()
        Valeur.objects.filter(ticker="ABBV").update(
            statut=StatutValeur.INACTIVE, nom="Ancien nom", alias="Ancien"
        )
        lancer()
        abbv = Valeur.objects.get(ticker="ABBV")
        self.assertEqual(abbv.statut, StatutValeur.INACTIVE)
        self.assertEqual(abbv.nom, "AbbVie")
        self.assertEqual(abbv.alias, "AbbVie")

    def test_relance_signale_les_mises_a_jour(self):
        lancer()
        sortie = lancer()
        self.assertIn("0 valeurs créées", sortie)

    def test_place_inconnue_echoue_sans_rien_ecrire(self):
        chemin = fichier_csv(
            "ticker,nom,place,devise,alias,imposee\n"
            "AAA,Aaa,NYSE,USD,Aaa,0\n"
            "BBB,Bbb,MARS,USD,Bbb,0\n"
        )
        with self.assertRaisesMessage(CommandError, "ligne 3"):
            lancer("--fichier", chemin)
        self.assertEqual(Valeur.objects.count(), 0)
