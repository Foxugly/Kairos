# CLAUDE.md

Kairos : outil de trading simulé de la flotte Foxugly (cours de bourse et flux publics, aucun ordre réel).
Django (API JSON) dans `backend/`, frontend Angular à venir (plan 4). Conception :
`docs/superpowers/specs/2026-11-09-kairos-design.md` ; plans dans `docs/superpowers/plans/`.
Référence de la flotte : `D:\Projects\PycharmProjects\FoxHouse` (le socle en est repris). Code, commentaires
et messages de commit en français. Dépôt public : aucun secret, aucune donnée personnelle.

## Commandes backend (depuis `backend/`, PowerShell, `$env:DJANGO_DEBUG="True"`)

- Venv : `py -3.14 -m venv .venv` puis `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt`
- Tests : `.\.venv\Scripts\python.exe manage.py test` (aucun appel réseau : mocks ou données construites)
- Lint : `.\.venv\Scripts\python.exe -m ruff check .`
- Migrations oubliées : `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
- Santé : `GET /health/` → 200 ou 503

## Architecture (`backend/`)

- `config/` — réglages (sûrs par défaut : sans `DJANGO_DEBUG=True`, `SECRET_KEY`, `ALLOWED_HOSTS` et
  PostgreSQL sont exigés), `sante.py` (`/health/`), `sentry_filtres.py` (rien de personnel vers Sentry,
  projet `kairos-backend`), `urls.py`.
- `accounts/` — utilisateur de la flotte (e-mail seul), administrateurs seulement.
- `settings.UNIVERS_MAX` (100) : taille maximale de l'univers de titres suivi. `settings.VERSION` vient de
  `KAIROS_VERSION`.

- `marche/` — `Valeur`, `Bougie`, `TauxChange`, séances. `manage.py proposer_univers [--fichier]` charge
  `marche/donnees/univers.csv` (8 valeurs imposées + S&P 100 + Euro Stoxx 50, tickers Yahoo, sans GOOG) ; relancée,
  elle met à jour nom/alias mais ne touche jamais au statut. Relevé des indices : 2026-11-09 (Wikipedia, composition
  au 2026-09-21) ; `BK` = BNY. À rafraîchir à la main lors des révisions trimestrielles.
  `Valeur.reference` : valeur suivie pour comparaison (IWDA.AS), jamais tradée, hors limite de l'univers ;
  `Valeur.objects.a_relever()` = actives + références. `Valeur.type_titre` (`action`/`etf`, pour la TOB).
  Bougie `1d` : `debut` = minuit UTC de la date locale de la séance. `manage.py historique [--jours 400] [--ticker T]`
  charge les bougies 1d de `a_relever()` (idempotent) et, si une valeur est en USD, le taux USD de clôture de
  chaque jour (`TauxChange` à minuit UTC, via `SourceCours.taux_journaliers`).

- `sources/` — `FluxRss`, `Nouvelle` (dédoublonnées, rattachées aux valeurs), client Yahoo des cours, registre
  des sources. Flux de départ : `manage.py loaddata flux_depart`.
- `analyse/` — code pur (Decimal, aucun accès base) : `indicateurs` (moyenne mobile, RSI de Wilder),
  `signaux.signaux_du_jour(bougies)` (croisement MM20/MM50, RSI14 < 30 / > 70, cassure des 20 séances) et `score`.
- `courtage/` — `Bareme` (+ `RegleCourtage` par place, `TauxTob` par type de titre), daté par `valide_depuis` ;
  `Bareme.en_vigueur(broker, jour).donnees()` → `BaremeDonnees` figé. `frais.calculer_frais` (courtage, change,
  TOB, en EUR, arrondis au centime). `broker` : interface `Broker`, `BrokerSimule` et `execution_simulee`
  (glissement défavorable du barème, partagée avec le backtest). Barème IBKR Pro semé par migration.
- `portefeuille/` — `Portefeuille` (règles : part max, positions max, stops, frais max, score d'achat ; indice de
  comparaison), `Position`, `Decision`, `Ordre`, `Valorisation`, `ResultatBacktest`. Une migration de données
  sème IWDA.AS et les portefeuilles « IA » et « Technique » (10 000 €, indice IWDA.AS). `strategie` (code pur,
  partagé cycle/backtest) : `Regles.depuis(p)`, `stops`, `decider`. `execution` : étapes « decisions » (une fois
  par jour après 22:30 UTC, signaux sur les 120 dernières bougies 1d → `Decision` pour le jour ouvré suivant) et
  « execution » (achat de l'indice au démarrage, stops à chaque cycle sur le dernier cours 5 min, décisions du
  jour au premier cycle où la valeur est cotable, sinon abandonnées ; revalorisation).
  `manage.py backtest [--depuis AAAA-MM-JJ] [--portefeuille Technique]` : rejoue (`backtest.rejouer`, pur) les
  règles sur les bougies 1d en base (lancer `historique --jours 1900` avant pour 5 ans), enregistre un
  `ResultatBacktest` et affiche le rapport. Signal à la clôture J → ordre à l'ouverture de la séance suivante de
  la valeur ; stops sur le plus bas du jour (sortie au stop, ou à l'ouverture en cas de gap) ; taux USD du jour
  ou du dernier jour connu. Il applique le barème en vigueur **aujourd'hui** à toute la période.
- Choix de stratégie (plan 2, à relire) : signaux une fois par jour sur bougies 1d clôturées, exécutés le jour
  suivant ; score +1 par signal d'achat, −1 par vente ; achat si score ≥ 2 et aucun signal de vente, vente si
  score ≤ −1 ; stop-loss −5 %, stop suiveur armé à +5 % et placé 5 % sous le plus haut ; exécution simulée avec
  0,1 % de glissement, quantités entières (une valeur dont une action dépasse 5 % du portefeuille est ignorée) ;
  pas d'achat si les frais aller-retour dépassent 1 % du montant (`frais_max_relatifs`).
- `cycle/` — `Cycle` (journal JSON par étape), `Verrou` (ligne unique pour la sérialisation) ; `deroulement.ETAPES`
  liste les étapes (nouvelles, cours, decisions, execution ; le plan 3 en ajoute). `manage.py cycle` : une étape
  en échec n'arrête pas les suivantes, code de sortie 0, cycles de plus de 30 jours purgés, cycle `en_cours` de plus de 10 min
  abandonné. Il sera lancé toutes les 5 minutes par un timer systemd (plan 5).

## Intégration continue

`.github/workflows/ci.yml` : tests sur PostgreSQL 16 (image ECR en cache, jamais un `services:`), migrations,
`check --deploy`, ruff, pip-audit. `codeql.yml` (Python), `dependabot-automerge.yml`. Pas de `deploy.yml` ni
de `deploy/` avant le plan 5.
