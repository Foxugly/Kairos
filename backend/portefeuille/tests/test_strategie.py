from decimal import Decimal
from unittest import TestCase

from analyse.signaux import Sens, Signal
from courtage.models import BaremeDonnees, RegleDonnees
from portefeuille.strategie import Cotation, Intention, PositionVue, Regles, decider, stops

D = Decimal


def bareme(minimum="1.00", glissement="0"):
    return BaremeDonnees(
        broker="test", nom="Test", change_pourcentage=D("0"), change_minimum=D("0"),
        glissement=D(glissement),
        regles=(RegleDonnees(("XPAR",), "EUR", D("0"), D("0.001"), D(minimum), None, None),),
        tob=(),
    )


REGLES = Regles(
    part_max=D("0.05"), positions_max=20, stop_perte=D("0.05"), seuil_suiveur=D("0.05"),
    ecart_suiveur=D("0.05"), frais_max_relatifs=D("0.01"), score_achat=2,
)


def cotation(prix):
    return Cotation(D(prix), "EUR", "XPAR", "action", D("1"))


def pos(ticker="AAA", prix_entree="100", plus_haut="100", quantite=10):
    return PositionVue(ticker, quantite, D(prix_entree), D(plus_haut))


def achat(*codes):
    return [Signal(c, Sens.ACHAT, "") for c in codes]


def vente(*codes):
    return [Signal(c, Sens.VENTE, "") for c in codes]


class StopsTests(TestCase):
    def appliquer(self, position, prix):
        return stops([position], {position.ticker: cotation(prix)}, REGLES)

    def test_stop_loss_exact(self):
        res = self.appliquer(pos(), "95")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].action, "vendre")
        self.assertEqual(res[0].quantite, 10)
        self.assertEqual(res[0].motif, "stop-loss −5 %")

    def test_stop_loss_pas_atteint(self):
        self.assertEqual(self.appliquer(pos(), "95.1"), [])

    def test_suiveur_declenche(self):
        res = self.appliquer(pos(plus_haut="110"), "104")
        self.assertEqual([i.motif for i in res], ["stop suiveur"])

    def test_suiveur_pas_atteint(self):
        self.assertEqual(self.appliquer(pos(plus_haut="110"), "105"), [])

    def test_suiveur_inactif(self):
        self.assertEqual(self.appliquer(pos(plus_haut="104"), "99"), [])

    def test_valeur_sans_cours_ignoree(self):
        self.assertEqual(stops([pos()], {}, REGLES), [])


class DeciderTests(TestCase):
    def decider(self, signaux, marche, liquidites="10000", total="10000", positions=(), regles=REGLES,
                bar=None):
        return decider(D(liquidites), D(total), list(positions), signaux, marche, regles, bar or bareme())

    def test_achat_simple(self):
        res = self.decider({"AAA": achat("rsi", "cassure")}, {"AAA": cotation("100")})
        self.assertEqual(res, [Intention("AAA", "acheter", 5, res[0].motif)])

    def test_score_insuffisant_ignore(self):
        self.assertEqual(self.decider({"AAA": achat("rsi")}, {"AAA": cotation("100")}), [])

    def test_candidat_avec_signal_de_vente_ignore(self):
        sig = achat("rsi", "cassure", "croisement_mm") + vente("x")
        self.assertEqual(self.decider({"AAA": sig}, {"AAA": cotation("100")}), [])

    def test_deux_candidats_un_seul_payable(self):
        sig = {"AAA": achat("rsi", "cassure"), "BBB": achat("rsi", "cassure")}
        marche = {"AAA": cotation("100"), "BBB": cotation("100")}
        res = self.decider(sig, marche, liquidites="600")
        self.assertEqual([(i.ticker, i.action) for i in res], [("AAA", "acheter"), ("BBB", "refuser")])
        self.assertEqual(res[0].quantite, 5)
        self.assertEqual(res[1].motif, "liquidités insuffisantes")

    def test_liquidites_jamais_negatives_avec_les_frais(self):
        # 5 actions à 100 + 1,00 de frais = 501 > 500 : on réduit à 4.
        res = self.decider({"AAA": achat("rsi", "cassure")}, {"AAA": cotation("100")}, liquidites="500")
        self.assertEqual(res[0].quantite, 4)

    def test_ordre_par_score_puis_ticker(self):
        sig = {"BBB": achat("rsi", "cassure"), "AAA": achat("rsi", "cassure"),
               "CCC": achat("rsi", "cassure", "croisement_mm")}
        marche = {t: cotation("100") for t in sig}
        res = self.decider(sig, marche)
        self.assertEqual([i.ticker for i in res], ["CCC", "AAA", "BBB"])

    def test_positions_max(self):
        positions = [pos(f"P{i}") for i in range(20)]
        res = self.decider({"AAA": achat("rsi", "cassure")}, {"AAA": cotation("100")}, positions=positions)
        self.assertEqual((res[0].action, res[0].motif), ("refuser", "20 positions déjà ouvertes"))

    def test_frais_trop_lourds(self):
        res = self.decider({"AAA": achat("rsi", "cassure")}, {"AAA": cotation("100")}, bar=bareme(minimum="10.00"))
        self.assertEqual(res[0].action, "refuser")
        self.assertIn("frais aller-retour trop élevés", res[0].motif)

    def test_sans_cours(self):
        res = self.decider({"AAA": achat("rsi", "cassure")}, {})
        self.assertEqual((res[0].action, res[0].motif), ("refuser", "pas de cours récent"))

    def test_action_trop_chere(self):
        res = self.decider({"AAA": achat("rsi", "cassure")}, {"AAA": cotation("600")})
        self.assertEqual((res[0].action, res[0].motif), ("refuser", "une action dépasse 5 % du portefeuille"))

    def test_place_sans_regle_refusee(self):
        marche = {"AAA": Cotation(D("100"), "EUR", "XMIL", "action", D("1"))}
        res = self.decider({"AAA": achat("rsi", "cassure")}, marche)
        self.assertEqual(res[0].action, "refuser")
        self.assertIn("XMIL", res[0].motif)

    def test_vente_sur_signal_avant_achats(self):
        sig = {"AAA": achat("rsi", "cassure"), "HHH": vente("rsi")}
        marche = {"AAA": cotation("100"), "HHH": cotation("100")}
        res = self.decider(sig, marche, positions=[pos("HHH")])
        self.assertEqual([(i.ticker, i.action) for i in res], [("HHH", "vendre"), ("AAA", "acheter")])
        self.assertEqual(res[0].quantite, 10)
        self.assertEqual(res[0].motif, "signal de vente (score −1)")

    def test_vente_sans_cours_gardee(self):
        res = self.decider({"HHH": vente("rsi")}, {}, positions=[pos("HHH")])
        self.assertEqual(res, [])

    def test_titre_detenu_non_rachete(self):
        res = self.decider({"HHH": achat("rsi", "cassure")}, {"HHH": cotation("100")}, positions=[pos("HHH")])
        self.assertEqual(res, [])
