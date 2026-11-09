from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase

from sources.yahoo import SourceYahoo

DEPUIS = datetime(2026, 11, 9, tzinfo=UTC)


def table(lignes):
    """DataFrame au format yfinance : index horodaté UTC, colonnes OHLCV."""
    index = pd.DatetimeIndex([ligne[0] for ligne in lignes], tz="UTC")
    return pd.DataFrame(
        [ligne[1:] for ligne in lignes],
        index=index, columns=["Open", "High", "Low", "Close", "Volume"],
    )


def telechargement(**par_ticker):
    """Faux résultat de `yfinance.download(group_by="ticker")` : colonnes (ticker, champ)."""
    return pd.concat(par_ticker, axis=1)


@mock.patch("sources.yahoo.yfinance.download")
class SourceYahooTests(SimpleTestCase):
    def test_ligne_nan_ecartee(self, download):
        nan = float("nan")
        download.return_value = telechargement(
            AAPL=table([
                ("2026-11-09 14:30", 10, 11, 9, 10.5, 100),
                ("2026-11-09 14:35", nan, nan, nan, nan, nan),
            ]),
            MSFT=table([("2026-11-09 14:30", 20, 21, 19, 20.5, 200)]),
        )
        source = SourceYahoo()
        resultat = source.bougies(["AAPL", "MSFT"], "5m", DEPUIS)
        self.assertEqual(len(resultat["AAPL"]), 1)
        self.assertEqual(resultat["AAPL"][0].cloture, Decimal("10.5000"))
        self.assertEqual(resultat["AAPL"][0].volume, 100)
        self.assertEqual(resultat["AAPL"][0].debut, datetime(2026, 11, 9, 14, 30, tzinfo=UTC))
        self.assertEqual(len(resultat["MSFT"]), 1)
        self.assertEqual(source.erreurs, {})
        self.assertEqual(download.call_args.kwargs["group_by"], "ticker")
        self.assertFalse(download.call_args.kwargs["auto_adjust"])

    def test_ticker_absent_signale_dans_erreurs(self, download):
        download.return_value = telechargement(
            AAPL=table([("2026-11-09 14:30", 10, 11, 9, 10.5, 100)])
        )
        source = SourceYahoo()
        resultat = source.bougies(["AAPL", "ZZZZ"], "5m", DEPUIS)
        self.assertIn("AAPL", resultat)
        self.assertNotIn("ZZZZ", resultat)
        self.assertIn("ZZZZ", source.erreurs)

    def test_download_qui_leve_ne_leve_pas(self, download):
        download.side_effect = RuntimeError("réseau coupé")
        source = SourceYahoo()
        with self.assertLogs("sources.yahoo", "WARNING"):
            self.assertEqual(source.bougies(["AAPL", "MSFT"], "5m", DEPUIS), {})
        self.assertEqual(set(source.erreurs), {"AAPL", "MSFT"})

    def test_erreurs_remises_a_zero(self, download):
        download.side_effect = RuntimeError("x")
        source = SourceYahoo()
        with self.assertLogs("sources.yahoo", "WARNING"):
            source.bougies(["AAPL"], "5m", DEPUIS)
        download.side_effect = None
        download.return_value = telechargement(
            AAPL=table([("2026-11-09 14:30", 10, 11, 9, 10.5, 100)])
        )
        source.bougies(["AAPL"], "5m", DEPUIS)
        self.assertEqual(source.erreurs, {})

    def test_colonne_toute_nan_signalee(self, download):
        nan = float("nan")
        download.return_value = telechargement(
            AAPL=table([("2026-11-09 14:30", nan, nan, nan, nan, nan)])
        )
        source = SourceYahoo()
        self.assertEqual(source.bougies(["AAPL"], "5m", DEPUIS)["AAPL"], [])
        self.assertEqual(source.erreurs, {"AAPL": "aucune bougie exploitable"})

    def test_5m_vide_est_legitime_mais_pas_1d(self, download):
        vide = table([("2026-11-09 14:30", 1, 1, 1, 1, 1)]).iloc[0:0]
        download.return_value = telechargement(AAPL=vide)
        source = SourceYahoo()
        source.bougies(["AAPL"], "5m", DEPUIS)
        self.assertEqual(source.erreurs, {})
        source.bougies(["AAPL"], "1d", DEPUIS)
        self.assertEqual(source.erreurs, {"AAPL": "aucune bougie exploitable"})

    def test_ticker_unique_et_date_journaliere_sans_fuseau(self, download):
        index = pd.DatetimeIndex(["2026-11-09"])  # forme réelle de yfinance en 1d : sans fuseau
        brut = pd.DataFrame([[10, 11, 9, 10.5, 100]], index=index,
                            columns=["Open", "High", "Low", "Close", "Volume"])
        download.return_value = telechargement(AAPL=brut)
        resultat = SourceYahoo().bougies(["AAPL"], "1d", DEPUIS)
        self.assertEqual(resultat["AAPL"][0].debut, datetime(2026, 11, 9, tzinfo=UTC))

    def test_download_avec_timeout_et_threads(self, download):
        download.return_value = telechargement(AAPL=table([("2026-11-09 15:00", 1, 1, 1, 1, 1)]))
        SourceYahoo().bougies(["AAPL"], "5m", DEPUIS)
        _, kwargs = download.call_args
        self.assertEqual((kwargs["timeout"], kwargs["threads"]), (10, 4))

    def test_taux_eur(self, download):
        download.return_value = telechargement(**{
            "EURUSD=X": table([("2026-11-09", 1.25, 1.25, 1.25, 1.25, 0)])
        })
        self.assertEqual(SourceYahoo().taux_eur("USD"), Decimal("0.800000"))
        self.assertEqual(SourceYahoo().taux_eur("EUR"), Decimal(1))
