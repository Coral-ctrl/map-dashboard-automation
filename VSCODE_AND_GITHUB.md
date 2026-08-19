# Using VS Code + GitHub

Everything from SETUP_GUIDE.md still applies — this just covers doing
it inside VS Code instead of the plain Terminal app, plus pushing the
project to GitHub so it's backed up and versioned.

---

## Part 1 — Open the project in VS Code

1. Open VS Code.
2. `File → Open Folder...` and select the `map-dashboard-automation` folder.
3. Open the built-in terminal: `Terminal → New Terminal` (or `` Ctrl+` `` / `` Cmd+` ``). This is the exact same terminal as before, just docked at the bottom of the editor.
4. Run every command from SETUP_GUIDE.md (Steps 3, 6, 8) in this terminal exactly as written — nothing changes about the commands themselves.

Optional but nice: install the **Python** extension (search in the Extensions panel, the puzzle-piece icon on the left) for syntax highlighting and inline errors while you're looking at `generate_dashboard.py`.

---

## Part 2 — Push to GitHub

**Before you do this**, double check `.env` is not open/saved with real
keys visible in a file that isn't `.gitignore`-protected — it is
already protected (see below), just flagging it since it holds your
API keys.

### The easy way — VS Code's built-in button

1. Click the **Source Control** icon in the left sidebar (it looks like a branching line, third or fourth icon down).
2. Click **Initialize Repository**.
3. You'll see a list of changed files. Confirm it does **not** show `.env`, anything in `inputs/`, or anything in `outputs/` — only the code and guide files should appear. (The `.gitignore` file in this folder already takes care of this automatically.)
4. Type a commit message like `Initial version of dashboard automation`, click the checkmark to commit.
5. Click **Publish to GitHub** (button appears at the top of the Source Control panel). VS Code will ask you to sign in to GitHub in your browser the first time — approve it there.
6. Choose **Private repository** (recommended, since this tool touches real attendee data even though that data itself isn't uploaded) and confirm the name.

That's it — VS Code handles authentication and the upload for you.

### The command-line way, if you prefer typing it

```
git init
git add .
git commit -m "Initial version of dashboard automation"
```

Then create an empty repo at [github.com/new](https://github.com/new) (**don't** initialize it with a README — you already have one), copy the URL it gives you, and run:

```
git remote add origin <paste the URL here>
git branch -M main
git push -u origin main
```

The first push will ask you to authenticate — GitHub no longer accepts
your account password here, so either let it open a browser sign-in
window (easiest), or use a Personal Access Token from
`github.com/settings/tokens` as the password if prompted.

---

## Every time after that (once it's on GitHub)

Same as always — drop a CSV in `inputs/`, run the script. If you want
to save your changes to GitHub too (e.g. you tweaked `template.html`
or added a `COLUMN_OVERRIDE`), use the Source Control panel: review
the changed files, write a short commit message, click the checkmark,
then click **Sync Changes** to push. Real attendee data still never
leaves your machine — it stays gitignored no matter how many times you
commit.
