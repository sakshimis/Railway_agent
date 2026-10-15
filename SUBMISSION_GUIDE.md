# Submission guide

## What to submit

1. The GitHub repository: https://github.com/sakshimis/Railway_agent
2. The accompanying project report PDF from the submission package.
3. If your portal accepts a ZIP, upload `railway_ai_submission.zip` instead of a copy of the running folder. The ZIP excludes passwords, audit logs, virtual environments and downloaded raw datasets.

## Run the demonstration

On Windows with Python 3.12 or later, open PowerShell in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe app.py --init-users
.\.venv\Scripts\python.exe app.py
```

Create separate `user` and `admin` passwords when prompted. Open http://127.0.0.1:8765. The first command is needed only once. For later runs, use only the final command. The bundled catalog and model summaries are already in `data/`; no Kaggle download is required to run the demo.

## Verify before presenting

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Follow `DEMO_SCRIPT.md` for a five-minute walkthrough. Use `REQUIREMENTS.md` when explaining which PDF requirements are implemented, partial or blocked by missing authorized live data. Do not present historical fares or synthetic PNR, booking, confirmation and governance exercises as live railway services.

## Data and publication note

The bundled historical catalog is derived from a public Kaggle dataset. `DATA_SOURCES.md` links each source and records its limitations. Verify source licensing and redistribution terms before any public release. Do not commit `runtime/` or credentials.
