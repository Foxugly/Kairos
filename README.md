# Kairos

Outil de trading simulé de la flotte Foxugly : API Django (`backend/`), frontend Angular à venir.
Conception : `docs/superpowers/specs/2026-11-09-kairos-design.md`.

## Développement

```powershell
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
$env:DJANGO_DEBUG="True"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe -m ruff check .
```
