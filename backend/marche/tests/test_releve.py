from datetime import UTC, datetime
from decimal import Decimal

from django.test import TestCase

from marche.models import Bougie, StatutValeur, TauxChange, Valeur
from marche.releve import relever_cours
from sources.cours import BougieBrute


def brute(debut, cloture="10"):
    c = Decimal(cloture)
    return BougieBrute(debut=debut, ouverture=c, haut=c, bas=c, cloture=c, volume=5)


class SourceFactice:
    code = "factice"

    def __init__(self, bougies=None, erreurs=None):
        self._bougies = bougies or {}
        self._erreurs = erreurs or {}
        self.erreurs = {}
        self.appels = []

    def bougies(self, tickers, intervalle, depuis):
        self.appels.append((list(tickers), intervalle, depuis))
        self.erreurs = {t: m for t, m in self._erreurs.items() if t in tickers}
        return {t: self._bougies[(t, intervalle)] for t in tickers
                if (t, intervalle) in self._bougies}

    def taux_eur(self, devise):
        return Decimal("0.8")


def valeur(ticker, place, devise, statut=StatutValeur.ACTIVE):
    return Valeur.objects.create(ticker=ticker, nom=ticker, place=place, devise=devise, statut=statut)


# Lundi 2026-11-09 : 15:00 UTC = 10:00 à New York et 16:00 à Paris (tous deux en séance).
MILIEU = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


class RelevéCinqMinutesTests(TestCase):
    def test_seules_les_valeurs_actives_en_seance_sont_demandees(self):
        valeur("AAPL", "NASDAQ", "USD")
        valeur("TTE.PA", "XPAR", "EUR")
        valeur("MSFT", "NASDAQ", "USD", StatutValeur.PROPOSEE)
        source = SourceFactice()
        relever_cours(datetime(2026, 11, 9, 8, 0, tzinfo=UTC), source)  # US fermé, Paris ouvert
        self.assertEqual(source.appels[0][:2], (["TTE.PA"], "5m"))
        self.assertEqual(len(source.appels), 1)

    def test_fermee_depuis_moins_de_30_minutes_est_relevee(self):
        valeur("TTE.PA", "XPAR", "EUR")
        source = SourceFactice()
        relever_cours(datetime(2026, 11, 9, 16, 40, tzinfo=UTC), source)  # 17:40 à Paris
        self.assertEqual(source.appels[0][0], ["TTE.PA"])

    def test_idempotent(self):
        valeur("TTE.PA", "XPAR", "EUR")
        debut = datetime(2026, 11, 9, 14, 55, tzinfo=UTC)
        source = SourceFactice({("TTE.PA", "5m"): [brute(debut)]})
        relever_cours(MILIEU, source)
        resultat = relever_cours(MILIEU, source)
        self.assertEqual(Bougie.objects.count(), 1)
        self.assertEqual(resultat["bougies"], 1)

    def test_met_a_jour_une_bougie_existante(self):
        valeur("TTE.PA", "XPAR", "EUR")
        debut = datetime(2026, 11, 9, 14, 55, tzinfo=UTC)
        relever_cours(MILIEU, SourceFactice({("TTE.PA", "5m"): [brute(debut, "10")]}))
        relever_cours(MILIEU, SourceFactice({("TTE.PA", "5m"): [brute(debut, "11")]}))
        self.assertEqual(Bougie.objects.get().cloture, Decimal("11.0000"))

    def test_reprend_depuis_la_derniere_bougie(self):
        valeur("TTE.PA", "XPAR", "EUR")
        debut = datetime(2026, 11, 9, 14, 55, tzinfo=UTC)
        relever_cours(MILIEU, SourceFactice({("TTE.PA", "5m"): [brute(debut)]}))
        source = SourceFactice()
        relever_cours(MILIEU, source)
        self.assertEqual(source.appels[0][2], debut)

    def test_erreur_sur_un_ticker_laisse_les_autres(self):
        valeur("TTE.PA", "XPAR", "EUR")
        valeur("AIR.PA", "XPAR", "EUR")
        debut = datetime(2026, 11, 9, 14, 55, tzinfo=UTC)
        source = SourceFactice(
            {("TTE.PA", "5m"): [brute(debut)]}, erreurs={"AIR.PA": "introuvable"}
        )
        resultat = relever_cours(MILIEU, source)
        self.assertEqual(Bougie.objects.get().valeur.ticker, "TTE.PA")
        self.assertEqual(resultat["erreurs"], {"AIR.PA": "introuvable"})
        self.assertEqual(resultat["valeurs"], 2)

    def test_enregistre_le_taux_usd(self):
        valeur("AAPL", "NASDAQ", "USD")
        relever_cours(MILIEU, SourceFactice())
        self.assertEqual(TauxChange.objects.get(devise="USD").taux, Decimal("0.800000"))

    def test_pas_de_taux_sans_valeur_usd(self):
        valeur("TTE.PA", "XPAR", "EUR")
        relever_cours(MILIEU, SourceFactice())
        self.assertFalse(TauxChange.objects.exists())


class RelevéJournalierTests(TestCase):
    # 17:00 UTC = 18:00 à Paris : fermé depuis 30 min, bougie du jour à relever.
    APRES = datetime(2026, 11, 9, 17, 0, tzinfo=UTC)
    # Minuit local à Paris en novembre (UTC+1) = 23:00 UTC la veille.
    MINUIT = datetime(2026, 11, 8, 23, 0, tzinfo=UTC)

    def test_releve_les_bougies_du_jour_apres_la_fermeture(self):
        valeur("TTE.PA", "XPAR", "EUR")
        source = SourceFactice({("TTE.PA", "1d"): [brute(self.MINUIT)]})
        relever_cours(self.APRES, source)
        self.assertEqual([a[1] for a in source.appels], ["1d"])
        self.assertEqual(Bougie.objects.get().intervalle, "1d")

    def test_une_seule_fois_par_jour(self):
        valeur("TTE.PA", "XPAR", "EUR")
        relever_cours(self.APRES, SourceFactice({("TTE.PA", "1d"): [brute(self.MINUIT)]}))
        source = SourceFactice()
        relever_cours(self.APRES, source)
        self.assertEqual(source.appels, [])

    def test_pas_avant_la_fermeture_ni_le_week_end(self):
        valeur("TTE.PA", "XPAR", "EUR")
        source = SourceFactice()
        relever_cours(datetime(2026, 11, 9, 10, 0, tzinfo=UTC), source)  # en séance
        relever_cours(datetime(2026, 11, 14, 17, 0, tzinfo=UTC), source)  # samedi
        self.assertNotIn("1d", [a[1] for a in source.appels])
