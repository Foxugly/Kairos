from datetime import UTC, datetime

from django.test import TestCase

from marche.models import StatutValeur, Valeur
from sources.models import FluxRss, Nouvelle
from sources.rss import relever_nouvelles

MAINTENANT = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def rss(*items):
    corps = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
        f"<pubDate>Mon, 09 Nov 2026 14:00:00 GMT</pubDate></item>"
        for t, u, d in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{corps}</channel></rss>'.encode()


class ReleverNouvellesTests(TestCase):
    def setUp(self):
        self.a = FluxRss.objects.create(nom="A", url="https://a.test/rss", langue="fr")
        self.b = FluxRss.objects.create(nom="B", url="https://b.test/rss", langue="en")
        self.apple = Valeur.objects.create(
            ticker="AAPL", nom="Apple", place="NASDAQ", devise="USD",
            alias="Apple", statut=StatutValeur.ACTIVE,
        )
        Valeur.objects.create(
            ticker="NVDA", nom="Nvidia", place="NASDAQ", devise="USD",
            alias="Nvidia", statut=StatutValeur.INACTIVE,
        )

    def test_dedoublonnage_par_empreinte_et_rattachement(self):
        contenus = {
            self.a.url: rss(("Apple bat les attentes", "https://a.test/1", "")),
            self.b.url: rss(("  APPLE bat les  attentes! ", "https://b.test/9", "")),
        }
        res = relever_nouvelles(MAINTENANT, telecharger=contenus.__getitem__)
        self.assertEqual(res, {"nouvelles": 1, "flux_en_erreur": {}})
        (n,) = Nouvelle.objects.all()
        self.assertEqual(list(n.valeurs.all()), [self.apple])

    def test_flux_en_erreur_n_arrete_pas_les_autres(self):
        def telecharger(url):
            if url == self.a.url:
                raise OSError("panne")
            return rss(("Nvidia grimpe", "https://b.test/2", "Apple suit"))

        res = relever_nouvelles(MAINTENANT, telecharger=telecharger)
        self.assertEqual(res["nouvelles"], 1)
        self.assertEqual(list(res["flux_en_erreur"]), ["A"])
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertIn("panne", self.a.derniere_erreur)
        self.assertIsNone(self.a.dernier_releve)
        self.assertEqual(self.b.dernier_releve, MAINTENANT)
        self.assertEqual(self.b.derniere_erreur, "")
        # Nvidia est inactive : seul le résumé cite Apple.
        self.assertEqual(list(Nouvelle.objects.get().valeurs.all()), [self.apple])

    def test_relancer_ne_double_pas(self):
        contenu = rss(("Apple annonce", "https://a.test/1", ""))
        self.b.actif = False
        self.b.save()
        for _ in range(2):
            relever_nouvelles(MAINTENANT, telecharger=lambda url: contenu)
        self.assertEqual(Nouvelle.objects.count(), 1)

    def test_flux_illisible_signale(self):
        res = relever_nouvelles(MAINTENANT, telecharger=lambda url: b"<html></html>")
        self.assertEqual(set(res["flux_en_erreur"]), {"A", "B"})


class FixtureDepartTests(TestCase):
    def test_flux_de_depart_se_charge(self):
        from django.core.management import call_command

        call_command("loaddata", "flux_depart", verbosity=0)
        self.assertEqual(FluxRss.objects.count(), 10)
