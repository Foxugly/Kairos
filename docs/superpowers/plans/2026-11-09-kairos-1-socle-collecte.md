# Kairos — plan 1 : socle et collecte

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** un backend Django Kairos, sur le modèle de FoxHouse, qui connaît l'univers de valeurs et, à chaque lancement de la commande `cycle`, relève les nouvelles des flux RSS et les cours des valeurs en séance, sans qu'une source en panne arrête le reste.

**Architecture:** dépôt `Kairos/` (git, `backend/` seulement dans ce plan). Apps : `marche` (valeurs, bougies, taux de change, horaires de séance), `sources` (interfaces interchangeables `SourceCours` / lecture RSS, flux et nouvelles), `cycle` (la commande et son journal, extensible par les plans suivants). `config/` et `accounts/` repris de FoxHouse.

**Tech Stack:** Python 3.14, Django 6.1, PostgreSQL 16 (prod/CI) / SQLite (dev), `yfinance`, `feedparser`, `requests`, ruff.

**Spec:** `docs/superpowers/specs/2026-11-09-kairos-design.md`

**Suite :** plan 2 (signaux techniques, broker simulé, barème de frais, portefeuilles, backtest), plan 3 (IA), plan 4 (frontend), plan 5 (mise en production : SSM, unités, timer 5 min, nginx, Sentry, UptimeRobot).

## Global Constraints

- Modèle de la flotte : reprendre `D:\Projects\PycharmProjects\FoxHouse\backend` (réglages sûrs par défaut, `/health/`, Sentry, utilisateur `accounts.User` e‑mail seul) — référence, pas d'invention.
- Code, commentaires, messages, noms de modèles et de fonctions **en français** (comme FoxHouse).
- Dépôt **public** : aucun secret, aucune clé, aucune donnée personnelle dans un fichier suivi.
- Univers : **100 valeurs actives au plus** (`UNIVERS_MAX = 100`). Noyau imposé : `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `META`, `NVDA`, `TTE.PA`, `TSLA`.
- Cycle : **toutes les 5 minutes** ; une erreur d'une source n'arrête pas le cycle (journalisée + Sentry).
- Tous les instants en UTC en base (`USE_TZ = True`), `TIME_ZONE = "Europe/Brussels"`.
- ruff à la version de la flotte (celle de FoxHouse `requirements-dev.txt`).

## Review Focus

1. **yfinance rend un tableau vide, des `NaN`, ou lève** (ticker radié, limite de débit) → la valeur est sautée, les autres sont enregistrées, l'erreur est dans le journal du cycle. (Task 4)
2. **Un flux RSS en panne ou mal formé** (timeout, HTML au lieu de XML) → les autres flux sont lus ; `FluxRss.derniere_erreur` est rempli. (Task 5)
3. **La même nouvelle dans deux flux** (URL différentes, même titre à la casse/espaces près) → une seule `Nouvelle`. (Task 5)
4. **Changement d'heure décalé** entre New York et Bruxelles (mars, fin octobre) → `en_seance` suit l'heure locale de chaque place. (Task 2)
5. **Cycle planté resté « en cours »** → le cycle suivant ne reste pas bloqué indéfiniment (au‑delà de 10 minutes, il est déclaré abandonné). (Task 6)

---

### Task 1 : dépôt et socle Django

**Files:**
- Create: `Kairos/.gitignore`, `Kairos/.gitattributes`, `Kairos/CLAUDE.md`, `Kairos/README.md`
- Create: `Kairos/backend/manage.py`, `backend/config/{__init__,settings,urls,wsgi,sante,sentry_filtres,tests}.py`, `backend/accounts/` (copie), `backend/ruff.toml`, `backend/requirements.txt`, `backend/requirements-dev.txt`
- Create: `Kairos/.github/workflows/ci.yml` (jobs backend seulement : tests PostgreSQL, ruff, pip-audit), `codeql.yml` (Python), `dependabot-automerge.yml`, `Kairos/.github/dependabot.yml`

**Interfaces:**
- Produces: projet Django `config`, `settings.UNIVERS_MAX = 100`, `settings.VERSION` lu de `KAIROS_VERSION`, `/health/`.

- [ ] **Step 1 :** `git init` dans `D:\Projects\PycharmProjects\Kairos` (branche `main`). Copier depuis FoxHouse `.gitignore`, `.gitattributes`, `backend/config/`, `backend/accounts/` (avec ses migrations), `ruff.toml`, `requirements-dev.txt`, les workflows et `dependabot.yml`. Remplacer `foxhouse`/`FoxHouse` par `kairos`/`Kairos` partout ; retirer de `INSTALLED_APPS`, `urls.py`, `CSRF_FAILURE_VIEW` et des réglages tout ce qui concerne les jeux et les parties (`tapis`, `parties`, jeux, `RETENTION_PARTIES_JOURS`, `SESSION_SAVE_EVERY_REQUEST`) ; garder la sécurité, la base, Sentry, CSP, `/health/`. Retirer du `ci.yml` le job frontend (il revient au plan 4) et des workflows tout ce qui pointe vers `frontend/`.
- [ ] **Step 2 :** `requirements.txt` = celui de FoxHouse + `yfinance`, `feedparser`, `requests` (bornes `>=x,<x+1` comme les autres lignes, versions courantes). Créer `backend/.venv` (Python 3.14) et installer `requirements.txt` + `requirements-dev.txt`.
- [ ] **Step 3 :** reprendre les tests de `config/tests.py` de FoxHouse (réglages sûrs, `/health/` 200 et 503) en les adaptant ; ajouter `test_univers_max` : `settings.UNIVERS_MAX == 100`.
- [ ] **Step 4 :** Run `$env:DJANGO_DEBUG="True"; .\.venv\Scripts\python.exe manage.py test` puis `.\.venv\Scripts\python.exe -m ruff check .` et `manage.py makemigrations --check --dry-run` — Expected : tout vert, aucune migration manquante.
- [ ] **Step 5 :** écrire `CLAUDE.md` (sur le modèle de celui de FoxHouse : rôle, commandes, architecture, lien vers la conception) et un `README.md` court.
- [ ] **Step 6 : Commit** — `git add -A && git commit -m "Socle Django de Kairos, repris de FoxHouse"` (inclut `docs/`).

### Task 2 : valeurs et horaires de séance (`marche`)

**Files:**
- Create: `backend/marche/{__init__,apps,models,admin,seances}.py`, `backend/marche/migrations/0001_initial.py`
- Test: `backend/marche/tests/test_seances.py`, `backend/marche/tests/test_modeles.py`

**Interfaces:**
- Produces:
  - `Place` (`TextChoices`) : `NASDAQ`, `NYSE`, `XPAR` (Paris), `XAMS` (Amsterdam), `XBRU` (Bruxelles), `XETR` (Francfort), `XMIL` (Milan), `XMAD` (Madrid), `XHEL` (Helsinki), `XDUB` (Dublin).
  - `Valeur` : `ticker` (unique, format Yahoo : `TTE.PA`), `nom`, `place`, `devise` (`"USD"`/`"EUR"`), `alias` (texte, noms séparés par des virgules, pour reconnaître la valeur dans une nouvelle), `statut` (`StatutValeur` : `proposee`, `active`, `inactive`), `imposee` (bool).
  - `Bougie` : `valeur` (FK), `intervalle` (`"5m"`/`"1d"`), `debut` (datetime UTC), `ouverture`, `haut`, `bas`, `cloture` (`DecimalField(max_digits=14, decimal_places=4)`), `volume` (`BigIntegerField`) ; contrainte unique `(valeur, intervalle, debut)`.
  - `TauxChange` : `devise`, `instant`, `taux` (`Decimal`, EUR pour 1 unité de la devise) ; unique `(devise, instant)`.
  - `seances.en_seance(place: str, instant: datetime) -> bool` et `seances.FUSEAU_PLACE: dict[str, str]`.
  - `Valeur.actives()` (manager/queryset) et l'action d'admin `activer` qui refuse de dépasser `settings.UNIVERS_MAX` (message d'erreur, rien n'est activé).

Horaires (heure locale, lundi–vendredi, jours fériés **non gérés** dans ce plan : un jour férié ne produit simplement pas de bougie) : `NASDAQ`/`NYSE` 09:30–16:00 `America/New_York` ; places européennes 09:00–17:30 dans leur fuseau (`Europe/Paris`, `Europe/Amsterdam`, `Europe/Brussels`, `Europe/Berlin`, `Europe/Rome`, `Europe/Madrid`, `Europe/Helsinki` 10:00–18:30, `Europe/Dublin` 08:00–16:30). Utiliser `zoneinfo`.

- [ ] **Step 1 : tests qui échouent** (`test_seances.py`) :
  - `en_seance("NASDAQ", 2026-11-09 15:00 UTC)` → `True` (10:00 à New York) ; `… 21:30 UTC` → `False`.
  - `en_seance("XPAR", 2026-11-09 08:30 UTC)` → `True` ; `2026-11-08` (dimanche) 12:00 UTC → `False`.
  - Décalage d'heure : `en_seance("NYSE", 2026-03-09 13:45 UTC)` → `True` (New York déjà à l'heure d'été, 09:45) ; `en_seance("XPAR", 2026-03-09 16:45 UTC)` → `False` (17:45 à Paris, encore à l'heure d'hiver).
  - Bornes : ouverture incluse, fermeture exclue.
- [ ] **Step 2 : tests qui échouent** (`test_modeles.py`) : unicité `(valeur, intervalle, debut)` ; action `activer` sur 3 valeurs alors que 99 sont actives → aucune activée, message d'erreur ; sur 1 → activée.
- [ ] **Step 3 :** Run `manage.py test marche` — Expected : FAIL (module absent).
- [ ] **Step 4 :** implémenter modèles, admin (listes filtrables par statut/place, recherche ticker/nom), `seances.py`, migration.
- [ ] **Step 5 :** Run `manage.py test marche` + ruff — Expected : PASS.
- [ ] **Step 6 : Commit** — `"Valeurs, bougies, taux de change et horaires de séance"`.

### Task 3 : proposition de l'univers

**Files:**
- Create: `backend/marche/donnees/univers.csv`, `backend/marche/management/commands/proposer_univers.py`
- Test: `backend/marche/tests/test_proposer_univers.py`

**Interfaces:**
- Consumes: `Valeur`, `StatutValeur`, `Place`.
- Produces: commande `manage.py proposer_univers [--fichier CHEMIN]`.

CSV (UTF‑8, en‑tête) : `ticker,nom,place,devise,alias,imposee`. Contenu : les 8 valeurs imposées (`imposee=1`) + les composants actuels du **S&P 100** et de l'**Euro Stoxx 50** au format Yahoo (relevés sur une source publique au moment de la construction ; noter la date en commentaire dans `CLAUDE.md`), sans doublons. Les `alias` sont les noms usuels, sensibles à la casse (`Apple`, `Nvidia,NVIDIA`, `TotalEnergies`, `Tesla`) — jamais un mot courant comme alias (pas « Total » pour TotalEnergies). « Meta » est accepté : la recherche est sensible à la casse et en mot entier, donc « metadata » ou « meta » ne correspondent pas.

- [ ] **Step 1 : tests qui échouent** :
  - sur une base vide, la commande crée toutes les lignes ; les 8 imposées sont `active` et `imposee=True`, les autres `proposee` ;
  - relancée, elle ne change **pas** le statut d'une valeur existante (une valeur passée `inactive` le reste) et met à jour `nom`/`alias` ;
  - une ligne avec une `place` inconnue fait échouer la commande avec le numéro de ligne, sans rien écrire (transaction).
- [ ] **Step 2 :** Run — Expected : FAIL.
- [ ] **Step 3 :** implémenter la commande et remplir `univers.csv`.
- [ ] **Step 4 :** Run tests + ruff — Expected : PASS. Run `manage.py proposer_univers` sur la base de dev — Expected : affiche `N valeurs créées, 0 mises à jour`, N entre 140 et 160.
- [ ] **Step 5 : Commit** — `"Proposition de l'univers : valeurs imposées, S&P 100 et Euro Stoxx 50"`.

### Task 4 : source de cours interchangeable

**Files:**
- Create: `backend/sources/{__init__,apps,cours,registre}.py`, `backend/sources/yahoo.py`, `backend/marche/releve.py`
- Test: `backend/sources/tests/test_yahoo.py`, `backend/marche/tests/test_releve.py`

**Interfaces:**
- Produces:
  - `sources.cours.BougieBrute` (dataclass gelée) : `debut: datetime` (UTC), `ouverture, haut, bas, cloture: Decimal`, `volume: int`.
  - `sources.cours.SourceCours` (`Protocol`) : `code: str` ; `bougies(tickers: list[str], intervalle: str, depuis: datetime) -> dict[str, list[BougieBrute]]` (un ticker en échec est absent du résultat ; la raison est dans l'attribut `erreurs: dict[str, str]` de l'instance, remis à zéro à chaque appel ; la méthode ne lève jamais) ; `taux_eur(devise: str) -> Decimal`.
  - `sources.registre.source_cours(code: str | None = None) -> SourceCours` ; `settings.SOURCE_COURS = "yahoo"`.
  - `sources.yahoo.SourceYahoo` (code `"yahoo"`) : `yfinance.download(..., group_by="ticker", interval=..., start=..., progress=False, auto_adjust=False)` ; lignes avec `NaN` écartées ; taux via le ticker `EURUSD=X` (`taux_eur("USD") = 1 / dernier cours`), `taux_eur("EUR") = Decimal(1)`.
  - `marche.releve.relever_cours(maintenant: datetime, source: SourceCours | None = None) -> dict` : pour les valeurs **actives** dont la place est en séance (ou fermée depuis moins de 30 min, pour la dernière bougie), bougies `5m` depuis la dernière enregistrée (ou 2 jours) ; une fois par jour après la fermeture, bougies `1d` des 30 derniers jours ; enregistrement idempotent (`bulk_create(..., update_conflicts=True)` sur la contrainte unique) ; enregistre le taux USD. Rend `{"bougies": int, "valeurs": int, "erreurs": {ticker: message}}`.

- [ ] **Step 1 : tests qui échouent** (`test_yahoo.py`, `yfinance.download` remplacé par un `DataFrame` construit dans le test — **aucun appel réseau dans les tests**) : 2 tickers dont un avec une ligne `NaN` → la ligne est écartée ; un ticker absent du `DataFrame` → absent du résultat et présent dans `erreurs` ; `download` qui lève → résultat vide, `erreurs` rempli pour tous, pas d'exception.
- [ ] **Step 2 : tests qui échouent** (`test_releve.py`, source factice) : seules les valeurs actives en séance sont demandées (une valeur US à 08:00 UTC ne l'est pas) ; relancer avec les mêmes bougies ne crée pas de doublon ; une erreur sur un ticker laisse les autres enregistrés et apparaît dans `erreurs`.
- [ ] **Step 3 :** Run — Expected : FAIL.
- [ ] **Step 4 :** implémenter.
- [ ] **Step 5 :** Run tests + ruff — Expected : PASS. Essai réel manuel (réseau) : `manage.py shell -c "from sources.yahoo import SourceYahoo; …"` sur `AAPL`, `TTE.PA` → des bougies récentes.
- [ ] **Step 6 : Commit** — `"Source de cours interchangeable, Yahoo d'abord"`.

### Task 5 : flux RSS et nouvelles

**Files:**
- Create: `backend/sources/{models,admin,rss,rattachement}.py`, `backend/sources/migrations/0001_initial.py`, `backend/sources/fixtures/flux_depart.json`
- Test: `backend/sources/tests/test_rss.py`, `test_rattachement.py`, `test_releve_nouvelles.py`

**Interfaces:**
- Consumes: `Valeur`.
- Produces:
  - `FluxRss` : `nom`, `url` (unique), `langue` (`fr`/`en`), `actif`, `dernier_releve`, `derniere_erreur` (texte, vide si OK).
  - `Nouvelle` : `url` (unique, max 1000), `empreinte` (unique, `sha256` du titre normalisé : minuscules, espaces compactés, ponctuation retirée), `titre`, `resume` (texte nettoyé de son HTML), `publiee` (datetime UTC), `flux` (FK), `valeurs` (M2M `Valeur`), `recue` (auto).
  - `sources.rss.NouvelleBrute` (dataclass) : `url, titre, resume, publiee`.
  - `sources.rss.lire_flux(contenu: bytes) -> list[NouvelleBrute]` (feedparser ; entrée sans date → date de réception ; contenu illisible → `FluxIllisible`).
  - `sources.rss.telecharger(url: str) -> bytes` (`requests`, timeout 15 s, `User-Agent: Kairos/1.0 (+https://kairos.foxugly.com)`, lève sur statut ≠ 200).
  - `sources.rattachement.valeurs_citees(texte: str, valeurs: Iterable[Valeur]) -> set[Valeur]` : correspondance **sensible à la casse et en mot entier** sur chaque alias et sur `$TICKER` / `(TICKER)` / `NASDAQ: TICKER`.
  - `sources.rss.relever_nouvelles(maintenant: datetime, telecharger=telecharger) -> dict` : lit chaque flux actif ; dédoublonne par `url` puis `empreinte` ; rattache aux valeurs actives (titre + résumé) ; met à jour `dernier_releve`/`derniere_erreur`. Rend `{"nouvelles": int, "flux_en_erreur": {nom: message}}`.

Flux de départ (fixture, modifiables en admin) : une dizaine de flux économiques publics, FR et EN (rubriques marchés/entreprises), à choisir et vérifier (réponse 200 et XML valide) au moment de la construction.

- [ ] **Step 1 : tests qui échouent** (XML d'exemple dans les tests, aucun réseau) :
  - `lire_flux` sur un RSS 2.0 et un Atom → titres, URL, dates UTC ; résumé sans balises HTML ; contenu HTML quelconque → `FluxIllisible`.
  - `valeurs_citees("Apple bat les attentes", …)` → {AAPL} ; `"pineapple"` → ∅ ; `"metadata"` → ∅ ; `"$NVDA grimpe"` → {NVDA} ; `"TotalEnergies relève…"` → {TTE.PA}.
  - `relever_nouvelles` : deux flux portant la même nouvelle (URL différentes, titre identique à la casse et aux espaces près) → **une** `Nouvelle` ; un flux dont `telecharger` lève → les autres sont lus, `derniere_erreur` rempli, `dernier_releve` inchangé pour lui ; relancer → aucun doublon.
- [ ] **Step 2 :** Run — Expected : FAIL.
- [ ] **Step 3 :** implémenter (modèles, admin avec liste des nouvelles filtrable par valeur et par flux, migration, fixture).
- [ ] **Step 4 :** Run tests + ruff + `makemigrations --check` — Expected : PASS.
- [ ] **Step 5 : Commit** — `"Flux RSS, nouvelles dédoublonnées et rattachées aux valeurs"`.

### Task 6 : la commande `cycle` et son journal

**Files:**
- Create: `backend/cycle/{__init__,apps,models,admin,deroulement}.py`, `backend/cycle/management/commands/cycle.py`, `backend/cycle/migrations/0001_initial.py`
- Test: `backend/cycle/tests/test_cycle.py`

**Interfaces:**
- Consumes: `relever_nouvelles`, `relever_cours`.
- Produces:
  - `Cycle` : `debut`, `fin` (nullable), `statut` (`en_cours`, `termine`, `en_erreur`, `abandonne`), `journal` (`JSONField`, `{nom_etape: résultat ou {"erreur": message}}`).
  - `cycle.deroulement.ETAPES: list[tuple[str, Callable[[datetime], dict]]]` — dans ce plan `[("nouvelles", relever_nouvelles), ("cours", relever_cours)]` ; **les plans 2 et 3 y ajoutent leurs étapes**.
  - `cycle.deroulement.lancer(maintenant: datetime | None = None) -> Cycle | None` : rend `None` sans rien faire si un cycle `en_cours` a commencé il y a moins de `DUREE_MAX_CYCLE = timedelta(minutes=10)` ; sinon marque les cycles `en_cours` plus anciens `abandonne`, crée le cycle (le contrôle et la création sous `transaction.atomic()` + `select_for_update()` sur les cycles en cours), exécute chaque étape dans l'ordre ; une étape qui lève est notée `{"erreur": …}` dans le journal, envoyée à Sentry (`sentry_sdk.capture_exception`) et **n'empêche pas les suivantes** ; statut final `termine` si aucune étape n'a levé, sinon `en_erreur`.
  - Commande `manage.py cycle` : appelle `lancer()`, écrit une ligne de résumé, code de sortie 0 même si une étape a échoué (le timer ne doit pas s'arrêter).
  - Purge : `lancer` supprime les `Cycle` de plus de 30 jours.

- [ ] **Step 1 : tests qui échouent** (étapes factices injectées par `mock.patch` de `ETAPES`) :
  - les étapes s'exécutent dans l'ordre et leurs résultats sont au journal, statut `termine` ;
  - la 1re étape lève → la 2e s'exécute quand même, statut `en_erreur`, message au journal ;
  - un cycle `en_cours` démarré il y a 3 min → `lancer()` rend `None`, aucune étape exécutée ;
  - un cycle `en_cours` démarré il y a 11 min → il passe `abandonne` et un nouveau cycle tourne ;
  - un cycle de 31 jours est supprimé.
- [ ] **Step 2 :** Run — Expected : FAIL.
- [ ] **Step 3 :** implémenter (admin en lecture seule : liste des cycles, journal lisible).
- [ ] **Step 4 :** Run toute la suite + ruff + `makemigrations --check` — Expected : PASS.
- [ ] **Step 5 :** essai réel : `proposer_univers`, `loaddata flux_depart`, `manage.py cycle` deux fois de suite à 1 minute d'intervalle pendant une séance — Expected : des nouvelles et des bougies en base, journal sans erreur ou avec des erreurs explicites ; aucun doublon au second passage.
- [ ] **Step 6 :** mettre à jour `CLAUDE.md` (apps, commandes `proposer_univers`, `cycle`, date du relevé des indices).
- [ ] **Step 7 : Commit** — `"Commande cycle : collecte toutes les 5 minutes, verrou et journal"`.

### Task 7 : publication sur GitHub (avec accord explicite)

- [ ] **Step 1 :** **demander l'accord de Renaud**, puis créer le dépôt public `Foxugly/Kairos` (`gh repo create Foxugly/Kairos --public --source . --push`).
- [ ] **Step 2 :** vérifier que la CI est verte (`gh run list`, `gh run view`) ; activer les alertes et correctifs Dependabot (`gh api -X PUT repos/Foxugly/Kairos/vulnerability-alerts`, puis `.../automated-security-fixes`).
- [ ] **Step 3 :** protection de `main` (jobs CI requis, admins exemptés) et auto-merge comme FoxHouse ; le secret Dependabot `DEPENDABOT_AUTOMERGE_TOKEN` est posé **par Renaud** dans l'interface GitHub.
- [ ] **Step 4 :** mettre à jour `~/.claude/CLAUDE.md` et `D:\Projects\CLAUDE.md` (Kairos : dépôt, non encore en prod).
