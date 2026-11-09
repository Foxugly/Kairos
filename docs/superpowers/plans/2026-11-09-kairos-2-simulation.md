# Kairos — plan 2 : signaux techniques, broker simulé, portefeuilles, backtest

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kairos tient deux portefeuilles fictifs de 10 000 € (« IA » et « Technique »), les fait vivre à chaque cycle de 5 minutes sur des signaux techniques, avec les frais d'Interactive Brokers et la TOB, les compare à un ETF MSCI World acheté et gardé, et sait rejouer ses règles sur plusieurs années de cours journaliers (backtest).

**Architecture:** code pur sans Django pour tout ce qui décide ou calcule (`analyse/` : indicateurs et signaux ; `courtage/frais.py` : frais ; `portefeuille/strategie.py` : décisions) — le même code sert au cycle et au backtest. Django autour : barèmes, portefeuilles, positions, ordres, décisions, valorisations, et deux nouvelles étapes du cycle.

**Tech Stack:** celle du plan 1 (Django 6.1, Python 3.14, yfinance). Pas de pandas dans le code de Kairos (yfinance l'utilise en interne seulement) : listes et `Decimal`.

**Spec:** `docs/superpowers/specs/2026-11-09-kairos-design.md`

## Global Constraints

- Tout en français ; dépôt public ; aucun appel réseau dans les tests (contexte du plan 1 inchangé).
- Montants en `Decimal` (jamais `float`) ; argent à 2 décimales (`ROUND_HALF_UP`), cours à 4.
- Portefeuille en **EUR** ; valeurs USD converties au dernier `TauxChange` USD.
- Règles par portefeuille (spec) : capital **10 000 €** ; **5 %** max par position ; **20** positions ouvertes max ; achat seulement ; **stop-loss −5 %** ; stop suiveur ; sortie sur signal de vente.
- Ordres **seulement en séance** de la place de la valeur.
- **Interactive Brokers (IBKR Pro)** = barème de départ ; **TOB** simulée ; aucun code ne se connecte à IBKR.
- Tous les gains et pertes affichés ou calculés sont **nets de frais** ; chaque ordre garde le détail de ses frais.
- Indice : **IWDA.AS** acheté une fois au départ avec les mêmes frais, puis gardé.
- Deux portefeuilles dès le départ : « IA » et « Technique » ; dans ce plan ils suivent les mêmes règles (l'IA arrive au plan 3).

## Décisions du plan (choix de Claude, à relire par Renaud)

- **Rythme des décisions :** les signaux d'entrée et de sortie se calculent **une fois par jour, sur les bougies journalières clôturées** ; ils s'exécutent au **premier cycle en séance du jour suivant**. Les **stops** (perte et suiveur) se surveillent **à chaque cycle** sur le dernier cours 5 min. Le backtest suit la même règle (signal à la clôture J → ordre à l'ouverture J+1 ; stops sur le plus bas du jour).
- **Signaux de la première version** (bougies 1d) : croisement des moyennes mobiles 20/50 jours ; RSI 14 (< 30 achat, > 70 vente) ; cassure du plus haut des 20 dernières séances (achat) / du plus bas (vente). Pas encore de figures complexes (tête‑épaules) : elles viendront si le backtest montre que les signaux simples ne suffisent pas.
- **Score :** chaque signal d'achat vaut +1, de vente −1 ; on achète si score ≥ 2 et aucun signal de vente ; on vend une position si score ≤ −1.
- **Stop suiveur :** actif dès que le cours a gagné 5 % depuis l'entrée ; il suit alors à 5 % sous le plus haut atteint.
- **Exécution simulée :** au dernier cours connu, avec un **glissement de 0,1 %** défavorable ; nombre d'actions **entier** (une valeur dont une action dépasse 5 % du portefeuille est ignorée).
- **Frais et gain attendu :** pas d'achat si les frais aller‑retour estimés dépassent **1 %** du montant (règle `frais_max_relatifs`, réglable).

## Review Focus

1. **Pas de cours récent ou pas de taux USD** (source en panne) → aucune décision sur la valeur concernée, raison au journal ; jamais d'ordre au cours d'avant‑hier. (Tasks 5, 6)
2. **Liquidités insuffisantes / 20 positions déjà ouvertes** → l'achat est refusé et la décision dit pourquoi ; jamais de liquidités négatives. (Task 5)
3. **Cycle relancé deux fois le même matin** → les ordres décidés à la clôture de la veille ne sont exécutés qu'une fois. (Task 6)
4. **Arrondis** : frais minimums, plafonds, TOB plafonnée, conversion USD → les totaux recalculés depuis les ordres égalent les liquidités affichées au centime. (Tasks 3, 6)
5. **Historique trop court** pour un indicateur (valeur récente, < 50 séances) → pas de signal, pas d'erreur. (Task 2)

---

### Task 1 : valeurs de référence et historique journalier

**Files:**
- Modify: `backend/marche/models.py` (champs), `backend/marche/donnees/univers.csv`, `backend/marche/management/commands/proposer_univers.py`, `backend/marche/releve.py`
- Create: `backend/marche/migrations/000X_reference_type_titre.py`, `backend/marche/management/commands/historique.py`
- Test: `backend/marche/tests/test_reference.py`, `test_historique.py`

**Interfaces:**
- Produces:
  - `Valeur.reference: bool` (défaut `False`) — valeur suivie pour comparaison, **jamais tradée, hors limite des 100** ; `Valeur.type_titre` (`TypeTitre` : `action`, `etf`, défaut `action`).
  - `Valeur.objects.a_relever()` : actives **ou** de référence.
  - `IWDA.AS` (iShares Core MSCI World, `XAMS`, `EUR`, `etf`, `reference=1`, sans alias) dans `univers.csv` (colonnes `reference`, `type_titre` ajoutées ; absentes = défauts).
  - `relever_cours` relève `a_relever()` au lieu de `actives()`.
  - Commande `manage.py historique [--jours 400] [--ticker T]` : bougies `1d` des N derniers jours pour `a_relever()` via la source de cours (`bougies(..., "1d", depuis)`), enregistrement idempotent (même upsert que `releve`), résumé `N bougies pour M valeurs, K en erreur`.

- [ ] **Step 1 : tests qui échouent** : `a_relever()` inclut une valeur de référence inactive et exclut une proposée ; l'action d'admin `activer` ne compte pas les valeurs de référence ; `proposer_univers` crée IWDA.AS avec `reference=True`, `type_titre="etf"` ; `historique` (source factice) enregistre les bougies, relancé ne crée pas de doublon, un ticker en erreur est compté et n'arrête pas les autres.
- [ ] **Step 2 :** Run — FAIL. **Step 3 :** implémenter (migration incluse). **Step 4 :** tests + ruff + `makemigrations --check` — PASS. Essai réel : `historique --jours 400` sur la base de dev → ~ 280 bougies par valeur.
- [ ] **Step 5 : Commit** — `"Valeurs de référence (IWDA.AS), type de titre et historique journalier"`.

### Task 2 : indicateurs et signaux (`analyse/`, code pur)

**Files:**
- Create: `backend/analyse/__init__.py`, `apps.py`, `indicateurs.py`, `signaux.py`
- Test: `backend/analyse/tests/test_indicateurs.py`, `test_signaux.py`

**Interfaces:**
- Produces:
  - `indicateurs.moyenne_mobile(cours: list[Decimal], n: int) -> Decimal | None` (None si < n points).
  - `indicateurs.rsi(cours: list[Decimal], n: int = 14) -> Decimal | None` (moyenne de Wilder ; None si < n+1 points ; 100 si aucune baisse).
  - `signaux.Signal` (dataclass gelée) : `code: str` (`"croisement_mm"`, `"rsi"`, `"cassure"`), `sens: Sens` (`ACHAT`/`VENTE`), `detail: str` (phrase française lisible, ex. « MM20 passe au‑dessus de MM50 »).
  - `signaux.BougieJour` (dataclass) : `jour: date, ouverture, haut, bas, cloture: Decimal`.
  - `signaux.signaux_du_jour(bougies: list[BougieJour]) -> list[Signal]` : sur la **dernière** bougie de la liste (triée par jour croissant) : croisement MM20/MM50 (la veille MM20 ≤ MM50 et ce jour MM20 > MM50 → ACHAT ; inverse → VENTE) ; RSI14 < 30 → ACHAT, > 70 → VENTE ; clôture > plus haut des 20 séances **précédentes** → ACHAT, < plus bas des 20 précédentes → VENTE.
  - `signaux.score(signaux: list[Signal]) -> int` (+1 / −1).

- [ ] **Step 1 : tests qui échouent** (séries construites dans le test) : MM sur 3 points ; RSI d'une série toujours haussière = 100, d'une série connue = valeur de référence calculée à la main (au centième) ; croisement détecté le jour exact et pas le lendemain ; cassure à la hausse et à la baisse ; 30 bougies → aucun croisement MM (pas d'erreur), RSI et cassure présents ; liste vide → `[]`.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS + ruff. **Step 5 : Commit** — `"Indicateurs et signaux techniques en code pur"`.

### Task 3 : barèmes de frais IBKR et TOB (`courtage/`)

**Files:**
- Create: `backend/courtage/{__init__,apps,models,admin,frais}.py`, `migrations/0001_initial.py`, `migrations/0002_bareme_ibkr.py` (données)
- Test: `backend/courtage/tests/test_frais.py`, `test_bareme.py`

**Interfaces:**
- Produces:
  - `Bareme` : `broker` (texte, `"ibkr"`), `nom`, `valide_depuis` (date), `change_pourcentage`, `change_minimum` (EUR), `glissement` (défaut 0,001), notes/source (URL et date du relevé).
  - `RegleCourtage` : `bareme` FK, `places` (texte, codes `Place` séparés par des virgules), `devise`, `par_action`, `pourcentage`, `minimum`, `maximum_pourcentage` (plafond en % du montant, optionnel), `maximum` (montant, optionnel).
  - `TauxTob` : `bareme` FK, `type_titre`, `taux`, `plafond` (EUR).
  - `Bareme.en_vigueur(broker: str, jour: date) -> Bareme` (le plus récent `valide_depuis <= jour`).
  - `frais.DetailFrais` (dataclass) : `courtage, change, tob, total` en EUR (`Decimal`, 2 décimales).
  - `frais.calculer_frais(bareme_donnees: BaremeDonnees, place: str, devise: str, type_titre: str, quantite: int, prix: Decimal, taux_eur: Decimal) -> DetailFrais` — **pur** : `BaremeDonnees` est une dataclass figée construite depuis le modèle (`Bareme.donnees()`), pour que le backtest et le cycle partagent le calcul. Courtage dans la devise de la règle puis converti ; change seulement si `devise != "EUR"` ; TOB sur le montant en EUR, plafonnée.
  - Migration de données : barème `ibkr` « IBKR Pro – fixe » **relevé sur le site d'Interactive Brokers au moment de la construction** (actions US ; places européennes de `Place`), change IBKR, et **TOB belge** (actions ; ETF capitalisant non enregistré en Belgique pour IWDA). URL et date du relevé dans `notes`. Si l'information « IBKR prélève ou non la TOB » est trouvée, la consigner dans `notes`.

- [ ] **Step 1 : tests qui échouent** (barème construit dans le test, valeurs **inventées** pour le test, pas celles d'IBKR) : ordre US de 10 actions à 100 USD → courtage par action vs minimum ; plafond en % appliqué ; ordre Euronext en pourcentage avec minimum ; change appliqué seulement en USD avec son minimum ; TOB plafonnée au‑delà d'un gros montant ; arrondis au centime (`ROUND_HALF_UP`) ; `en_vigueur` choisit le bon barème selon la date.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter (admin : barème avec règles et TOB en lignes). **Step 4 :** PASS + ruff + makemigrations. **Step 5 : Commit** — `"Barèmes de frais : courtage, change et TOB ; barème IBKR Pro"`.

### Task 4 : portefeuilles, positions, ordres, décisions

**Files:**
- Create: `backend/portefeuille/{__init__,apps,models,admin}.py`, `migrations/0001_initial.py`, `migrations/0002_portefeuilles_depart.py`
- Test: `backend/portefeuille/tests/test_modeles.py`

**Interfaces:**
- Produces:
  - `Portefeuille` : `nom` (unique), `broker` (`"simule"`), `bareme_broker` (`"ibkr"`), `capital_initial` (10000), `liquidites`, `part_max` (0.05), `positions_max` (20), `stop_perte` (0.05), `seuil_suiveur` (0.05), `ecart_suiveur` (0.05), `frais_max_relatifs` (0.01), `score_achat` (2), `utilise_ia` (bool), `budget_ia_mensuel` (EUR, défaut 40), `indice` (FK `Valeur`, IWDA.AS), `indice_quantite`, `indice_liquidites`, `demarre` (datetime, nullable), `actif`.
  - `Position` : `portefeuille`, `valeur`, `quantite`, `prix_entree` (devise de la valeur), `taux_entree`, `cout_entree_eur` (montant + frais), `plus_haut` (devise), `ouverte_le`, `fermee_le`, `prix_sortie`, `produit_sortie_eur` (montant − frais), `motif_sortie` ; `resultat_eur` (propriété : produit − coût, `None` si ouverte) ; contrainte : une seule position **ouverte** par (portefeuille, valeur).
  - `Ordre` : `portefeuille`, `position`, `sens` (`achat`/`vente`), `quantite`, `prix`, `taux_eur`, `montant_eur`, `courtage`, `change`, `tob`, `frais_total`, `instant`, `decision` (FK).
  - `Decision` : `portefeuille`, `valeur` (nullable), `instant`, `action` (`acheter`, `vendre`, `garder`, `refuser`), `motif` (texte lisible), `signaux` (JSON), `pour_le` (date d'exécution prévue), `executee` (datetime nullable).
  - `Valorisation` : `portefeuille`, `instant`, `liquidites`, `titres`, `total`, `indice_total` ; unique (portefeuille, instant).
  - Migration de données : portefeuilles « IA » (`utilise_ia=True`) et « Technique » (`utilise_ia=False`), `liquidites = capital_initial`, indice IWDA.AS (créé par la migration s'il n'existe pas encore, mêmes champs que le CSV).

- [ ] **Step 1 : tests qui échouent** : les deux portefeuilles existent après migration avec 10 000 € ; deux positions ouvertes sur la même valeur dans le même portefeuille → `IntegrityError` ; une ouverte + une fermée → accepté ; `resultat_eur` d'une position fermée.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter (admin en lecture pour ordres/décisions/valorisations ; portefeuille éditable pour ses règles). **Step 4 :** PASS + ruff + makemigrations. **Step 5 : Commit** — `"Portefeuilles IA et Technique, positions, ordres, décisions, valorisations"`.

### Task 5 : stratégie (code pur)

**Files:**
- Create: `backend/portefeuille/strategie.py`
- Test: `backend/portefeuille/tests/test_strategie.py`

**Interfaces:**
- Consumes: `Signal`, `score` (Task 2) ; `DetailFrais`, `calculer_frais`, `BaremeDonnees` (Task 3).
- Produces (dataclasses figées, aucun accès base) :
  - `Regles` : champs de règles du `Portefeuille` (part_max, positions_max, stop_perte, seuil_suiveur, ecart_suiveur, frais_max_relatifs, score_achat).
  - `PositionVue` : `ticker, quantite, prix_entree, plus_haut`.
  - `Marche` : `ticker -> (prix: Decimal, devise, place, type_titre, taux_eur: Decimal)` pour les valeurs **cotables maintenant** (prix récent et taux présents).
  - `Intention` : `ticker, action` (`acheter`/`vendre`/`refuser`), `quantite`, `motif`.
  - `stops(positions: list[PositionVue], marche: Marche, regles: Regles) -> list[Intention]` : vente si `prix <= prix_entree × (1 − stop_perte)` (motif « stop‑loss −5 % ») ; vente si le suiveur est actif (`plus_haut >= prix_entree × (1 + seuil_suiveur)`) et `prix <= plus_haut × (1 − ecart_suiveur)` (motif « stop suiveur »).
  - `decider(liquidites: Decimal, total: Decimal, positions: list[PositionVue], signaux: dict[str, list[Signal]], marche: Marche, regles: Regles, bareme: BaremeDonnees) -> list[Intention]` : d'abord les **ventes** (positions avec `score ≤ −1`), puis les **achats** : candidats `score ≥ score_achat` sans signal de vente, non détenus, triés par score décroissant puis ticker ; `quantite = floor(min(part_max × total, liquidites restantes) / (prix × taux × (1 + glissement)))` ; **refus** motivé si : 0 action possible, `positions_max` atteint, frais aller‑retour estimés `> frais_max_relatifs × montant`, ou valeur absente de `marche` (« pas de cours récent »). Les liquidités restantes tiennent compte des achats déjà retenus et de leurs frais : **jamais négatives**.

- [ ] **Step 1 : tests qui échouent** : stop‑loss à −5 % exactement → vente ; −4,9 % → rien ; suiveur : entrée 100, plus haut 110, prix 104 → vente, prix 105 → rien, plus haut 104 (suiveur inactif) et prix 99 → rien ; achat de 2 candidats quand il reste de quoi en payer un seul → un achat + un refus « liquidités insuffisantes » ; 20 positions ouvertes → refus « 20 positions déjà ouvertes » ; frais aller‑retour trop lourds → refus ; valeur sans cours → refus « pas de cours récent » ; une action plus chère que 5 % → refus ; ventes listées avant achats.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS + ruff. **Step 5 : Commit** — `"Stratégie : stops, ventes, achats sous contraintes de liquidités et de frais"`.

### Task 6 : broker simulé et exécution dans le cycle

**Files:**
- Create: `backend/courtage/broker.py`, `backend/portefeuille/execution.py`, `backend/portefeuille/marche_actuel.py`
- Modify: `backend/cycle/deroulement.py` (`ETAPES`)
- Test: `backend/courtage/tests/test_broker.py`, `backend/portefeuille/tests/test_execution.py`, `backend/cycle/tests/test_etapes_plan2.py`

**Interfaces:**
- Consumes: Tasks 2–5 ; `Bougie`, `TauxChange`, `en_seance`.
- Produces:
  - `courtage.broker.Broker` (`Protocol`) : `code: str` ; `estimer(ordre: OrdreDemande) -> DetailFrais` ; `executer(ordre: OrdreDemande) -> Execution` (prix appliqué avec glissement, frais, montant EUR). `BrokerSimule` (code `"simule"`, barème `Bareme.en_vigueur(portefeuille.bareme_broker, jour)`) ; registre `courtage.broker.broker(code) -> Broker`.
  - `marche_actuel.marche(maintenant) -> Marche` : pour chaque valeur `a_relever()` dont la place est en séance, dernière bougie 5m **de moins de 30 minutes** et taux USD de moins de 24 h (EUR : 1) ; sinon absente.
  - `execution.decider_du_jour(maintenant) -> dict` : une fois par jour et par portefeuille, après la clôture de toutes les places européennes **et** US (≥ 22:30 UTC, dernière bougie 1d du jour présente), calcule les signaux de chaque valeur active sur les 120 dernières bougies 1d et enregistre des `Decision` (`pour_le` = prochain jour ouvré) ; idempotent (pas de nouvelle décision si celles du jour existent).
  - `execution.executer(maintenant) -> dict` : pour chaque portefeuille actif : (1) si `demarre` est vide et qu'IWDA.AS est cotable, achète l'indice (quantité entière, mêmes frais), pose `demarre` ; (2) **stops** sur les positions ouvertes ; (3) décisions du jour non exécutées dont la valeur est cotable → `decider` de la stratégie avec ces signaux → ordres via le broker ; chaque `Decision` exécutée reçoit `executee` (**exécutée une seule fois**, sous `select_for_update` du portefeuille) ; met à jour `plus_haut` des positions ; (4) enregistre une `Valorisation` (liquidités + titres au dernier cours + indice).
  - `ETAPES` complété : `("decisions", decider_du_jour)`, `("execution", executer)` après la collecte.

- [ ] **Step 1 : tests qui échouent** :
  - broker : prix avec glissement défavorable (achat +0,1 %, vente −0,1 %) ; frais issus du barème en vigueur.
  - marché : bougie 5m de 40 min → valeur absente ; taux USD absent → valeurs USD absentes.
  - exécution : premier passage achète l'indice et pose `demarre` ; décision d'achat exécutée une seule fois sur deux passages ; stop‑loss déclenché par une bougie 5m → position fermée, motif, `produit_sortie_eur` net de frais ; **réconciliation** : `capital_initial − Σ coûts d'achat + Σ produits de vente − coût indice == liquidites + indice_liquidites` au centime après une séquence achat/vente/frais USD ; valorisation enregistrée ; valeur sans cours → décision non exécutée, gardée pour le passage suivant du même jour, abandonnée (`action = refuser`, motif) le jour suivant.
  - cycle : `ETAPES` contient les nouvelles étapes dans l'ordre ; une erreur dans `executer` n'empêche pas l'enregistrement du journal (comportement du plan 1).
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS + suite + ruff + makemigrations. **Step 5 : Commit** — `"Broker simulé et exécution des décisions à chaque cycle"`.

### Task 7 : backtest

**Files:**
- Create: `backend/portefeuille/backtest.py`, `backend/portefeuille/management/commands/backtest.py`, migration `ResultatBacktest`
- Test: `backend/portefeuille/tests/test_backtest.py`

**Interfaces:**
- Consumes: `signaux_du_jour`, `stops`, `decider`, `calculer_frais` (mêmes fonctions que le cycle — aucune logique dupliquée).
- Produces:
  - `backtest.rejouer(series: dict[str, list[BougieJour]], meta: dict[str, (devise, place, type_titre)], taux_usd: dict[date, Decimal], regles: Regles, bareme: BaremeDonnees, capital: Decimal, indice: str) -> Rapport` — **pur** : chaque jour J, stops sur le **plus bas** de J (exécution au prix du stop, ou à l'ouverture si elle est déjà en dessous), puis les décisions issues de la clôture J−1 exécutées à l'**ouverture** de J ; indice acheté à l'ouverture du premier jour.
  - `Rapport` : `debut, fin, valeur_finale, performance, performance_indice, ecart, nb_positions, taux_gagnantes, frais_total, tob_total, perte_max` (plus forte baisse depuis un sommet), `courbe: list[(date, total, indice_total)]`.
  - `ResultatBacktest` (modèle) : paramètres (règles, période, barème), champs du rapport, `courbe` (JSON), `cree`.
  - Commande `manage.py backtest [--depuis AAAA-MM-JJ] [--portefeuille Technique]` : lit les bougies 1d en base (via `historique` au préalable), lance `rejouer`, enregistre et affiche le rapport en français.
- [ ] **Step 1 : tests qui échouent** (séries artificielles) : une valeur qui monte régulièrement puis casse → achat puis sortie par stop suiveur au bon jour ; gap de baisse sous le stop → exécution à l'ouverture ; l'ordre d'un signal de J est exécuté à l'ouverture de J+1, jamais à la clôture de J ; aucun signal → performance = 0 hors indice ; frais et TOB totaux égaux à la somme des ordres ; `perte_max` d'une courbe connue.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS + suite + ruff + makemigrations.
- [ ] **Step 5 :** essai réel : `historique --jours 1900` (≈ 5 ans) sur les valeurs actives + IWDA.AS, puis `backtest --depuis <il y a 5 ans>` ; consigner le rapport (chiffres) dans le rapport de tâche.
- [ ] **Step 6 :** mettre à jour `CLAUDE.md` (apps `analyse`, `courtage`, `portefeuille`, commandes `historique`, `backtest`, étapes du cycle, choix de stratégie listés plus haut).
- [ ] **Step 7 : Commit** — `"Backtest des règles techniques sur l'historique journalier"`.

### Task 8 : PR (avec accord explicite pour la fusion)

- [ ] Pousser la branche `plan-2-simulation`, ouvrir la PR, CI verte ; **la fusion se fait avec l'accord de Renaud**.
