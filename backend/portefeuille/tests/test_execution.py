from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.db.models import F, Sum
from django.test import TestCase

from analyse.signaux import Sens, Signal
from marche.models import Bougie, StatutValeur, TauxChange, TypeTitre, Valeur
from marche.tests.outils import repartir_de_zero
from portefeuille import execution
from portefeuille.execution import decider_du_jour, executer, prochain_jour_ouvre
from portefeuille.marche_actuel import marche
from portefeuille.models import (
    ActionDecision,
    Decision,
    Ordre,
    Portefeuille,
    Position,
    SensOrdre,
    Valorisation,
)

# Mardi 2026-11-10 : 10:00 UTC = 11:00 à Paris (New York fermé) ; 15:00 UTC = 16:00 à Paris, 10:00 à New York.
MARDI_MATIN = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
MARDI_APREM = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
MARDI_SOIR = datetime(2026, 11, 10, 22, 45, tzinfo=UTC)
MERCREDI_MATIN = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
MARDI = date(2026, 11, 10)
MERCREDI = date(2026, 11, 11)

ACHAT = {
    "score": 2,
    "signaux": [
        {"code": "rsi", "sens": "achat", "detail": "RSI bas"},
        {"code": "cassure", "sens": "achat", "detail": "cassure"},
    ],
}
VENTE = {"score": -1, "signaux": [{"code": "rsi", "sens": "vente", "detail": "RSI haut"}]}


def bougie(valeur, debut, cloture, intervalle="5m"):
    c = Decimal(cloture)
    return Bougie.objects.create(
        valeur=valeur, intervalle=intervalle, debut=debut,
        ouverture=c, haut=c, bas=c, cloture=c, volume=1,
    )


class Base(TestCase):
    def setUp(self):
        repartir_de_zero()
        self.iwda = Valeur.objects.create(
            ticker="IWDA.AS", nom="iShares", place="XAMS", devise="EUR",
            reference=True, type_titre=TypeTitre.ETF,
        )
        self.tte = Valeur.objects.create(
            ticker="TTE.PA", nom="Total", place="XPAR", devise="EUR", statut=StatutValeur.ACTIVE
        )
        self.aapl = Valeur.objects.create(
            ticker="AAPL", nom="Apple", place="NASDAQ", devise="USD", statut=StatutValeur.ACTIVE
        )
        # Part maximale relevée : à 5 % de 10 000 €, les frais aller-retour dépassent 1 % du montant.
        self.p = Portefeuille.objects.create(nom="Technique", indice=self.iwda, part_max=Decimal("0.5"))

    def decision(self, valeur, action=ActionDecision.ACHETER, signaux=ACHAT, pour_le=MARDI):
        return Decision.objects.create(
            portefeuille=self.p, valeur=valeur, instant=MARDI_SOIR - timedelta(days=1),
            action=action, motif="test", signaux=signaux, pour_le=pour_le,
        )

    def position(self, valeur, quantite=10, prix="100", plus_haut=None, taux="1"):
        return Position.objects.create(
            portefeuille=self.p, valeur=valeur, quantite=quantite, prix_entree=Decimal(prix),
            taux_entree=Decimal(taux), cout_entree_eur=Decimal("1006.50"),
            plus_haut=Decimal(plus_haut or prix), ouverte_le=MARDI_MATIN - timedelta(days=5),
        )

    def demarrer(self):
        Portefeuille.objects.filter(pk=self.p.pk).update(demarre=MARDI_MATIN - timedelta(days=5))


class MarcheActuelTests(Base):
    def test_bougie_recente_cotee(self):
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=10), "100")
        cotation = marche(MARDI_MATIN)["TTE.PA"]
        self.assertEqual(cotation.prix, Decimal("100"))
        self.assertEqual(cotation.taux_eur, Decimal(1))
        self.assertEqual((cotation.devise, cotation.place, cotation.type_titre), ("EUR", "XPAR", "action"))

    def test_bougie_de_40_minutes_absente(self):
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=40), "100")
        self.assertNotIn("TTE.PA", marche(MARDI_MATIN))

    def test_taux_usd_absent_ou_trop_vieux(self):
        bougie(self.aapl, MARDI_APREM - timedelta(minutes=5), "200")
        bougie(self.tte, MARDI_APREM - timedelta(minutes=5), "100")
        self.assertNotIn("AAPL", marche(MARDI_APREM))
        self.assertIn("TTE.PA", marche(MARDI_APREM))
        TauxChange.objects.create(devise="USD", instant=MARDI_APREM - timedelta(hours=25), taux=Decimal("0.9"))
        self.assertNotIn("AAPL", marche(MARDI_APREM))
        TauxChange.objects.create(devise="USD", instant=MARDI_APREM - timedelta(hours=2), taux=Decimal("0.88"))
        self.assertEqual(marche(MARDI_APREM)["AAPL"].taux_eur, Decimal("0.88"))

    def test_place_fermee_absente(self):
        bougie(self.aapl, MARDI_MATIN - timedelta(minutes=5), "200")
        TauxChange.objects.create(devise="USD", instant=MARDI_MATIN, taux=Decimal("0.9"))
        self.assertNotIn("AAPL", marche(MARDI_MATIN))

    def test_valeur_inactive_absente_reference_presente(self):
        self.tte.statut = StatutValeur.INACTIVE
        self.tte.save()
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        bougie(self.iwda, MARDI_MATIN - timedelta(minutes=5), "100")
        self.assertEqual(set(marche(MARDI_MATIN)), {"IWDA.AS"})


class IndiceTests(Base):
    def test_premier_passage_achete_l_indice(self):
        bougie(self.iwda, MARDI_MATIN - timedelta(minutes=5), "100")
        executer(MARDI_MATIN)
        self.p.refresh_from_db()
        # 99 parts à 100,10 = 9 909,90 ; courtage 4,95 ; TOB ETF 0,12 % = 11,89.
        self.assertEqual(self.p.indice_quantite, Decimal(99))
        self.assertEqual(self.p.indice_liquidites, Decimal("73.26"))
        self.assertEqual(self.p.demarre, MARDI_MATIN)
        self.assertEqual(self.p.liquidites, Decimal("10000"))
        # Détail des frais gardé sur un ordre sans position.
        ordre = Ordre.objects.get()
        self.assertEqual((ordre.valeur, ordre.position, ordre.sens), (self.iwda, None, SensOrdre.ACHAT))
        self.assertEqual((ordre.quantite, ordre.prix, ordre.montant_eur), (99, Decimal("100.1000"), Decimal("9909.90")))
        self.assertEqual((ordre.courtage, ordre.change, ordre.tob), (Decimal("4.95"), Decimal("0.00"), Decimal("11.89")))
        self.assertEqual(ordre.frais_total, self.p.capital_initial - self.p.indice_liquidites - ordre.montant_eur)

        bougie(self.iwda, MARDI_MATIN, "90")
        executer(MARDI_MATIN + timedelta(minutes=5))
        self.p.refresh_from_db()
        self.assertEqual(self.p.indice_quantite, Decimal(99))
        self.assertEqual(self.p.demarre, MARDI_MATIN)
        self.assertEqual(Ordre.objects.count(), 1)

    def test_indice_sans_cours_pas_de_demarrage(self):
        resultat = executer(MARDI_MATIN)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.demarre)
        self.assertEqual(self.p.indice_quantite, 0)
        self.assertEqual(resultat["portefeuilles"]["Technique"]["sans_cours"], {"IWDA.AS": "pas de cours récent"})
        self.assertFalse(Valorisation.objects.exists())

    def test_valorisation_enregistree(self):
        bougie(self.iwda, MARDI_MATIN - timedelta(minutes=5), "100")
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "110")
        self.position(self.tte)
        executer(MARDI_MATIN)
        v = Valorisation.objects.get(portefeuille=self.p)
        self.assertEqual(v.instant, MARDI_MATIN)
        self.assertEqual(v.liquidites, Decimal("10000.00"))
        self.assertEqual(v.titres, Decimal("1100.00"))
        self.assertEqual(v.total, Decimal("11100.00"))
        self.assertEqual(v.indice_total, Decimal("9973.26"))


class DecisionsExecuteesTests(Base):
    def setUp(self):
        super().setUp()
        self.demarrer()

    def test_achat_execute_une_seule_fois(self):
        d = self.decision(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        executer(MARDI_MATIN)
        bougie(self.tte, MARDI_MATIN, "100")
        executer(MARDI_MATIN + timedelta(minutes=5))

        ordre = Ordre.objects.get()
        self.assertEqual((ordre.sens, ordre.quantite, ordre.prix), (SensOrdre.ACHAT, 49, Decimal("100.1000")))
        self.assertEqual(ordre.decision, d)
        self.assertEqual(ordre.montant_eur, Decimal("4904.90"))
        self.assertEqual((ordre.courtage, ordre.change, ordre.tob), (Decimal("3.00"), Decimal("0.00"), Decimal("17.17")))
        self.assertEqual(ordre.frais_total, Decimal("20.17"))
        d.refresh_from_db()
        self.assertEqual(d.executee, MARDI_MATIN)
        self.assertEqual(d.action, ActionDecision.ACHETER)
        position = Position.objects.get()
        self.assertEqual(position.cout_entree_eur, Decimal("4925.07"))
        self.assertEqual(position.plus_haut, Decimal("100.1000"))
        self.p.refresh_from_db()
        self.assertEqual(self.p.liquidites, Decimal("5074.93"))

    def test_refus_de_la_strategie_enregistre(self):
        Portefeuille.objects.filter(pk=self.p.pk).update(liquidites=Decimal("50"))
        d = self.decision(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        executer(MARDI_MATIN)
        d.refresh_from_db()
        self.assertEqual(d.action, ActionDecision.REFUSER)
        self.assertIn("liquidités insuffisantes", d.motif)
        self.assertFalse(Ordre.objects.exists())

    def test_erreur_de_frais_enregistree_comme_refus(self):
        d = self.decision(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        with mock.patch(
            "courtage.broker.calculer_frais", side_effect=ValueError("Aucune règle de courtage")
        ):
            executer(MARDI_MATIN)
        d.refresh_from_db()
        self.assertEqual(d.action, ActionDecision.REFUSER)
        self.assertIn("Aucune règle de courtage", d.motif)
        self.assertFalse(Ordre.objects.exists())

    def test_valeur_sans_cours_gardee_puis_abandonnee_le_lendemain(self):
        d = self.decision(self.aapl)
        resultat = executer(MARDI_MATIN)  # New York fermé
        self.assertEqual(resultat["portefeuilles"]["Technique"]["en_attente"], {"AAPL": "place fermée"})
        executer(MARDI_MATIN + timedelta(hours=1))
        d.refresh_from_db()
        self.assertEqual(d.action, ActionDecision.ACHETER)
        self.assertIsNone(d.executee)

        executer(MERCREDI_MATIN)
        d.refresh_from_db()
        self.assertEqual(d.action, ActionDecision.REFUSER)
        self.assertIn("abandonnée", d.motif)
        self.assertFalse(Ordre.objects.exists())

    def test_vente_sur_signal(self):
        self.position(self.tte)
        d = self.decision(self.tte, ActionDecision.VENDRE, VENTE)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        executer(MARDI_MATIN)
        position = Position.objects.get()
        self.assertIsNotNone(position.fermee_le)
        self.assertIn("signal de vente", position.motif_sortie)
        self.assertEqual(Ordre.objects.get().decision, d)


class StopsTests(Base):
    def setUp(self):
        super().setUp()
        self.demarrer()

    def test_stop_loss_ferme_la_position(self):
        self.position(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "94")
        executer(MARDI_MATIN)
        position = Position.objects.get()
        self.assertEqual(position.fermee_le, MARDI_MATIN)
        self.assertEqual(position.motif_sortie, "stop-loss −5 %")
        self.assertEqual(position.prix_sortie, Decimal("93.9060"))
        # 939,06 − (courtage 3,00 + TOB 3,29).
        self.assertEqual(position.produit_sortie_eur, Decimal("932.77"))
        ordre = Ordre.objects.get()
        self.assertEqual((ordre.sens, ordre.frais_total), (SensOrdre.VENTE, Decimal("6.29")))
        self.assertEqual(ordre.decision.action, ActionDecision.VENDRE)
        self.p.refresh_from_db()
        self.assertEqual(self.p.liquidites, Decimal("10932.77"))

    def test_plus_haut_mis_a_jour(self):
        self.position(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "103")
        executer(MARDI_MATIN)
        self.assertEqual(Position.objects.get().plus_haut, Decimal("103"))
        bougie(self.tte, MARDI_MATIN, "101")
        executer(MARDI_MATIN + timedelta(minutes=5))
        self.assertEqual(Position.objects.get().plus_haut, Decimal("103"))

    def bougie_5m(self, cloture, bas, haut):
        return Bougie.objects.create(
            valeur=self.tte, intervalle="5m", debut=MARDI_MATIN - timedelta(minutes=5),
            ouverture=Decimal(cloture), haut=Decimal(haut), bas=Decimal(bas), cloture=Decimal(cloture), volume=1,
        )

    def test_stop_declenche_par_le_plus_bas_execute_au_dernier_cours(self):
        self.position(self.tte)
        self.bougie_5m("96", bas="94.5", haut="96")
        executer(MARDI_MATIN)
        position = Position.objects.get()
        self.assertEqual(position.motif_sortie, "stop-loss −5 %")
        # Dernier cours 96 moins 0,1 % de glissement, et non le plus bas.
        self.assertEqual(position.prix_sortie, Decimal("95.9040"))

    def test_plus_haut_de_la_bougie_arme_le_suiveur(self):
        self.position(self.tte)
        self.bougie_5m("104", bas="103", haut="106")
        executer(MARDI_MATIN)
        position = Position.objects.get()
        self.assertEqual(position.plus_haut, Decimal("106"))
        self.assertIsNone(position.fermee_le)

    def test_position_sans_cours_signalee(self):
        self.position(self.aapl, prix="200", taux="0.9")
        resultat = executer(MARDI_MATIN)
        self.assertEqual(resultat["portefeuilles"]["Technique"]["sans_cours"], {"AAPL": "place fermée"})
        self.assertIsNone(Position.objects.get().fermee_le)


class ReconciliationTests(Base):
    def test_liquidites_egales_aux_ordres_au_centime(self):
        capital = self.p.capital_initial
        TauxChange.objects.create(devise="USD", instant=MARDI_APREM - timedelta(hours=1), taux=Decimal("0.9123"))
        bougie(self.iwda, MARDI_APREM - timedelta(minutes=5), "100")
        bougie(self.tte, MARDI_APREM - timedelta(minutes=5), "100.37")
        bougie(self.aapl, MARDI_APREM - timedelta(minutes=5), "201.13")
        self.decision(self.tte)
        self.decision(self.aapl)
        executer(MARDI_APREM)
        self.assertEqual(Position.objects.filter(fermee_le__isnull=True).count(), 2)

        # Stop-loss sur AAPL (−6 %).
        bougie(self.aapl, MARDI_APREM + timedelta(minutes=25), "189.06")
        executer(MARDI_APREM + timedelta(minutes=30))
        # Vente de TTE sur signal le lendemain.
        self.decision(self.tte, ActionDecision.VENDRE, VENTE, pour_le=MERCREDI)
        bougie(self.tte, MERCREDI_MATIN - timedelta(minutes=5), "104.71")
        executer(MERCREDI_MATIN)
        self.assertFalse(Position.objects.filter(fermee_le__isnull=True).exists())

        portefeuille = Ordre.objects.filter(position__isnull=False)
        achats = portefeuille.filter(sens=SensOrdre.ACHAT).aggregate(
            s=Sum(F("montant_eur") + F("frais_total"))
        )["s"]
        ventes = portefeuille.filter(sens=SensOrdre.VENTE).aggregate(
            s=Sum(F("montant_eur") - F("frais_total"))
        )["s"]
        self.assertEqual(portefeuille.count(), 4)
        self.assertTrue(portefeuille.filter(change__gt=0).exists())
        indice = Ordre.objects.get(position__isnull=True)
        cout_indice = indice.montant_eur + indice.frais_total
        self.assertEqual(cout_indice, Decimal("9926.74"))
        self.p.refresh_from_db()
        # Deux poches de `capital_initial` : le portefeuille, et l'indice acheté au départ et gardé.
        self.assertEqual(self.p.liquidites, capital - achats + ventes)
        self.assertEqual(self.p.indice_liquidites, capital - cout_indice)
        self.assertEqual(
            2 * capital - achats + ventes - cout_indice, self.p.liquidites + self.p.indice_liquidites
        )
        for position in Position.objects.all():
            achat = position.ordres.get(sens=SensOrdre.ACHAT)
            vente = position.ordres.get(sens=SensOrdre.VENTE)
            self.assertEqual(position.cout_entree_eur, achat.montant_eur + achat.frais_total)
            self.assertEqual(position.produit_sortie_eur, vente.montant_eur - vente.frais_total)


def historique(valeur, jours, jusqu_au=MARDI):
    for i in range(jours):
        jour = jusqu_au - timedelta(days=jours - 1 - i)
        bougie(valeur, datetime(jour.year, jour.month, jour.day, tzinfo=UTC), str(100 + i % 7), "1d")


class DeciderDuJourTests(Base):
    def signaux(self, *sens):
        return [Signal("rsi", Sens(s), f"détail {s}") for s in sens]

    def test_prochain_jour_ouvre(self):
        self.assertEqual(prochain_jour_ouvre(MARDI), MERCREDI)
        self.assertEqual(prochain_jour_ouvre(date(2026, 11, 13)), date(2026, 11, 16))

    def test_pas_avant_22h30(self):
        historique(self.tte, 130)
        resultat = decider_du_jour(MARDI_SOIR.replace(hour=22, minute=0))
        self.assertIn("attente", resultat)
        self.assertFalse(Decision.objects.exists())

    def test_achat_decide_pour_le_jour_ouvre_suivant(self):
        historique(self.tte, 130)
        historique(self.aapl, 30, jusqu_au=MARDI - timedelta(days=1))
        with mock.patch.object(
            execution, "signaux_du_jour", return_value=self.signaux("achat", "achat")
        ) as calcul:
            resultat = decider_du_jour(MARDI_SOIR)
        bougies = calcul.call_args.args[0]
        self.assertEqual(len(bougies), 120)
        self.assertEqual(bougies[-1].jour, MARDI)
        self.assertLess(bougies[0].jour, bougies[1].jour)

        d = Decision.objects.get(valeur=self.tte)
        self.assertEqual(d.action, ActionDecision.ACHETER)
        self.assertEqual(d.pour_le, MERCREDI)
        self.assertEqual(d.signaux["score"], 2)
        self.assertEqual(d.signaux["signaux"][0]["sens"], "achat")
        self.assertEqual(resultat["portefeuilles"]["Technique"]["sans_bougie"], ["AAPL"])

    def test_idempotent(self):
        historique(self.tte, 60)
        with mock.patch.object(
            execution, "signaux_du_jour", return_value=self.signaux("achat", "achat")
        ) as calcul:
            decider_du_jour(MARDI_SOIR)
            nombre = Decision.objects.count()
            resultat = decider_du_jour(MARDI_SOIR + timedelta(minutes=5))
        self.assertEqual(Decision.objects.count(), nombre)
        # Tous les portefeuilles ont déjà décidé : les signaux ne sont pas recalculés.
        self.assertEqual(calcul.call_count, 1)
        self.assertTrue(resultat["deja_decide"])
        self.assertEqual(Decision.objects.filter(valeur=self.tte).count(), 1)

    def test_vente_seulement_si_detenue(self):
        historique(self.tte, 60)
        historique(self.aapl, 60)
        self.position(self.tte)
        with mock.patch.object(execution, "signaux_du_jour", return_value=self.signaux("vente")):
            decider_du_jour(MARDI_SOIR)
        self.assertEqual(Decision.objects.get(valeur=self.tte).action, ActionDecision.VENDRE)
        self.assertFalse(Decision.objects.filter(valeur=self.aapl).exists())

    def test_reference_exclue(self):
        historique(self.iwda, 60)
        with mock.patch.object(execution, "signaux_du_jour", return_value=self.signaux("achat", "achat")) as calcul:
            decider_du_jour(MARDI_SOIR)
        calcul.assert_not_called()


class RaisonsEtBruitTests(Base):
    def setUp(self):
        super().setUp()
        self.demarrer()

    def test_raisons_d_attente(self):
        self.decision(self.tte)
        self.decision(self.aapl)
        bougie(self.aapl, MARDI_APREM - timedelta(minutes=5), "200")
        resultat = executer(MARDI_APREM)
        self.assertEqual(
            resultat["portefeuilles"]["Technique"]["en_attente"],
            {"TTE.PA": "pas de cours récent", "AAPL": "pas de taux USD récent"},
        )

    def test_stop_refuse_une_seule_fois_par_jour(self):
        self.position(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "94")
        bougie(self.tte, MARDI_MATIN, "94")
        bougie(self.tte, MERCREDI_MATIN - timedelta(minutes=5), "94")
        with mock.patch("courtage.broker.calculer_frais", side_effect=ValueError("Aucune règle")):
            executer(MARDI_MATIN)
            resultat = executer(MARDI_MATIN + timedelta(minutes=5))
            self.assertEqual(Decision.objects.filter(action=ActionDecision.REFUSER).count(), 1)
            self.assertTrue(resultat["portefeuilles"]["Technique"]["refus"])
            executer(MERCREDI_MATIN)
        self.assertEqual(Decision.objects.filter(action=ActionDecision.REFUSER).count(), 2)
        self.assertIsNone(Position.objects.get().fermee_le)

    def test_achat_de_l_indice_refuse_une_seule_fois_par_jour(self):
        Portefeuille.objects.filter(pk=self.p.pk).update(demarre=None)
        bougie(self.iwda, MARDI_MATIN - timedelta(minutes=5), "100")
        bougie(self.iwda, MARDI_MATIN, "100")
        with mock.patch("courtage.broker.calculer_frais", side_effect=ValueError("Aucune règle")):
            executer(MARDI_MATIN)
            executer(MARDI_MATIN + timedelta(minutes=5))
        refus = Decision.objects.get(action=ActionDecision.REFUSER)
        self.assertEqual(refus.valeur, self.iwda)
        self.assertIn("Aucune règle", refus.motif)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.demarre)


class ValeurDesactiveeDetenueTests(Base):
    """Une valeur désactivée encore détenue reste surveillée et vendable, jamais achetée."""

    def setUp(self):
        super().setUp()
        self.demarrer()
        self.tte.statut = StatutValeur.INACTIVE
        self.tte.save()

    def test_toujours_cotee(self):
        self.position(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        self.assertIn("TTE.PA", marche(MARDI_MATIN))

    def test_stop_toujours_declenche(self):
        self.position(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "94")
        executer(MARDI_MATIN)
        self.assertEqual(Position.objects.get().motif_sortie, "stop-loss −5 %")

    def test_signal_de_vente_decide_et_execute(self):
        self.position(self.tte)
        historique(self.tte, 60)
        historique(self.aapl, 60)
        Valeur.objects.filter(pk=self.aapl.pk).update(statut=StatutValeur.INACTIVE)
        signaux = [Signal("rsi", Sens.VENTE, "RSI haut")]
        with mock.patch.object(execution, "signaux_du_jour", return_value=signaux):
            decider_du_jour(MARDI_SOIR)
        d = Decision.objects.get(valeur=self.tte)
        self.assertEqual((d.action, d.pour_le), (ActionDecision.VENDRE, MERCREDI))
        self.assertFalse(Decision.objects.filter(valeur=self.aapl).exists())
        bougie(self.tte, MERCREDI_MATIN - timedelta(minutes=5), "100")
        executer(MERCREDI_MATIN)
        self.assertIn("signal de vente", Position.objects.get().motif_sortie)

    def test_pas_d_achat_decide_sur_une_valeur_inactive(self):
        historique(self.tte, 60)
        signaux = [Signal("rsi", Sens.ACHAT, "a"), Signal("cassure", Sens.ACHAT, "b")]
        with mock.patch.object(execution, "signaux_du_jour", return_value=signaux):
            decider_du_jour(MARDI_SOIR)
        self.assertFalse(Decision.objects.filter(valeur=self.tte).exists())

    def test_achat_decide_avant_la_desactivation_refuse(self):
        d = self.decision(self.tte)
        bougie(self.tte, MARDI_MATIN - timedelta(minutes=5), "100")
        executer(MARDI_MATIN)
        d.refresh_from_db()
        self.assertEqual(d.action, ActionDecision.REFUSER)
        self.assertIn("valeur désactivée", d.motif)
        self.assertFalse(Position.objects.exists())


class IsolementTests(Base):
    def test_un_portefeuille_en_panne_n_arrete_pas_les_autres(self):
        Portefeuille.objects.create(nom="Casse", indice=self.iwda)
        bougie(self.iwda, MARDI_MATIN - timedelta(minutes=5), "100")
        original = execution._Passage.derouler

        def derouler(passage):
            if passage.p.nom == "Casse":
                raise RuntimeError("panne")
            return original(passage)

        with (
            mock.patch.object(execution._Passage, "derouler", derouler),
            mock.patch.object(execution.sentry_sdk, "capture_exception") as sentry,
            self.assertLogs("portefeuille.execution", "ERROR"),
        ):
            resultat = executer(MARDI_MATIN)
        self.assertEqual(resultat["portefeuilles"]["Casse"], {"erreur": "panne"})
        sentry.assert_called_once()
        self.assertTrue(Valorisation.objects.filter(portefeuille=self.p).exists())
        self.assertFalse(Valorisation.objects.filter(portefeuille__nom="Casse").exists())
