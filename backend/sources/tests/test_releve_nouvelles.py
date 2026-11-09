from datetime import UTC, datetime

from unittest import mock

from django.db import DatabaseError
from django.test import TestCase

from marche.models import StatutValeur, Valeur
from sources.models import FluxRss, Nouvelle
from sources.rss import NouvelleBrute, _enregistrer, empreinte, relever_nouvelles

MAINTENANT = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def rss(*items, date="Mon, 09 Nov 2026 14:00:00 GMT"):
    corps = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
        f"<pubDate>{date}</pubDate></item>"
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

    def test_panne_totale_journalise_une_erreur(self):
        with self.assertLogs("sources.rss", "ERROR") as cm:
            relever_nouvelles(MAINTENANT, telecharger=mock.Mock(side_effect=OSError("panne")))
        self.assertEqual(len(cm.records), 1)

    def test_panne_partielle_sans_erreur(self):
        def telecharger(url):
            if url == self.a.url:
                raise OSError("panne")
            return rss(("Apple", "https://b.test/3", ""))

        with self.assertNoLogs("sources.rss", "ERROR"):
            relever_nouvelles(MAINTENANT, telecharger=telecharger)

    def test_flux_illisible_signale(self):
        res = relever_nouvelles(MAINTENANT, telecharger=lambda url: b"<html></html>")
        self.assertEqual(set(res["flux_en_erreur"]), {"A", "B"})

    def test_meme_titre_deux_jours_differents_donne_deux_nouvelles(self):
        self.b.actif = False
        self.b.save()
        for jour in ("Mon, 09 Nov 2026 14:00:00 GMT", "Tue, 10 Nov 2026 14:00:00 GMT"):
            contenu = rss(("Wall Street ouvre en hausse", f"https://a.test/{jour[:3]}", ""), date=jour)
            relever_nouvelles(MAINTENANT, telecharger=lambda url, c=contenu: c)
        self.assertEqual(Nouvelle.objects.count(), 2)

    def test_erreur_de_stockage_isolee_par_flux(self):
        vrai = _enregistrer

        def enregistrer(flux, brute, valeurs):
            if flux == self.a:
                raise DatabaseError("base indisponible")
            return vrai(flux, brute, valeurs)

        contenu = rss(("Apple annonce", "https://x.test/1", ""))
        with mock.patch("sources.rss._enregistrer", enregistrer):
            res = relever_nouvelles(MAINTENANT, telecharger=lambda url: contenu)
        self.assertEqual(res["nouvelles"], 1)
        self.assertEqual(list(res["flux_en_erreur"]), ["A"])
        self.a.refresh_from_db()
        self.assertIn("base indisponible", self.a.derniere_erreur)
        self.assertIsNone(self.a.dernier_releve)

    def test_doublon_concurrent_compte_comme_deja_connue(self):
        brute = NouvelleBrute("https://x.test/1", "Apple", "", MAINTENANT)
        with mock.patch.object(Nouvelle.objects, "filter") as filtre:
            filtre.return_value.exists.return_value = False  # le contrôle préalable ne voit rien
            Nouvelle.objects.create(
                url=brute.url, empreinte=empreinte("Apple", MAINTENANT), titre="Apple",
                publiee=MAINTENANT, flux=self.a,
            )
            self.assertEqual(_enregistrer(self.a, brute, []), 0)


class FixtureDepartTests(TestCase):
    def test_flux_de_depart_se_charge(self):
        from django.core.management import call_command

        call_command("loaddata", "flux_depart", verbosity=0)
        self.assertEqual(FluxRss.objects.count(), 10)
