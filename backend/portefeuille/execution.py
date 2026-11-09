"""Étapes « decisions » et « execution » du cycle.

Les signaux se calculent une fois par jour sur les bougies 1d clôturées et deviennent des `Decision`
pour le jour ouvré suivant ; à chaque cycle, `executer` achète l'indice au démarrage, surveille les
stops, exécute les décisions du jour dont la valeur est cotable, puis revalorise le portefeuille.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import sentry_sdk
from django.db import transaction
from django.db.models import Q

from analyse.signaux import BougieJour, Sens, Signal, score, signaux_du_jour
from courtage.broker import Broker, Execution, OrdreDemande, broker
from courtage.frais import CENTIME
from courtage.models import Bareme
from marche.models import Bougie, StatutValeur, TauxChange, Valeur
from marche.seances import FUSEAU_PLACE

from .marche_actuel import marche_et_absences
from .models import ActionDecision, Decision, Ordre, Portefeuille, Position, SensOrdre, Valorisation
from .strategie import Cotation, Marche, PositionVue, Regles, decider, stops

logger = logging.getLogger(__name__)

# Toutes les places européennes et américaines sont fermées, et leur bougie 1d relevée.
HEURE_DECISION = time(22, 30)
HISTORIQUE = 120  # bougies 1d lues pour les signaux


def prochain_jour_ouvre(jour: date) -> date:
    suivant = jour + timedelta(days=1)
    while suivant.weekday() >= 5:
        suivant += timedelta(days=1)
    return suivant


def _minuit(jour: date) -> datetime:
    """Convention des bougies 1d : minuit UTC de la date locale de la séance."""
    return datetime(jour.year, jour.month, jour.day, tzinfo=UTC)


def _bougies_jour(valeur: Valeur, jour: date) -> list[BougieJour]:
    """Les `HISTORIQUE` dernières bougies 1d jusqu'à `jour` inclus, par jour croissant."""
    lignes = Bougie.objects.filter(
        valeur=valeur, intervalle="1d", debut__lt=_minuit(jour) + timedelta(days=1)
    ).order_by("-debut")[:HISTORIQUE]
    return [
        BougieJour(jour=b.debut.date(), ouverture=b.ouverture, haut=b.haut, bas=b.bas, cloture=b.cloture)
        for b in reversed(lignes)
    ]


def _signaux_json(signaux: list[Signal]) -> dict:
    return {
        "score": score(signaux),
        "signaux": [{"code": s.code, "sens": s.sens.value, "detail": s.detail} for s in signaux],
    }


def _signaux_depuis(donnees: dict) -> list[Signal]:
    return [Signal(s["code"], Sens(s["sens"]), s["detail"]) for s in donnees.get("signaux", [])]


def decider_du_jour(maintenant: datetime) -> dict:
    """Décisions du jour pour chaque portefeuille actif, une seule fois par jour (idempotent)."""
    maintenant = maintenant.astimezone(UTC)
    if maintenant.time() < HEURE_DECISION:
        return {"attente": "avant 22:30 UTC"}
    jour = maintenant.date()
    pour_le = prochain_jour_ouvre(jour)
    portefeuilles = Portefeuille.objects.filter(actif=True)
    if not portefeuilles.exclude(decisions__pour_le=pour_le).exists():
        return {"jour": jour, "deja_decide": True}

    # Les signaux ne dépendent que des cours : calculés une fois pour tous les portefeuilles. Une valeur
    # désactivée encore détenue garde ses signaux (pour la vendre), sans jamais être achetée.
    signaux: dict[str, list[Signal]] = {}
    sans_bougie: list[str] = []
    achetables = set(Valeur.objects.actives().filter(reference=False).values_list("ticker", flat=True))
    analysees = Valeur.objects.filter(
        Q(ticker__in=achetables) | Q(pk__in=Valeur.objects.detenues().filter(reference=False))
    ).order_by("ticker")
    for valeur in analysees:
        bougies = _bougies_jour(valeur, jour)
        if not bougies or bougies[-1].jour != jour:
            sans_bougie.append(valeur.ticker)
            continue
        signaux[valeur.ticker] = signaux_du_jour(bougies)
    if not signaux:
        return {"attente": "aucune bougie journalière du jour", "sans_bougie": sans_bougie}

    valeurs = {v.ticker: v for v in Valeur.objects.filter(ticker__in=signaux)}
    resultat: dict = {"jour": jour, "portefeuilles": {}}
    for p in portefeuilles:
        with transaction.atomic():
            p = Portefeuille.objects.select_for_update().get(pk=p.pk)
            if p.decisions.filter(pour_le=pour_le).exists():
                resultat["portefeuilles"][p.nom] = {"deja_decide": True}
                continue
            resultat["portefeuilles"][p.nom] = _decider_portefeuille(
                p, signaux, valeurs, achetables, sans_bougie, maintenant, pour_le
            )
    return resultat


def _decider_portefeuille(p, signaux, valeurs, achetables, sans_bougie, maintenant, pour_le) -> dict:
    detenus = set(p.positions.filter(fermee_le__isnull=True).values_list("valeur__ticker", flat=True))
    regles = Regles.depuis(p)
    decisions = []
    for ticker in sorted(signaux):
        liste = signaux[ticker]
        s = score(liste)
        if ticker in detenus and s <= -1:
            action, motif = ActionDecision.VENDRE, f"signal de vente (score −{-s})"
        elif (
            ticker not in detenus
            and ticker in achetables
            and s >= regles.score_achat
            and not any(x.sens is Sens.VENTE for x in liste)
        ):
            action, motif = ActionDecision.ACHETER, f"signaux d'achat (score {s})"
        else:
            continue
        details = " ; ".join(x.detail for x in liste)
        decisions.append(
            Decision(
                portefeuille=p, valeur=valeurs[ticker], instant=maintenant, action=action,
                motif=f"{motif} : {details}", signaux=_signaux_json(liste), pour_le=pour_le,
            )
        )
    # Ligne de synthèse : trace de l'analyse et marque « déjà décidé » même sans ordre.
    decisions.append(
        Decision(
            portefeuille=p, instant=maintenant, action=ActionDecision.GARDER,
            motif=(
                f"Analyse du {maintenant.date()} : {len(signaux)} valeurs, {len(decisions)} décisions"
                + (f" ; sans bougie du jour : {', '.join(sans_bougie)}" if sans_bougie else "")
            ),
            signaux={"analysees": len(signaux), "sans_bougie": sans_bougie},
            pour_le=pour_le,
        )
    )
    Decision.objects.bulk_create(decisions)
    return {"decisions": len(decisions) - 1, "sans_bougie": sans_bougie}


def executer(maintenant: datetime) -> dict:
    """Un passage d'exécution par portefeuille actif, chacun sous verrou de sa ligne."""
    maintenant = maintenant.astimezone(UTC)
    cotations, absences = marche_et_absences(maintenant)
    resultat: dict = {"cotees": len(cotations), "portefeuilles": {}}
    for pk, nom in Portefeuille.objects.filter(actif=True).values_list("pk", "nom"):
        # Un portefeuille en panne n'empêche ni l'exécution ni la valorisation des autres.
        try:
            with transaction.atomic():
                resultat["portefeuilles"][nom] = _Passage(pk, cotations, absences, maintenant).derouler()
        except Exception as exc:
            logger.exception("Exécution du portefeuille %s en échec", nom)
            sentry_sdk.capture_exception(exc)
            resultat["portefeuilles"][nom] = {"erreur": str(exc) or type(exc).__name__}
    return resultat


class _Passage:
    def __init__(self, pk: int, cotations: Marche, absences: dict[str, str], maintenant: datetime):
        # Verrou de la ligne : deux passages simultanés n'exécutent pas deux fois la même décision.
        self.p = Portefeuille.objects.select_for_update().select_related("indice").get(pk=pk)
        self.cotations = cotations
        self.absences = absences
        self.maintenant = maintenant
        self.jour = maintenant.date()
        self.broker: Broker = broker(self.p.broker)
        self.bilan: dict = {
            "indice": None, "ventes": [], "achats": [], "refus": [],
            "en_attente": {}, "abandonnees": 0, "sans_cours": {},
        }

    def derouler(self) -> dict:
        p = self.p
        if p.demarre is None:
            self._acheter_indice()

        ouvertes = {
            pos.valeur.ticker: pos
            for pos in p.positions.filter(fermee_le__isnull=True).select_related("valeur")
        }
        for ticker, pos in ouvertes.items():
            cotation = self.cotations.get(ticker)
            if cotation is None:
                self.bilan["sans_cours"][ticker] = self._absence(ticker)
            elif cotation.prix > pos.plus_haut:
                pos.plus_haut = cotation.prix
                pos.save(update_fields=["plus_haut"])

        regles = Regles.depuis(p)
        for intention in stops(self._vues(ouvertes), self.cotations, regles):
            pos = ouvertes[intention.ticker]
            decision = Decision(
                portefeuille=p, valeur=pos.valeur, instant=self.maintenant,
                action=ActionDecision.VENDRE, motif=intention.motif,
            )
            if self._vendre(pos, intention.motif, decision, une_fois_par_jour=True):
                del ouvertes[intention.ticker]

        self._decisions_du_jour(ouvertes, regles)

        p.save(update_fields=["liquidites", "indice_quantite", "indice_liquidites", "demarre"])
        if p.demarre is not None:
            self._valoriser()
        return self.bilan

    def _absence(self, ticker: str) -> str:
        return self.absences.get(ticker, "valeur non relevée")

    # -- ordres ------------------------------------------------------------------------------------

    def _demande(self, sens: str, ticker: str, quantite: int) -> OrdreDemande:
        return OrdreDemande(sens, ticker, quantite, self.cotations[ticker], self.p.bareme_broker, self.jour)

    def _acheter_indice(self):
        p, ticker = self.p, self.p.indice.ticker
        cotation = self.cotations.get(ticker)
        if cotation is None:
            self.bilan["sans_cours"][ticker] = self._absence(ticker)
            return
        # Quantité entière, mêmes frais : on descend jusqu'à tenir dans le capital, frais compris.
        quantite = int(p.capital_initial // (cotation.prix * cotation.taux_eur))
        try:
            while quantite >= 1:
                ex = self.broker.executer(self._demande(SensOrdre.ACHAT, ticker, quantite))
                if ex.montant_eur + ex.frais.total <= p.capital_initial:
                    break
                quantite -= 1
        except ValueError as erreur:
            decision = Decision(
                portefeuille=p, valeur=p.indice, instant=self.maintenant,
                action=ActionDecision.ACHETER, motif="achat de l'indice de comparaison",
            )
            self._refuser(decision, str(erreur), une_fois_par_jour=True)
            return
        if quantite < 1:
            self.bilan["refus"].append(f"{ticker} : capital insuffisant pour une part")
            return
        p.indice_quantite = Decimal(quantite)
        p.indice_liquidites = p.capital_initial - ex.montant_eur - ex.frais.total
        p.demarre = self.maintenant
        # Ordre sans position : l'indice n'appartient pas au portefeuille, mais ses frais restent tracés.
        Ordre.objects.create(
            portefeuille=p, valeur=p.indice, sens=SensOrdre.ACHAT, quantite=quantite, prix=ex.prix,
            taux_eur=ex.taux_eur, montant_eur=ex.montant_eur, courtage=ex.frais.courtage,
            change=ex.frais.change, tob=ex.frais.tob, frais_total=ex.frais.total,
            instant=self.maintenant,
        )
        self.bilan["indice"] = f"{ticker} x{quantite}"

    def _executer(
        self, sens: str, ticker: str, quantite: int, decision: Decision, une_fois_par_jour=False
    ) -> Execution | None:
        """Exécution par le broker ; une erreur de frais devient un refus enregistré."""
        try:
            ex = self.broker.executer(self._demande(sens, ticker, quantite))
        except ValueError as erreur:
            self._refuser(decision, str(erreur), une_fois_par_jour)
            return None
        if sens == SensOrdre.ACHAT and ex.montant_eur + ex.frais.total > self.p.liquidites:
            self._refuser(decision, "liquidités insuffisantes à l'exécution")
            return None
        return ex

    def _refuser(self, decision: Decision, raison: str, une_fois_par_jour=False):
        """`une_fois_par_jour` : refus retenté à chaque cycle (stop, indice), enregistré une fois par jour local."""
        self.bilan["refus"].append(f"{decision.valeur.ticker} : {raison}")
        if une_fois_par_jour and self._deja_refuse(decision.valeur):
            return
        decision.action = ActionDecision.REFUSER
        decision.motif = f"{decision.motif} — refusée : {raison}"
        decision.save()

    def _deja_refuse(self, valeur: Valeur) -> bool:
        fuseau = ZoneInfo(FUSEAU_PLACE[valeur.place])
        local = self.maintenant.astimezone(fuseau).date()
        debut = datetime(local.year, local.month, local.day, tzinfo=fuseau)
        # Les refus de stop et d'indice n'ont pas de `pour_le` (ceux des décisions du jour en ont un).
        return self.p.decisions.filter(
            valeur=valeur, action=ActionDecision.REFUSER, pour_le__isnull=True,
            instant__gte=debut, instant__lt=debut + timedelta(days=1),
        ).exists()

    def _ordre(self, position: Position, sens: str, quantite: int, ex: Execution, decision: Decision):
        decision.executee = self.maintenant
        decision.save()
        Ordre.objects.create(
            portefeuille=self.p, position=position, valeur=position.valeur, sens=sens, quantite=quantite, prix=ex.prix,
            taux_eur=ex.taux_eur, montant_eur=ex.montant_eur, courtage=ex.frais.courtage,
            change=ex.frais.change, tob=ex.frais.tob, frais_total=ex.frais.total,
            instant=self.maintenant, decision=decision,
        )

    def _vendre(self, pos: Position, motif: str, decision: Decision, une_fois_par_jour=False) -> bool:
        ex = self._executer(SensOrdre.VENTE, pos.valeur.ticker, pos.quantite, decision, une_fois_par_jour)
        if ex is None:
            return False
        produit = ex.montant_eur - ex.frais.total
        pos.fermee_le = self.maintenant
        pos.prix_sortie = ex.prix
        pos.produit_sortie_eur = produit
        pos.motif_sortie = motif[:200]
        pos.save()
        self.p.liquidites += produit
        self._ordre(pos, SensOrdre.VENTE, pos.quantite, ex, decision)
        self.bilan["ventes"].append(f"{pos.valeur.ticker} x{pos.quantite} ({motif})")
        return True

    def _acheter(self, valeur: Valeur, quantite: int, decision: Decision):
        ex = self._executer(SensOrdre.ACHAT, valeur.ticker, quantite, decision)
        if ex is None:
            return
        cout = ex.montant_eur + ex.frais.total
        pos = Position.objects.create(
            portefeuille=self.p, valeur=valeur, quantite=quantite, prix_entree=ex.prix,
            taux_entree=ex.taux_eur, cout_entree_eur=cout, plus_haut=ex.prix,
            ouverte_le=self.maintenant,
        )
        self.p.liquidites -= cout
        self._ordre(pos, SensOrdre.ACHAT, quantite, ex, decision)
        self.bilan["achats"].append(f"{valeur.ticker} x{quantite}")

    # -- décisions ---------------------------------------------------------------------------------

    def _decisions_du_jour(self, ouvertes: dict[str, Position], regles: Regles):
        cotables: dict[str, Decision] = {}
        attente = self.p.decisions.filter(
            executee__isnull=True,
            action__in=[ActionDecision.ACHETER, ActionDecision.VENDRE],
            pour_le__lte=self.jour,
        ).select_related("valeur").order_by("instant", "pk")
        for d in attente:
            if d.pour_le < self.jour:
                # Jamais d'ordre sur une décision d'avant-hier : la valeur n'a pas été cotable à temps.
                d.action = ActionDecision.REFUSER
                d.motif = f"{d.motif} — abandonnée : aucun cours exploitable le {d.pour_le}"
                d.save()
                self.bilan["abandonnees"] += 1
            elif d.action == ActionDecision.ACHETER and not self._achetable(d.valeur):
                self._refuser(d, "valeur désactivée depuis la décision")
            elif d.valeur.ticker in self.cotations:
                cotables[d.valeur.ticker] = d
            else:
                self.bilan["en_attente"][d.valeur.ticker] = self._absence(d.valeur.ticker)
        if not cotables:
            return

        bareme = Bareme.en_vigueur(self.p.bareme_broker, self.jour).donnees()
        signaux = {ticker: _signaux_depuis(d.signaux) for ticker, d in cotables.items()}
        total = self.p.liquidites + self._titres(ouvertes.values())
        intentions = decider(
            self.p.liquidites, total, self._vues(ouvertes), signaux, self.cotations, regles, bareme
        )
        for intention in intentions:
            d = cotables.pop(intention.ticker, None)
            if d is None:
                continue
            if intention.action == "vendre":
                self._vendre(ouvertes[intention.ticker], intention.motif, d)
            elif intention.action == "acheter":
                self._acheter(d.valeur, intention.quantite, d)
            else:
                self._refuser(d, intention.motif)
        # La stratégie n'a rien proposé : position déjà ouverte (achat) ou déjà fermée (vente).
        for d in cotables.values():
            deja = "position déjà ouverte" if d.action == ActionDecision.ACHETER else "aucune position ouverte"
            self._refuser(d, f"sans objet ({deja})")

    @staticmethod
    def _achetable(valeur: Valeur) -> bool:
        return valeur.statut == StatutValeur.ACTIVE and not valeur.reference

    @staticmethod
    def _vues(ouvertes: dict[str, Position]) -> list[PositionVue]:
        return [
            PositionVue(ticker, pos.quantite, pos.prix_entree, pos.plus_haut)
            for ticker, pos in ouvertes.items()
        ]

    # -- valorisation ------------------------------------------------------------------------------

    def _cours(self, valeur: Valeur) -> tuple[Decimal, Decimal] | None:
        """(prix, taux EUR) : cotation du moment, sinon dernier cours et dernier taux connus."""
        cotation: Cotation | None = self.cotations.get(valeur.ticker)
        if cotation is not None:
            return cotation.prix, cotation.taux_eur
        bougie = (
            Bougie.objects.filter(valeur=valeur, debut__lte=self.maintenant).order_by("-debut").first()
        )
        if bougie is None:
            return None
        if valeur.devise == "EUR":
            return bougie.cloture, Decimal(1)
        taux = (
            TauxChange.objects.filter(devise=valeur.devise, instant__lte=self.maintenant)
            .order_by("-instant")
            .first()
        )
        return (bougie.cloture, taux.taux) if taux else None

    def _titres(self, positions) -> Decimal:
        total = Decimal(0)
        for pos in positions:
            cours = self._cours(pos.valeur) or (pos.prix_entree, pos.taux_entree)
            total += pos.quantite * cours[0] * cours[1]
        return total.quantize(CENTIME, ROUND_HALF_UP)

    def _valoriser(self):
        p = self.p
        titres = self._titres(p.positions.filter(fermee_le__isnull=True).select_related("valeur"))
        cours_indice = self._cours(p.indice)
        indice = p.indice_liquidites
        if cours_indice is not None:
            indice += (p.indice_quantite * cours_indice[0] * cours_indice[1]).quantize(CENTIME, ROUND_HALF_UP)
        Valorisation.objects.update_or_create(
            portefeuille=p, instant=self.maintenant,
            defaults={
                "liquidites": p.liquidites, "titres": titres,
                "total": p.liquidites + titres, "indice_total": indice,
            },
        )
