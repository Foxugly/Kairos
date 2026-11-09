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

## Intégration continue

`.github/workflows/ci.yml` : tests sur PostgreSQL 16 (image ECR en cache, jamais un `services:`), migrations,
`check --deploy`, ruff, pip-audit. `codeql.yml` (Python), `dependabot-automerge.yml`. Pas de `deploy.yml` ni
de `deploy/` avant le plan 5.
