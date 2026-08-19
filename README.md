# MAP dashboard automation

First time using this? Read **SETUP_GUIDE.md** first (one-time, ~10 min).

Doing this in VS Code and want it on GitHub too? See **VSCODE_AND_GITHUB.md**.

## Every time after that

1. Export the registration CSV from Eventbrite.
2. Drop it into the `inputs/` folder.
3. Run:
   ```
   python3 generate_dashboard.py inputs/your-file-name.csv
   ```
4. Open the dated folder inside `outputs/` — dashboard, PDF, and PNGs
   are all there. If Notion is set up, they're also on a new Notion
   page automatically.

## Files in this folder

| File | What it's for |
|---|---|
| `generate_dashboard.py` | The script that does everything |
| `template.html` | The dashboard's design — edit CSS here if you want to restyle it |
| `requirements.txt` | Python packages it needs |
| `.env` | Your private API keys (create this from `.env.example`) |
| `SETUP_GUIDE.md` | One-time setup instructions |
| `inputs/` | Drop new Eventbrite CSVs here |
| `outputs/` | Every past dashboard, PDF, and image set lands here, dated |
