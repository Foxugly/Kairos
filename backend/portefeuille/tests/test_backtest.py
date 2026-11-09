from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from analyse.signaux import BougieJour, Sens, Signal
from courtage.models import BaremeDonnees, RegleDonnees, TobDonnees
from marche.models import Bougie, StatutValeur, TauxChange, Valeur
from portefeuille.backtest import perte_max, rejouer
from portefeuille.management.commands.backtest import taux_usd_journaliers
from portefeuille.models import ResultatBacktest
from portefeuille.strategie import Regles

D = Decimal
LUNDI = date(2026, 1, 5)

BAREME = BaremeDonnees(
    broker="test", nom="Test", change_pourcentage=D("0.0002"), change_minimum=D("2"),
    glissement=D("0"),
    regles=(
        RegleDonnees(("XPAR",), "EUR", D("0"), D("0.001"), D("1.00"), None, None),
        RegleDonnees(("NYSE",), "USD", D("0.005"), D("0"), D("1.00"), None, None),
    ),
    tob=(TobDonnees("action", D("0.0035"), D("1600")), TobDonnees("etf", D("0.0012"), D("1300"))),
)

REGLES = Regles(
    part_max=D("0.5"), positions_max=20, stop_perte=D("0.05"), seuil_suiveur=D("0.05"),
    ecart_suiveur=D("0.05"), frais_max_relatifs=D("0.05"), score_achat=2,
)

META = {
    "AAA": ("EUR", "XPAR", "action"),
    "BBB": ("EUR", "XPAR", "action"),
    "UUU": ("USD", "NYSE", "action"),
    "IDX": ("EUR", "XPAR", "etf"),
}


def jours(n, depuis=LUNDI):
    """n jours ouvrés consécutifs."""
    resultat, jour = [], depuis
    while len(resultat) < n:
        if jour.weekday() < 5:
            resultat.append(jour)
        jour += timedelta(days=1)
    return resultat


J = jours(40)


def bougie(jour, ouverture, haut=None, bas=None, cloture=None):
    o = D(str(ouverture))
    c = D(str(cloture)) if cloture is not None else o
    h = D(str(haut)) if haut is not None else max(o, c)
    b = D(str(bas)) if bas is not None else min(o, c)
    return BougieJour(jour=jour, ouverture=o, haut=h, bas=b, cloture=c)


def plat(prix, n=len(J)):
    return [bougie(j, prix) for j in J[:n]]


def achat_le(*achats):
    """Faux `signaux_du_jour` : deux signaux d'achat pour (ticker, jour) listés, rien sinon.

    Le ticker est reconnu au prix de clôture du premier jour (séries de test distinctes).
    """
    def signaux(bougies):
        if any(bougies[-1].jour == jour for jour in achats):
            return [Signal("rsi", Sens.ACHAT, ""), Signal("cassure", Sens.ACHAT, "")]
        return []
    return signaux


def lancer(series, taux=None, regles=REGLES, capital="10000", debut=None):
    meta = {t: META[t] for t in series}
    return rejouer(series, meta, taux or {}, regles, BAREME, D(capital), "IDX", debut=debut)


class SignauxEtOrdresTests(SimpleTestCase):
    def test_signal_de_j_execute_a_l_ouverture_de_j_plus_1(self):
        # Clôture de J[1] à 200, ouverture de J[2] à 100 : l'achat doit se faire à 100.
        aaa = plat(100)
        aaa[1] = bougie(J[1], 100, cloture=200)
        vus = []

        def signaux(bougies):
            vus.append(bougies[-1].jour)
            return achat_le(J[1])(bougies)

        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=signaux):
            rapport = lancer({"AAA": aaa, "IDX": plat(50)})
        achats = [o for o in rapport.ordres if o.sens == "achat"]
        self.assertEqual([(o.jour, o.prix) for o in achats], [(J[2], D("100"))])
        # Jamais de bougie future : les signaux de J sont calculés sur les bougies jusqu'à J inclus.
        self.assertEqual(vus, J[: len(vus)])

    def test_valeur_sans_bougie_le_lendemain_executee_a_sa_seance_suivante(self):
        aaa = [b for b in plat(100) if b.jour != J[2]]
        aaa[2] = bougie(J[3], 101)
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[1])):
            rapport = lancer({"AAA": aaa, "IDX": plat(50)})
        self.assertEqual([(o.jour, o.prix) for o in rapport.ordres], [(J[3], D("101"))])

    def test_indice_achete_a_l_ouverture_du_premier_jour(self):
        idx = plat(50)
        idx[0] = bougie(J[0], 40, cloture=50)
        with mock.patch("portefeuille.backtest.signaux_du_jour", return_value=[]):
            rapport = lancer({"AAA": plat(100), "IDX": idx})
        # 249 parts à 40 (+ frais) : 250 parts dépasseraient le capital une fois les frais ajoutés.
        self.assertEqual(rapport.indice_ordre.quantite, 249)
        self.assertEqual(rapport.indice_ordre.prix, D("40"))
        self.assertEqual(rapport.indice_ordre.jour, J[0])

    def test_aucun_signal_performance_nulle_hors_indice(self):
        # 20 séances : trop court pour tout signal (cassure : 21, MM : 51), signaux réels.
        rapport = lancer({"AAA": plat(100, 20), "IDX": plat(50, 20)})
        self.assertEqual(rapport.nb_positions, 0)
        self.assertEqual(rapport.performance, D("0"))
        self.assertEqual(rapport.valeur_finale, D("10000.00"))
        self.assertEqual(rapport.frais_total, D("0"))
        self.assertEqual(rapport.perte_max, D("0"))
        # L'indice, lui, a payé ses frais d'achat.
        self.assertLess(rapport.performance_indice, 0)
        self.assertEqual(rapport.ecart, -rapport.performance_indice)
        self.assertEqual((rapport.debut, rapport.fin), (J[0], J[19]))
        self.assertEqual(len(rapport.courbe), 20)

    def test_signaux_reels_cassure_puis_achat(self):
        # Zigzag 100/99 puis clôture à 103 : cassure du plus haut des 20 séances, RSI entre 30 et 70.
        aaa = [bougie(j, 100 if i % 2 == 0 else 99) for i, j in enumerate(J[:30])]
        aaa.append(bougie(J[30], 100, cloture=103))
        aaa += [bougie(j, 104) for j in J[31:35]]
        regles = replace(REGLES, score_achat=1)
        rapport = lancer({"AAA": aaa, "IDX": plat(50, 35)}, regles=regles)
        self.assertEqual([(o.sens, o.jour, o.prix) for o in rapport.ordres][:1], [("achat", J[31], D("104"))])

    def test_debut_bougies_anterieures_pour_les_signaux_seulement(self):
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[1], J[6])):
            rapport = lancer({"AAA": plat(100), "IDX": plat(50)}, debut=J[5])
        # Le signal de J[1] est antérieur à la période : seul celui de J[6] donne un ordre.
        self.assertEqual([o.jour for o in rapport.ordres], [J[7]])
        self.assertEqual(rapport.debut, J[5])
        self.assertEqual(rapport.courbe[0][0], J[5])
        self.assertEqual(rapport.indice_ordre.jour, J[5])

    def test_valeur_usd_au_taux_du_jour_ou_precedent(self):
        taux = {J[0]: D("0.9"), J[2]: D("0.8")}
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[3])):
            rapport = lancer({"UUU": plat(100), "IDX": plat(50)}, taux=taux)
        achat = rapport.ordres[0]
        self.assertEqual((achat.jour, achat.taux_eur), (J[4], D("0.8")))

    def test_ouverture_au_taux_de_la_veille_jamais_celui_du_jour(self):
        # Le taux de J est celui de la clôture de J : inconnu à l'ouverture de J.
        taux = {J[0]: D("0.9"), J[4]: D("0.8")}
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[3])):
            rapport = lancer({"UUU": plat(100), "IDX": plat(50)}, taux=taux)
        achat = rapport.ordres[0]
        self.assertEqual((achat.jour, achat.taux_eur), (J[4], D("0.9")))
        # La valorisation à la clôture de J[4], elle, prend le taux de J[4].
        titres = rapport.courbe[4][1] - (D("10000") - achat.montant_eur - achat.frais.total)
        self.assertEqual(titres, achat.quantite * D("100") * D("0.8"))

    def test_valeur_usd_sans_taux_non_tradee(self):
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[1])):
            rapport = lancer({"UUU": plat(100), "IDX": plat(50)}, taux={J[5]: D("0.9")})
        self.assertEqual(rapport.ordres, [])


class StopsTests(SimpleTestCase):
    def rejouer_achat_puis(self, suite):
        """Achat de AAA à 100 à l'ouverture de J[2], puis les bougies `suite` à partir de J[3]."""
        aaa = [bougie(J[0], 100), bougie(J[1], 100), bougie(J[2], 100, haut=101, bas=99.5)]
        aaa += [bougie(J[3 + i], *b) for i, b in enumerate(suite)]
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[1])):
            return lancer({"AAA": aaa, "IDX": plat(50, len(aaa))})

    def ventes(self, rapport):
        return [(o.jour, o.prix, o.motif) for o in rapport.ordres if o.sens == "vente"]

    def test_monte_puis_casse_sortie_par_stop_suiveur_au_bon_jour(self):
        rapport = self.rejouer_achat_puis([
            (103, 106, 102.5, 105),   # J3 : plus haut 106, suiveur armé à 100,70
            (105, 110, 104.8, 109),   # J4 : bas 104,8 > 100,70 ; nouveau plus haut 110 (après le contrôle)
            (109, 109.5, 106, 107),   # J5 : niveau 104,50 non touché
            (107, 108, 104, 105),     # J6 : bas 104 ≤ 104,50 → sortie à 104,50
            (105, 106, 100, 101),
        ])
        self.assertEqual(self.ventes(rapport), [(J[6], D("104.5000"), "stop suiveur")])
        self.assertEqual(rapport.nb_positions, 1)
        self.assertEqual(rapport.taux_gagnantes, D("1"))

    def test_plus_haut_du_jour_ne_declenche_pas_le_stop_du_meme_jour(self):
        # J3 : haut 120 puis bas 112 ; le plus haut n'est mis à jour qu'après le contrôle : pas de sortie.
        rapport = self.rejouer_achat_puis([(110, 120, 112, 113), (115, 116, 115, 115.5)])
        self.assertEqual(self.ventes(rapport), [])

    def test_gap_sous_le_stop_execute_a_l_ouverture(self):
        rapport = self.rejouer_achat_puis([(90, 91, 89, 90), (90, 91, 89, 90)])
        self.assertEqual(self.ventes(rapport), [(J[3], D("90.0000"), "stop-loss −5 %")])
        self.assertEqual(rapport.taux_gagnantes, D("0"))

    def test_stop_loss_au_niveau_du_stop(self):
        rapport = self.rejouer_achat_puis([(99, 99.5, 94, 96)])
        self.assertEqual(self.ventes(rapport), [(J[3], D("95.0000"), "stop-loss −5 %")])


class TotauxTests(SimpleTestCase):
    def test_frais_et_tob_egaux_a_la_somme_des_ordres(self):
        aaa = plat(100)
        bbb = plat(30)
        bbb[8] = bougie(J[8], 30, bas=20, cloture=25)  # stop-loss de BBB
        with mock.patch("portefeuille.backtest.signaux_du_jour", side_effect=achat_le(J[1], J[3])):
            rapport = lancer({"AAA": aaa, "BBB": bbb, "IDX": plat(50)})
        self.assertGreaterEqual(len(rapport.ordres), 3)
        self.assertEqual(rapport.frais_total, sum((o.frais.total for o in rapport.ordres), D(0)))
        self.assertEqual(rapport.tob_total, sum((o.frais.tob for o in rapport.ordres), D(0)))
        self.assertGreater(rapport.tob_total, 0)
        # Liquidités recalculées depuis les ordres = valeur finale moins les titres encore détenus.
        flux = sum(
            (-(o.montant_eur + o.frais.total) if o.sens == "achat" else o.montant_eur - o.frais.total
             for o in rapport.ordres),
            D(0),
        )
        detenus = {o.ticker: o.quantite for o in rapport.ordres if o.sens == "achat"}
        for o in rapport.ordres:
            if o.sens == "vente":
                del detenus[o.ticker]
        titres = sum((q * {"AAA": D(100), "BBB": D(30)}[t] for t, q in detenus.items()), D(0))
        self.assertEqual(rapport.valeur_finale, D("10000") + flux + titres)

    def test_perte_max_d_une_courbe_connue(self):
        self.assertEqual(perte_max([D(100), D(120), D(90), D(130), D(117)]), D("0.2500"))
        self.assertEqual(perte_max([D(100), D(110)]), D("0"))
        self.assertEqual(perte_max([]), D("0"))


def creer_bougies(valeur, prix, n=25):
    for jour in J[:n]:
        Bougie.objects.create(
            valeur=valeur, intervalle="1d", debut=datetime(jour.year, jour.month, jour.day, tzinfo=UTC),
            ouverture=D(prix), haut=D(prix), bas=D(prix), cloture=D(prix), volume=1,
        )


class CommandeBacktestTests(TestCase):
    def test_enregistre_et_affiche_le_rapport(self):
        aaa = Valeur.objects.create(ticker="AAA.PA", nom="A", place="XPAR", devise="EUR",
                                    statut=StatutValeur.ACTIVE)
        creer_bougies(aaa, "100")
        creer_bougies(Valeur.objects.get(ticker="IWDA.AS"), "80")
        TauxChange.objects.create(devise="USD", instant=datetime(2026, 1, 5, tzinfo=UTC), taux=D("0.9"))
        sortie = StringIO()
        call_command("backtest", "--depuis", "2026-01-07", stdout=sortie)
        texte = sortie.getvalue()
        resultat = ResultatBacktest.objects.get()
        self.assertEqual(resultat.portefeuille.nom, "Technique")
        self.assertEqual(resultat.debut, J[2])
        self.assertEqual(resultat.performance, D("0"))
        self.assertEqual(len(resultat.courbe), 23)
        self.assertIn("Performance", texte)
        self.assertIn("barème en vigueur aujourd'hui", texte)
        self.assertIn("Positions prises     : 0", texte)
        self.assertIn("1 valeurs)", texte)
        self.assertIn("hors achat de l'indice", texte)

    def test_valeurs_comptees_sans_bougie_de_l_indice(self):
        aaa = Valeur.objects.create(ticker="AAA.PA", nom="A", place="XPAR", devise="EUR",
                                    statut=StatutValeur.ACTIVE)
        creer_bougies(aaa, "100")
        sortie = StringIO()
        call_command("backtest", "--depuis", "2026-01-07", stdout=sortie)
        self.assertIn("(23 séances, 1 valeurs)", sortie.getvalue())

    def test_taux_usd_journaliers_seulement(self):
        minuit = datetime(2026, 1, 5, tzinfo=UTC)
        TauxChange.objects.create(devise="USD", instant=minuit, taux=D("0.9"))
        # Taux relevé en séance par le cycle, le même jour et plus tard : ignoré.
        TauxChange.objects.create(devise="USD", instant=minuit + timedelta(hours=15), taux=D("0.7"))
        TauxChange.objects.create(devise="USD", instant=minuit + timedelta(days=1, hours=9), taux=D("0.6"))
        self.assertEqual(taux_usd_journaliers(), {J[0]: D("0.9")})

    def test_portefeuille_inconnu(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("backtest", "--portefeuille", "Inconnu", stdout=StringIO())
