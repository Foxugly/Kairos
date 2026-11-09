from datetime import UTC, datetime

from unittest import mock

from django.test import SimpleTestCase

from sources.rss import TAILLE_MAX, FluxIllisible, lire_flux, telecharger

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Marchés</title>
<item><title>Apple bat les attentes</title><link>https://exemple.test/a</link>
<description>&lt;p&gt;Résultats &lt;b&gt;solides&lt;/b&gt; au trimestre.&lt;/p&gt;</description>
<pubDate>Mon, 09 Nov 2026 14:30:00 +0100</pubDate></item>
<item><title>Sans date</title><link>https://exemple.test/b</link></item>
</channel></rss>""".encode()

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Flux</title>
<entry><title>Nvidia grimpe</title><link href="https://exemple.test/c"/>
<summary>Un &lt;a href="x"&gt;résumé&lt;/a&gt; court</summary>
<updated>2026-11-09T10:00:00Z</updated></entry></feed>""".encode()


class LireFluxTests(SimpleTestCase):
    def test_rss(self):
        nouvelles = lire_flux(RSS)
        self.assertEqual(len(nouvelles), 2)
        n = nouvelles[0]
        self.assertEqual(n.titre, "Apple bat les attentes")
        self.assertEqual(n.url, "https://exemple.test/a")
        self.assertEqual(n.publiee, datetime(2026, 11, 9, 13, 30, tzinfo=UTC))
        self.assertEqual(n.resume, "Résultats solides au trimestre.")

    def test_entree_sans_date_prend_la_date_de_reception(self):
        avant = datetime.now(UTC)
        n = lire_flux(RSS)[1]
        self.assertGreaterEqual(n.publiee, avant)
        self.assertEqual(n.resume, "")

    def test_atom(self):
        (n,) = lire_flux(ATOM)
        self.assertEqual(n.titre, "Nvidia grimpe")
        self.assertEqual(n.url, "https://exemple.test/c")
        self.assertEqual(n.publiee, datetime(2026, 11, 9, 10, 0, tzinfo=UTC))
        self.assertEqual(n.resume, "Un résumé court")

    def test_contenu_html_illisible(self):
        with self.assertRaises(FluxIllisible):
            lire_flux(b"<html><body><p>Page de connexion</p></body></html>")

    def test_date_de_repli_fournie(self):
        repli = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
        self.assertEqual(lire_flux(RSS, repli)[1].publiee, repli)

    def test_titre_vide_apres_normalisation_et_url_trop_longue_ecartes(self):
        contenu = (
            '<rss version="2.0"><channel><title>x</title>'
            '<item><title>!!! ...</title><link>https://e.test/1</link></item>'
            f'<item><title>Long</title><link>https://e.test/{"a" * 1000}</link></item>'
            '<item><title>Bon</title><link>https://e.test/3</link></item>'
            "</channel></rss>"
        ).encode()
        with self.assertLogs("sources.rss", "WARNING"):
            self.assertEqual([n.titre for n in lire_flux(contenu)], ["Bon"])

    def test_201_entrees_gardent_les_200_premieres(self):
        items = "".join(
            f"<item><title>N{i}</title><link>https://e.test/{i}</link></item>" for i in range(201)
        )
        contenu = f'<rss version="2.0"><channel><title>x</title>{items}</channel></rss>'.encode()
        nouvelles = lire_flux(contenu)
        self.assertEqual(len(nouvelles), 200)
        self.assertEqual(nouvelles[-1].titre, "N199")

    def test_titre_et_resume_tronques(self):
        contenu = (
            '<rss version="2.0"><channel><title>x</title><item>'
            f'<title>{"t" * 600}</title><link>https://e.test/1</link>'
            f'<description>{"r" * 6000}</description></item></channel></rss>'
        ).encode()
        (n,) = lire_flux(contenu)
        self.assertEqual((len(n.titre), len(n.resume)), (500, 5000))


def fausse_reponse(morceaux, entetes=None, statut=200):
    reponse = mock.MagicMock()
    reponse.__enter__.return_value = reponse
    reponse.status_code = statut
    reponse.headers = entetes or {}
    reponse.iter_content.return_value = iter(morceaux)
    return reponse


class TelechargerTests(SimpleTestCase):
    def test_schema_refuse(self):
        for url in ("file:///etc/passwd", "ftp://e.test/x", "gopher://e.test"):
            with self.assertRaisesMessage(ValueError, "schéma refusé"):
                telecharger(url)

    @mock.patch("sources.rss.requests.Session")
    def test_content_length_trop_grand(self, session):
        session.return_value.__enter__.return_value = session.return_value
        session.return_value.get.return_value = fausse_reponse(
            [b"x"], {"Content-Length": str(TAILLE_MAX + 1)}
        )
        with self.assertRaisesMessage(ValueError, "limite de"):
            telecharger("https://e.test/rss")

    @mock.patch("sources.rss.requests.Session")
    def test_lecture_interrompue_au_dela_de_la_limite(self, session):
        session.return_value.__enter__.return_value = session.return_value
        session.return_value.get.return_value = fausse_reponse(
            [b"x" * TAILLE_MAX, b"y"]
        )
        with self.assertRaisesMessage(ValueError, "limite de"):
            telecharger("https://e.test/rss")

    @mock.patch("sources.rss.requests.Session")
    def test_lecture_normale_et_parametres(self, session):
        session.return_value.__enter__.return_value = session.return_value
        session.return_value.get.return_value = fausse_reponse([b"ab", b"cd"])
        self.assertEqual(telecharger("https://e.test/rss"), b"abcd")
        self.assertEqual(session.return_value.max_redirects, 5)
        _, kwargs = session.return_value.get.call_args
        self.assertEqual((kwargs["stream"], kwargs["timeout"]), (True, (5, 15)))
        session.return_value.__exit__.assert_called_once()  # session fermée
