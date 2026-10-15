# Publish this project to GitHub

The project repository has already been created at https://github.com/sakshimis/Railway_agent. For subsequent local commits, run `git push origin main` from the runnable project folder. The first-push instructions below are retained only for someone making a separate copy.

This repository is a **local educational prototype**. Read `README.md`, `REQUIREMENTS.md` and `DATA_SOURCES.md` before publishing it. It does not provide a live railway API or production booking.

## Before the first push

1. Decide whether the repository should be **private or public**. If public, verify that the Kaggle source license and redistribution terms permit publishing the derived `data/historical_catalog.sqlite` file and retain any required notices. The catalog is about 47 MB, so use Git rather than GitHub's browser upload.
2. Run the project tests: `python -m unittest discover -s tests -v`.
3. Check `git status --short` and `git ls-files` before committing. The tracked files should not include `runtime/`, `.venv/`, `__pycache__/`, `.env` or downloaded raw ZIPs. Do not add your real PNRs, passwords or API credentials.
4. The bundled `data/pnr.json` and refund records are fictional examples. `runtime/accounts.json` is generated locally and is intentionally ignored.

## Create a new repository

Create an empty repository on GitHub, without adding a README or license there. In PowerShell, from this project folder:

```powershell
git init
git add .
git status --short
git commit -m "Initial railway AI case study prototype"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Replace the example remote with the URL GitHub gives you. If Git requests authentication, use GitHub's supported sign-in flow or a credential manager; do not put a token in the remote URL or commit it to a file. If you already have a repository, use its existing remote and skip `git init` and `git remote add`.

## Run after cloning on another Windows computer

Install Python 3.12 or later from the official Python site, then in PowerShell from the cloned project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe app.py --init-users
.\.venv\Scripts\python.exe app.py
```

Create new user/admin passwords on that computer. Open `http://127.0.0.1:8765`. The app uses only Python's standard library at runtime, so there is no package install step. If the catalog was intentionally left out of a public repository, follow `README.md` to rebuild it from the source Kaggle ZIPs first.
