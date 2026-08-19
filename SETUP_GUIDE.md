# MAP dashboard automation — setup guide

This is a one-time setup (about 10–15 minutes). After this, running the
whole thing for a future event takes two actions: drop in a CSV, type
one command.

---

## What you'll end up with

Every time you run the tool with a new Eventbrite export, it creates a
dated folder containing:

- `dashboard.html` — the interactive dashboard
- `dashboard.pdf` — a static, skimmable PDF version
- `dashboard-full.png` — one image of the whole dashboard
- five more PNGs, one per chart, ready to paste into WeChat or Slack

...and if you set up the optional Notion step, all of those images also
land automatically on a new page in Notion.

---

## Step 1 — Check you have Python

Open your terminal.

- **Mac**: press `Cmd + Space`, type "Terminal", press Enter.
- **Windows**: press the Start key, type "PowerShell", press Enter.
- **Using VS Code instead**: open VS Code, go to the menu `Terminal → New Terminal`. This is the exact same thing as the steps above, just inside the editor — use whichever you find easier.

Type this and press Enter:

```
python3 --version
```

If you see something like `Python 3.11.4`, you're set — skip to Step 2.

If you get an error, install Python from [python.org/downloads](https://python.org/downloads) first (just click through the installer with default options), then come back and try the command again.

---

## Step 2 — Get this folder onto your computer

Save the `map-dashboard-automation` folder (the one containing this
guide) somewhere memorable, e.g. your Desktop or Documents.

In your terminal, move into that folder. For example, if you put it on
your Desktop:

```
cd Desktop/map-dashboard-automation
```

---

## Step 3 — Install the tools it needs

**Optional but recommended: use a virtual environment.** This keeps
this project's packages separate from anything else Python-related on
your computer.

If you're using VS Code: open the Command Palette (`Cmd+Shift+P`),
type **Python: Create Environment**, choose **Venv**, pick any Python
3.x interpreter. VS Code will detect `requirements.txt` and offer to
install everything into it automatically — say yes, then skip straight
to the `playwright install chromium` line below.

If you're not using a virtual environment, or want to set one up by
hand instead:

```
python3 -m venv .venv
source .venv/bin/activate
```

(You'll need to run that `source` line again each time you open a new
terminal window for this project — VS Code does this for you
automatically once you've created the environment through the Command
Palette.)

Either way, copy and paste this into your terminal, then press Enter:

```
pip3 install -r requirements.txt
playwright install chromium
```

This downloads a few small packages and (usually) a headless browser
used to turn the dashboard into a PDF and images.

**If the second line fails with an error like "Playwright does not
support chromium on mac13"** (or mac12, mac11, etc.) — don't worry
about it, you can ignore that error completely. Playwright periodically
raises the minimum macOS version its own downloaded browser supports,
and this script is already set up to fall back to your regular Google
Chrome instead (as long as Chrome is installed, which it almost
certainly already is). Nothing else to do here — just move on to the
next step.

---

## Step 4 — (Optional) Get an API key for automatic clustering

Skip this step entirely if you'd rather cluster the open-text questions
by hand each time in a normal chat with Claude — free, and only takes
an extra minute per event. See "How the question-clustering step
works" below for details on all three paths.

If you *do* want it fully automatic instead, you have two choices —
use whichever account you already have:

**Claude API key:**
1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in (or create an account) — this is different from your normal claude.ai login.
2. Click **Settings → API Keys → Create Key**.
3. Copy the key (it starts with `sk-ant-`).

**OpenAI API key** (if you already have an OpenAI account and would rather use that):
1. Go to [platform.openai.com](https://platform.openai.com) and sign in.
2. Go to **API Keys** in the left sidebar → **Create new secret key**.
3. Copy the key (it starts with `sk-`).

Either goes into `.env` in Step 6. For this specific task (clustering a
few dozen short survey answers), cost is under a cent per event on
either provider — genuinely negligible. If both keys are set, the
Claude one is used.

---

## How the question-clustering step works

The script needs to group similar open-text answers ("what would you
ask the speaker?", "what topics do you want covered?") into themes.
There are four ways it can do that, tried automatically in this order
— no flags to remember, and each one falls through to the next if it
fails (unfunded account, not logged in, etc.):

**1. `ANTHROPIC_API_KEY` set — fully automatic, ~$0.01/event.** The
script calls the Claude API directly and finishes in one run.

**2. `OPENAI_API_KEY` set instead — fully automatic, ~$0.001/event.**
Same one-run behavior, just calls OpenAI's API. Tried only if the
Claude key isn't set (or its call fails).

**3. Claude Code CLI, if installed and logged in — fully automatic,
$0 marginal cost.** If you already have a Claude Pro or Max
subscription and the `claude` command installed, the script runs the
clustering step through it in headless mode (`claude -p`), billed to
your existing subscription rather than a metered API key. No setup in
`.env` needed for this one — it's detected automatically if the `claude`
command exists on your machine. If you haven't installed it, see
claude.com/claude-code, then run `claude` once and follow `/login`.
*(This works because Claude Code itself is explicitly allowed to use
subscription login — Anthropic restricts that kind of login to Claude
Code and claude.ai specifically, so this script calls the real `claude`
command rather than trying to reuse a login token directly, which
Anthropic's terms don't permit.)*

**4. Manual paste — always available, always free.** If none of the
above are set up or all of them fail, the script computes everything
else, then stops and writes a file called `for_claude.txt` inside that
event's output folder. Open it, copy everything below the `=====`
line, paste it into a normal chat with Claude (claude.ai, the app —
wherever you'd normally talk to it), and Claude will reply with a
block of JSON. Save that reply as `clusters.json` in the same folder
the instructions point to, then run the *exact same command again*.
The script picks up `clusters.json` automatically and finishes the
whole thing — PDF, images, Notion upload, all of it.

You can mix and match freely — leave everything unset for most events
and add a key later if you change your mind, switch which option you
use event to event, or go back to manual any time.

**Pausing/resuming an API key.** To turn a key off for a while, just
clear its value in `.env` and save:
```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```
The next run falls through to the next available option automatically
— no other changes needed. Paste a key back in whenever you want it
used again.

---

## Step 5 — (Optional) Set up Notion

Skip this step if you're happy just opening the PDF/PNG files from
your outputs folder each time. The script works fine without it.

1. Go to [notion.so/my-integrations](https://notion.so/my-integrations) and click **New integration**.
2. Give it a name like "MAP Dashboard Bot", pick your workspace, click **Submit**.
3. Copy the **Internal Integration Token** shown (starts with `ntn_`).
4. In Notion itself, create a new database (or use an existing one) called something like "MAP Connect Dashboards".
5. Open that database, click the **`...`** menu in the top right → **Connections** → find and add your "MAP Dashboard Bot" integration. This is the step people usually miss — without it, the script can't see the database at all.
6. Copy the database's ID from its URL. A Notion database URL looks like:
   `https://www.notion.so/myworkspace/a1b2c3d4e5f6...?v=...`
   The long string right after your workspace name (before the `?`) is the database ID.

---

## Step 6 — Fill in your `.env` file (if using an API key and/or Notion)

Skip this entirely if you're going the free, manual-clustering route
and not using Notion — no `.env` file needed at all.

Otherwise: find the file called `.env.example`. Make a copy of it and
rename the copy to exactly `.env` (no ".example").

Open `.env` in any text editor and fill in whichever blanks apply to you:

```
ANTHROPIC_API_KEY=sk-ant-...          <- optional, from Step 4
OPENAI_API_KEY=sk-...                  <- optional, alternative to the above
NOTION_TOKEN=ntn_...                   <- optional, from Step 5
NOTION_DATABASE_ID=a1b2c3d4...         <- optional, from Step 5
EVENT_NAME=MAP Connect
```

Save the file. This is the only file with your private keys in it — it
never gets uploaded anywhere by the script.

---

## Step 7 — Run it

Export your registration list from Eventbrite as a CSV (same as
before), and put the file into the `inputs` folder inside
`map-dashboard-automation`.

Then in your terminal:

```
python3 generate_dashboard.py inputs/your-file-name.csv
```

**If you added an API key**, this one command does everything — reads
the CSV, clusters the questions, builds the dashboard, renders the
PDF, uploads to Notion — in about 30–60 seconds. It tells you exactly
which folder everything landed in, under `outputs/`.

**If you're going the free manual route (no API key)**, this first run
stops partway through and gives you a file to paste into a chat with
Claude — see "How the question-clustering step works" above. Once you
paste Claude's reply back into `clusters.json` as instructed, run the
exact same command a second time and it finishes the rest
automatically. Two runs total per event, one short manual step in
between.

That's it — for every future event, Steps 1–6 are done for good. You
only ever repeat Step 7.

---

## If something goes wrong

**"Could not auto-detect these columns"** — Eventbrite's exact question
wording changed since the last event. Open `generate_dashboard.py` in
a text editor, find the `COLUMN_OVERRIDE` dictionary near the top, and
paste in the exact column header from your CSV. Example:

```python
COLUMN_OVERRIDE = {
    "speaker_q": "What would you like to ask our guest speaker?",
}
```

**"Playwright does not support chromium on mac13" (or similar)** — this
is expected and already handled; see the note in Step 3 above. The
script defaults to using your regular Google Chrome instead of
Playwright's own download. If you don't have Chrome installed, grab it
free from google.com/chrome, or upgrade macOS to a newer version and
leave `PLAYWRIGHT_CHANNEL` blank in `.env` to use Playwright's own
Chromium instead.

**Notion upload fails** — double check you completed Step 5.5 above
(sharing the database with the integration). This is the single most
common thing to miss.

**Numbers look a bit different from a hand-built dashboard** — the
auto-clustering does its best but isn't identical to a human doing it
by hand; it's consistent and good enough to skim, but if a specific
event needs extra polish, you can always open `dashboard.html` in a
text editor afterward and tweak it directly.
