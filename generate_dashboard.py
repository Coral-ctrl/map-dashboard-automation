#!/usr/bin/env python3
"""
MAP Connect dashboard automation
=================================

Turns a raw Eventbrite CSV export into a finished registration dashboard,
a shareable PDF, a handful of PNG chart images, and (optionally) a fresh
page in Notion with everything already attached.

USAGE
-----
    python generate_dashboard.py inputs/some-export.csv

WHAT IT DOES, IN ORDER
-----------------------
  1. Reads the Eventbrite CSV export.
  2. Computes every number the dashboard needs (totals, breakdowns, %s).
  3. Calls Claude to cluster the two open-text questions ("question for
     the speaker" and "future topics") into themes — the same grouping
     we used to do by hand.
  4. Fills in template.html to build the finished dashboard.
  5. Uses a headless browser (Playwright) to export that dashboard as a
     PDF and as PNG images — one per chart card, plus one of the whole
     page.
  6. If Notion credentials are set, uploads everything to a new Notion
     page so it's waiting for you there.
  7. Saves every file into a dated folder under outputs/.

ONE-TIME SETUP
---------------
See SETUP_GUIDE.md in this folder. Short version: install the packages
in requirements.txt, run `playwright install chromium`, and copy
.env.example to .env with your API keys filled in.

EDITING THIS FILE
------------------
You should almost never need to touch anything below the CONFIG block.
The one exception: if Eventbrite changes the exact wording of a
registration question, the auto-detect below might grab the wrong
column — see COLUMN_HINTS and COLUMN_OVERRIDE.
"""

import os
import sys
import json
import re
import html
import pathlib
import datetime
from collections import Counter

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIG — the only section you should normally need to touch
# ============================================================

# Shown in the dashboard header. Leave EVENT_DATE blank ("") to omit it.
EVENT_NAME = os.environ.get("EVENT_NAME", "MAP Connect")
EVENT_DATE = os.environ.get("EVENT_DATE", "")  # e.g. "Sep 23"

SOURCE_LABEL = "Eventbrite order report"

# Which self-reported experience answers count as "already experienced"
# for the KPI card. Edit this list if Eventbrite's answer wording changes.
EXPERIENCED_LABELS = ["Regular user", "Advanced"]

# Keyword hints used to auto-detect each CSV column. The script checks
# each column's header (lowercased) for these substrings, in order.
# If it keeps picking the wrong column for a given event, just hardcode
# the exact header text in COLUMN_OVERRIDE instead of relying on hints.
COLUMN_HINTS = {
    "order_date": ["order date"],
    "attendee_status": ["attendee status"],
    "ticket_type": ["ticket type"],
    "total_paid": ["total paid"],
    "role": ["role", "best describes"],
    "experience": ["experience", "how would you describe"],
    "speaker_q": ["speaker", "question for"],
    "future_topics": ["topic", "future", "explore"],
}
COLUMN_OVERRIDE = {
    # "speaker_q": "Exact column header text goes here",
}

MODEL_NAME = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# Alternative to ANTHROPIC_API_KEY: if you'd rather use an existing
# OpenAI key, set OPENAI_API_KEY instead. If both are set, Anthropic
# is used. If neither is set, the script falls back to the free
# manual-clustering-via-chat flow (see write_prep_file below).
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")

# Which browser Playwright launches to render the PDF/PNGs.
# "chrome" uses the regular Google Chrome already on your machine —
# no download needed, and it sidesteps Playwright's periodic "does not
# support chromium on macOS <version>" install error entirely.
# Set to "" in .env to use Playwright's own downloaded Chromium instead
# (requires `playwright install chromium` to have succeeded).
BROWSER_CHANNEL = os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_TITLE_PROPERTY = os.environ.get("NOTION_TITLE_PROPERTY", "Name")
NOTION_VERSION = "2026-03-11"

HERE = pathlib.Path(__file__).parent
TEMPLATE_PATH = HERE / "template.html"
OUTPUT_ROOT = HERE / "outputs"

#  Used for bar-chart rows: adjacent same-count ranks are allowed to
#  share a color since each row still has its own label.
PALETTE = [
    "var(--jade)", "var(--jade)", "var(--sage)", "var(--amber)",
    "var(--amber)", "var(--plum)", "var(--grey-bar)", "var(--grey-bar)",
    "var(--grey-bar)", "var(--grey-bar)",
]

#  Used for the donut chart: every segment needs a visually distinct
#  color since there's no per-segment label on the wedge itself.
DONUT_PALETTE = [
    "var(--jade)", "var(--amber)", "var(--plum)", "var(--sage)", "var(--grey-bar)",
]

# ============================================================
# CSV loading + column detection
# ============================================================


def find_column(columns, key):
    if key in COLUMN_OVERRIDE:
        return COLUMN_OVERRIDE[key]
    hints = COLUMN_HINTS.get(key, [])
    lower = {c: c.lower() for c in columns}
    for hint in hints:
        for col, low in lower.items():
            if hint in low:
                return col
    return None


def load_csv(path):
    df = pd.read_csv(path)
    cols = {key: find_column(df.columns, key) for key in COLUMN_HINTS}
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        print("WARNING: could not auto-detect these columns:", missing)
        print("Available columns in the CSV:")
        for c in df.columns:
            print("  -", c)
        print(
            "Fix this by adding an entry to COLUMN_OVERRIDE at the top "
            "of generate_dashboard.py, then re-run."
        )
    return df, cols


# ============================================================
# Stats + chart data
# ============================================================


def color_for_rank(i):
    return PALETTE[i] if i < len(PALETTE) else "var(--grey-bar)"


def shorten_label(label, max_words=6):
    """Eventbrite answer options sometimes carry a long explanatory
    suffix ('Regular user — I use AI for work or study'). Chart labels
    look best short, so cut at a dash/em-dash if present, else cap the
    word count."""
    for sep in [" — ", " – ", " - "]:
        if sep in label:
            return label.split(sep)[0].strip()
    words = label.split()
    return label if len(words) <= max_words else " ".join(words[:max_words]) + "…"


def split_multiselect(series):
    """Eventbrite multi-select answers are usually pipe-separated ('A | B'),
    since commas often appear inside individual option names themselves
    (e.g. 'Business / Entrepreneurship'). We split on | first; if a value
    has no | but does have a comma/semicolon, fall back to that."""
    counts = Counter()
    for val in series.dropna():
        raw = str(val)
        if "|" in raw:
            parts = raw.split("|")
        else:
            parts = re.split(r"[,;]", raw)
        for p in parts:
            p = p.strip()
            if p:
                counts[p] += 1
    return counts.most_common()


def compute_stats(df, cols):
    total = len(df)

    # ---------- timeline ----------
    dates = pd.to_datetime(df[cols["order_date"]]).dt.date
    daily_counts = dates.value_counts().sort_index()
    labels = [d.strftime("%b %d") for d in daily_counts.index]
    daily = [int(v) for v in daily_counts.values]
    cumulative = list(pd.Series(daily).cumsum())
    peak_idx = int(pd.Series(daily).idxmax())
    peak_val = daily[peak_idx]
    peak_date = daily_counts.index[peak_idx]
    peak_pct = round(peak_val / total * 100)

    # ---------- role / industry ----------
    role_split = split_multiselect(df[cols["role"]]) if cols["role"] else []
    role_raw = (
        df[cols["role"]].dropna().astype(str).str.strip().value_counts().items()
        if cols["role"]
        else []
    )
    role_raw = list(role_raw)
    multi_role_count = 0
    if cols["role"]:
        def _n_parts(v):
            return len(v.split("|")) if "|" in v else len(re.split(r"[,;]", v))
        multi_role_count = df[cols["role"]].dropna().astype(str).apply(
            lambda v: _n_parts(v) > 1
        ).sum()

    # ---------- experience ----------
    exp_counts = (
        df[cols["experience"]].dropna().astype(str).str.strip().value_counts()
        if cols["experience"]
        else pd.Series(dtype=int)
    )
    def _is_experienced(v):
        v_low = v.lower()
        return any(v_low.startswith(label.lower()) for label in EXPERIENCED_LABELS)

    experienced_count = int(
        df[cols["experience"]]
        .dropna()
        .astype(str)
        .str.strip()
        .apply(_is_experienced)
        .sum()
    ) if cols["experience"] else 0
    experienced_pct = round(experienced_count / total * 100) if total else 0

    # ---------- engagement (speaker question left blank or not) ----------
    if cols["speaker_q"]:
        q_series = df[cols["speaker_q"]].dropna().astype(str).str.strip()
        q_series = q_series[q_series != ""]
    else:
        q_series = pd.Series(dtype=str)
    engagement_count = len(q_series)
    engagement_pct = round(engagement_count / total * 100) if total else 0

    # ---------- future topics (raw non-empty answers) ----------
    if cols["future_topics"]:
        topics_series = df[cols["future_topics"]].dropna().astype(str).str.strip()
        topics_series = topics_series[topics_series != ""]
        blank_count = total - len(topics_series)
    else:
        topics_series = pd.Series(dtype=str)
        blank_count = total

    # ---------- ticketing / payment blurb ----------
    ticket_types = (
        ", ".join(sorted(df[cols["ticket_type"]].dropna().unique()))
        if cols["ticket_type"]
        else "General Admission"
    )
    total_paid = df[cols["total_paid"]].sum() if cols["total_paid"] else 0
    money_blurb = "Free ($0 AUD)" if total_paid == 0 else f"${total_paid:.0f} AUD collected"
    attending_count = (
        (df[cols["attendee_status"]].astype(str).str.strip() == "Attending").sum()
        if cols["attendee_status"]
        else total
    )
    attending_pct = round(attending_count / total * 100) if total else 0

    return {
        "total": total,
        "timeline": {"labels": labels, "daily": daily, "cumulative": cumulative},
        "peak_val": peak_val,
        "peak_date": peak_date,
        "peak_pct": peak_pct,
        "role_split": role_split,
        "role_raw": role_raw,
        "multi_role_count": int(multi_role_count),
        "exp_counts": list(exp_counts.items()),
        "experienced_count": experienced_count,
        "experienced_pct": experienced_pct,
        "engagement_count": engagement_count,
        "engagement_pct": engagement_pct,
        "speaker_questions": list(q_series),
        "future_topics_answers": list(topics_series),
        "blank_topics_count": int(blank_count),
        "ticket_types": ticket_types,
        "money_blurb": money_blurb,
        "attending_pct": attending_pct,
    }


# ============================================================
# Claude clustering
# ============================================================

CLUSTER_PROMPT = """You are helping organize open-text survey answers from an AI
community event registration form into a short, skimmable dashboard.

Below are two lists of raw attendee answers, plus some numbers you can use
for context (do not invent any numbers beyond what's given here).

SPEAKER QUESTIONS ({n_speaker} non-empty answers):
{speaker_block}

FUTURE TOPIC REQUESTS ({n_topics} non-empty answers):
{topics_block}

CONTEXT NUMBERS:
- Registrations by day: {daily_json}
- Role/industry counts: {role_json}

Return ONLY a single JSON object (no markdown fences, no prose before or
after) with this exact shape:

{{
  "speaker_question_clusters": [
    {{"title": "short theme name", "count": <number of attendees whose question fits this theme>, "quotes": ["1-3 representative verbatim questions from the list above"]}}
  ],
  "future_topic_clusters": [
    {{"title": "short theme name", "count": <number>, "quotes": ["1-3 representative verbatim answers"]}}
  ],
  "non_specific_speaker_count": <number of speaker-question answers that are filler / not an actual question>,
  "non_specific_topics_count": <number of future-topic answers that are filler / not an actual topic>,
  "timeline_insight": "one short sentence (under 160 characters) describing the registration timing pattern, using only the numbers given above",
  "role_insight": "one short sentence (under 160 characters) describing the role/industry mix, using only the numbers given above"
}}

Rules:
- Before clustering, set aside any answer that isn't a genuine, specific question or topic — filler like "n/a", "none", "no", "nothing", "just curious", "no questions for now", "无", "没有", or similar non-answers (in English or Chinese). Do not build a cluster around these and do not let them inflate any cluster's count — instead, count how many were set aside from each list and report them as non_specific_speaker_count / non_specific_topics_count.
- Every remaining count must be based on how many of the listed answers genuinely fit that theme — don't inflate.
- Aim for 4-6 clusters per list. It's fine to have fewer if the answers are sparse.
- Include up to 3 quotes per cluster where enough distinct answers support it — fewer is fine for smaller clusters, but don't cap yourself at 2 if a third good one exists.
- Quotes must be copied verbatim from the lists above, not paraphrased.
- Keep cluster titles under 6 words.
- If a list is empty, return an empty array for that key.
"""


def build_cluster_prompt(stats):
    speaker_block = "\n".join(f"- {q}" for q in stats["speaker_questions"]) or "(none)"
    topics_block = "\n".join(f"- {t}" for t in stats["future_topics_answers"]) or "(none)"
    return CLUSTER_PROMPT.format(
        n_speaker=len(stats["speaker_questions"]),
        speaker_block=speaker_block,
        n_topics=len(stats["future_topics_answers"]),
        topics_block=topics_block,
        daily_json=json.dumps(dict(zip(stats["timeline"]["labels"], stats["timeline"]["daily"]))),
        role_json=json.dumps(dict(stats["role_split"])),
    )


def _parse_cluster_json(text):
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip())
    return json.loads(text)


def cluster_with_claude(stats):
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    prompt = build_cluster_prompt(stats)

    resp = client.messages.create(
        model=MODEL_NAME,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    try:
        return _parse_cluster_json(text)
    except json.JSONDecodeError:
        print("WARNING: Claude did not return valid JSON. Raw response:")
        print(text)
        return {
            "speaker_question_clusters": [],
            "future_topic_clusters": [],
            "timeline_insight": "",
            "role_insight": "",
        }


def cluster_with_openai(stats):
    import openai

    client = openai.OpenAI()  # reads OPENAI_API_KEY from env
    prompt = build_cluster_prompt(stats)

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content
    try:
        return _parse_cluster_json(text)
    except json.JSONDecodeError:
        print("WARNING: OpenAI did not return valid JSON. Raw response:")
        print(text)
        return {
            "speaker_question_clusters": [],
            "future_topic_clusters": [],
            "timeline_insight": "",
            "role_insight": "",
        }


def cluster_with_claude_code(stats):
    """Runs the clustering step through the Claude Code CLI in headless
    mode (`claude -p`), authenticated with your existing Pro/Max
    subscription login rather than a metered API key. Requires the
    `claude` command to be installed and already logged in (run `claude`
    once interactively and follow /login if you haven't).

    Deliberately does NOT pass --bare: that flag makes headless runs
    more reproducible by skipping local config discovery, but it also
    disables OAuth/keychain credential reading entirely, which breaks
    subscription-based auth outright."""
    import subprocess

    prompt = build_cluster_prompt(stats)
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # force subscription auth, not API billing

    result = subprocess.run(
        [
            "claude", "-p",
            "Follow the instructions in the piped input below and reply "
            "with ONLY the JSON object it specifies — no prose, no "
            "markdown fences.",
            "--output-format", "json",
        ],
        input=prompt,
        capture_output=True, text=True, timeout=180, env=env,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail[:3000])

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None

    # Headless mode can exit 0 while still reporting an error inside the
    # JSON payload itself (is_error: true) — catch that case too, since
    # returncode alone doesn't tell the whole story.
    if isinstance(payload, dict) and payload.get("is_error"):
        raise RuntimeError(f"Claude Code reported an error: {result.stdout.strip()[:3000]}")

    inner_text = payload.get("result", result.stdout) if isinstance(payload, dict) else result.stdout
    return _parse_cluster_json(inner_text)


def write_prep_file(stats, out_dir):
    """Writes a ready-to-paste prompt for doing the clustering step by hand
    in a chat with Claude, instead of paying for an API call."""
    prompt = build_cluster_prompt(stats)
    header = (
        "Paste EVERYTHING below the ===== line into a chat with Claude\n"
        "(claude.ai, the app, wherever you normally talk to it — no API\n"
        "key needed for this). Then take Claude's reply — just the JSON\n"
        "part — and save it as clusters.json in this same folder:\n\n"
        f"  {out_dir / 'clusters.json'}\n\n"
        "Once that file exists, run this exact same command again and the\n"
        "script will pick it up automatically and finish building everything.\n"
    )
    divider = "=" * 70
    path = out_dir / "for_claude.txt"
    path.write_text(f"{header}\n{divider}\n\n{prompt}\n", encoding="utf-8")
    return path


def load_clusters_file(path):
    text = path.read_text(encoding="utf-8")
    try:
        return _parse_cluster_json(text)
    except json.JSONDecodeError as e:
        print(f"Could not read {path} as JSON: {e}")
        print("Make sure the file contains only Claude's JSON reply — no extra")
        print("text before or after it (markdown ```json fences are fine, those")
        print("get stripped automatically).")
        sys.exit(1)


def rank_clusters(clusters):
    """Standard competition ranking (1,2,2,4...) by count, descending."""
    ordered = sorted(clusters, key=lambda c: -c.get("count", 0))
    ranks = []
    prev_count, prev_rank = None, 0
    for i, c in enumerate(ordered, start=1):
        rank = prev_rank if c.get("count") == prev_count else i
        ranks.append(rank)
        prev_rank, prev_count = rank, c.get("count")
    return list(zip(ordered, ranks))


def build_speakerq_html(clusters):
    blocks = []
    for cluster, rank in rank_clusters(clusters):
        title = html.escape(cluster.get("title", ""))
        count = cluster.get("count", 0)
        quotes = cluster.get("quotes", [])
        items = "\n".join(
            f'              <li>{html.escape(q)}</li>' for q in quotes
        )
        blocks.append(f"""        <div class="qcluster">
          <div class="qrank">{rank:02d}</div>
          <div>
            <div class="qcluster-head">
              <span class="qcluster-title">{title}</span>
              <span class="qcount">{count} attendees</span>
            </div>
            <ul class="qlist">
{items}
            </ul>
          </div>
        </div>""")
    return "\n".join(blocks)


# ============================================================
# Template filling
# ============================================================


def build_html(stats, ai, source_filename):
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    event_title_html = f"<em>{html.escape(EVENT_NAME)}</em>"
    if EVENT_DATE:
        event_title_html += f" — {html.escape(EVENT_DATE)}"

    dates = stats["timeline"]["labels"]
    data_window = f"{dates[0]} – {dates[-1]}, {datetime.date.today().year}" if dates else ""

    kpi_total_sub = f"{stats['ticket_types']} · {stats['money_blurb']} · {stats['attending_pct']}% confirmed Attending"
    kpi_peak_sub = f"{stats['peak_date'].strftime('%a %b %d')} — {stats['peak_pct']}% of all registrations landed in one day"
    kpi_exp_sub = f"{stats['experienced_count']} of {stats['total']} attendees reported regular or advanced AI use"
    kpi_eng_sub = f"{stats['engagement_count']} of {stats['total']} left a question or topic ask"

    timeline_footnote = (
        " · ".join(f"{l}: {v}" for l, v in zip(dates, stats["timeline"]["daily"]))
    )
    if ai.get("timeline_insight"):
        timeline_footnote += " — " + ai["timeline_insight"]

    role_desc = "Eventbrite lets attendees pick more than one role, so counts may add up to more than the total registrations."
    if ai.get("role_insight"):
        role_desc = ai["role_insight"]

    speakerq_desc = (
        f"{stats['engagement_count']} of {stats['total']} attendees left a question. "
        f"Grouped by similarity, ranked by how many asked something similar — "
        f"1–2 representative questions per cluster, ready to read out."
    )
    topics_desc = (
        'From the future-topics question only, tagged by theme. '
        '"No specific ask / blank" covers unanswered entries.'
    )

    role_split_pairs = [[label, count] for label, count in stats["role_split"]]
    role_raw_pairs = [[label, count] for label, count in stats["role_raw"]]
    role_footnote_split = (
        f"{stats['multi_role_count']} attendees selected more than one role — counts reflect every role picked."
        if stats["multi_role_count"]
        else "Each attendee selected a single role."
    )
    role_footnote_raw = "Raw combinations exactly as submitted."

    topics_clusters = ai.get("future_topic_clusters", [])
    topics_js = [
        [c.get("title", ""), c.get("count", 0), color_for_rank(i)]
        for i, c in enumerate(sorted(topics_clusters, key=lambda c: -c.get("count", 0)))
    ]
    topics_js.append(["No specific ask / blank", stats["blank_topics_count"], "var(--grey-bar)"])

    exp_js = [
        [shorten_label(label), count, DONUT_PALETTE[i % len(DONUT_PALETTE)]]
        for i, (label, count) in enumerate(stats["exp_counts"])
    ]

    replacements = {
        "__TITLE__": f"{EVENT_NAME} · Registration Dashboard",
        "__EVENT_TITLE_HTML__": event_title_html,
        "__DATA_WINDOW__": data_window,
        "__SOURCE_LABEL__": SOURCE_LABEL,
        "__KPI_TOTAL__": str(stats["total"]),
        "__KPI_TOTAL_SUB__": kpi_total_sub,
        "__KPI_PEAK__": str(stats["peak_val"]),
        "__KPI_PEAK_SUB__": kpi_peak_sub,
        "__KPI_EXP_PCT__": str(stats["experienced_pct"]),
        "__KPI_EXP_SUB__": kpi_exp_sub,
        "__KPI_ENG_PCT__": str(stats["engagement_pct"]),
        "__KPI_ENG_SUB__": kpi_eng_sub,
        "__TIMELINE_DESC__": "Registrations across the data window shown above.",
        "__TIMELINE_FOOTNOTE__": timeline_footnote,
        "__ROLE_DESC__": role_desc,
        "__SPEAKERQ_DESC__": speakerq_desc,
        "__SPEAKERQ_CLUSTERS_HTML__": build_speakerq_html(ai.get("speaker_question_clusters", [])),
        "__TOPICS_DESC__": topics_desc,
        "__FOOTER_SOURCE__": f"Built from {source_filename} · {stats['total']} rows",
        "__TIMELINE_JS__": json.dumps(stats["timeline"]),
        "__ROLE_JS__": json.dumps({"split": role_split_pairs, "raw": role_raw_pairs}),
        "__ROLE_FOOTNOTES_JS__": json.dumps({"split": role_footnote_split, "raw": role_footnote_raw}),
        "__TOPICS_JS__": json.dumps(topics_js),
        "__EXP_JS__": json.dumps(exp_js),
    }

    for token, value in replacements.items():
        template = template.replace(token, value)

    return template


# ============================================================
# Render PDF + PNGs
# ============================================================


def render_outputs(html_path, out_dir):
    from playwright.sync_api import sync_playwright

    pdf_path = out_dir / "dashboard.pdf"
    full_png_path = out_dir / "dashboard-full.png"
    card_ids = ["timeline-card", "role-card", "exp-card", "speakerq-card", "topics-card"]
    card_pngs = {}

    with sync_playwright() as p:
        launch_kwargs = {"channel": BROWSER_CHANNEL} if BROWSER_CHANNEL else {}
        browser = p.chromium.launch(**launch_kwargs)

        # --- PDF export: narrow viewport triggers the built-in mobile,
        #     single-column layout, which paginates cleanly ---
        pdf_page = browser.new_page(viewport={"width": 816, "height": 1200})
        pdf_page.goto(html_path.as_uri())
        pdf_page.wait_for_timeout(2200)
        pdf_page.pdf(
            path=str(pdf_path),
            format="Letter",
            print_background=True,
            margin={"top": "0.25in", "bottom": "0.35in", "left": "0", "right": "0"},
        )
        pdf_page.close()

        # --- PNGs: wider viewport for crisp, shareable chart images ---
        png_page = browser.new_page(viewport={"width": 1280, "height": 1400})
        png_page.goto(html_path.as_uri())
        png_page.wait_for_timeout(2200)
        png_page.screenshot(path=str(full_png_path), full_page=True)
        for card_id in card_ids:
            card_path = out_dir / f"{card_id}.png"
            try:
                png_page.locator(f"#{card_id}").screenshot(path=str(card_path))
                card_pngs[card_id] = card_path
            except Exception as e:
                print(f"WARNING: could not screenshot #{card_id}: {e}")
        png_page.close()

        browser.close()

    return pdf_path, full_png_path, card_pngs


# ============================================================
# Notion upload
# ============================================================


def notion_headers(extra=None):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
    }
    if extra:
        headers.update(extra)
    return headers


def notion_upload_file(path):
    import requests

    create_resp = requests.post(
        "https://api.notion.com/v1/file_uploads",
        headers=notion_headers({"Content-Type": "application/json"}),
        json={"filename": path.name, "content_type": "image/png"},
    )
    create_resp.raise_for_status()
    upload_id = create_resp.json()["id"]

    with open(path, "rb") as f:
        send_resp = requests.post(
            f"https://api.notion.com/v1/file_uploads/{upload_id}/send",
            headers=notion_headers(),
            files={"file": (path.name, f, "image/png")},
        )
    send_resp.raise_for_status()
    return upload_id


def upload_to_notion(title, summary_text, full_png_path, card_pngs):
    import requests

    if not (NOTION_TOKEN and NOTION_DATABASE_ID):
        print("Notion credentials not set — skipping Notion upload. "
              "(Set NOTION_TOKEN and NOTION_DATABASE_ID in .env to enable this.)")
        return None

    print("Uploading images to Notion...")
    children = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Summary"}}]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary_text}}]}},
        {"object": "block", "type": "divider", "divider": {}},
    ]

    full_id = notion_upload_file(full_png_path)
    children.append({
        "object": "block", "type": "image",
        "image": {"type": "file_upload", "file_upload": {"id": full_id}},
    })

    for card_id, path in card_pngs.items():
        file_id = notion_upload_file(path)
        children.append({
            "object": "block", "type": "image",
            "image": {"type": "file_upload", "file_upload": {"id": file_id}},
        })

    page_resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=notion_headers({"Content-Type": "application/json"}),
        json={
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                NOTION_TITLE_PROPERTY: {
                    "title": [{"text": {"content": title}}]
                }
            },
            "children": children,
        },
    )
    page_resp.raise_for_status()
    return page_resp.json().get("url")


def try_api_clustering(stats):
    """Attempts Claude API, then OpenAI API, then the Claude Code CLI
    (subscription-based), in that order. Returns the clusters dict on
    success, or None if nothing usable is configured, or if every
    attempted path fails (unfunded account, bad key, not logged in,
    network issue, etc.) — callers should fall back to manual mode on
    None rather than crash."""
    import shutil

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("Clustering open-text answers with the Claude API...")
        try:
            return cluster_with_claude(stats)
        except Exception as e:
            print(f"  Claude API call failed: {e}")
            print("  Trying the next option instead.")
    if os.environ.get("OPENAI_API_KEY"):
        print(f"Clustering open-text answers with the OpenAI API ({OPENAI_MODEL})...")
        try:
            return cluster_with_openai(stats)
        except Exception as e:
            print(f"  OpenAI API call failed: {e}")
            print("  Trying the next option instead.")
    if shutil.which("claude"):
        print("Clustering open-text answers with Claude Code (your Pro/Max subscription)...")
        try:
            return cluster_with_claude_code(stats)
        except Exception as e:
            print(f"  Claude Code call failed: {e}")
            print("  Falling back to free manual clustering instead.")
            return None
    elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        pass  # already tried and failed above; message already printed
    else:
        print("(No ANTHROPIC_API_KEY or OPENAI_API_KEY set, and `claude` wasn't found on PATH.")
        print(" If you expected Claude Code to be picked up, run `claude --version` in this")
        print(" exact terminal to confirm it resolves here before re-running this script.)")
    return None


# ============================================================
# Main
# ============================================================


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_dashboard.py path/to/export.csv")
        sys.exit(1)

    csv_path = pathlib.Path(sys.argv[1])
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    print(f"Reading {csv_path.name}...")
    df, cols = load_csv(csv_path)
    stats = compute_stats(df, cols)
    print(f"  {stats['total']} rows · {stats['engagement_count']} left a speaker question")

    # The output folder is named after the CSV itself (not today's date),
    # so it stays the same across both runs of the manual-clustering flow —
    # today's "prep" run and tomorrow's "finish" run land in the same place.
    safe_csv = re.sub(r"[^A-Za-z0-9_-]+", "-", csv_path.stem).strip("-") or "event"
    out_dir = OUTPUT_ROOT / safe_csv
    out_dir.mkdir(parents=True, exist_ok=True)
    clusters_path = out_dir / "clusters.json"

    if clusters_path.exists():
        print(f"Found {clusters_path.name} — using your clustering.")
        ai = load_clusters_file(clusters_path)
    else:
        ai = try_api_clustering(stats)
        if ai is not None:
            clusters_path.write_text(json.dumps(ai, indent=2), encoding="utf-8")
        else:
            prep_path = write_prep_file(stats, out_dir)
            print(f"""
Let's do the clustering step by hand instead, in a normal chat:

  1. Open this file:  {prep_path}
  2. Copy everything below the ===== line into a chat with Claude.
  3. Copy Claude's reply back (just the JSON).
  4. Save it as:       {clusters_path}
  5. Run this exact same command again:
       python3 generate_dashboard.py {csv_path}

The script will pick up clusters.json automatically and finish
building the dashboard, PDF, images, and Notion upload from there.
""")
            return

    print("Building dashboard HTML...")
    html_out = build_html(stats, ai, csv_path.name)

    html_path = out_dir / "dashboard.html"
    html_path.write_text(html_out, encoding="utf-8")
    print(f"  wrote {html_path}")

    print("Rendering PDF + PNG images...")
    pdf_path, full_png_path, card_pngs = render_outputs(html_path, out_dir)
    print(f"  wrote {pdf_path}")
    print(f"  wrote {full_png_path}")
    for p in card_pngs.values():
        print(f"  wrote {p}")

    stamp = datetime.date.today().isoformat()
    title = f"{EVENT_NAME}{' — ' + EVENT_DATE if EVENT_DATE else ''} — {stamp}"
    summary_text = (
        f"Total registrations: {stats['total']} · "
        f"Peak day: {stats['peak_date'].strftime('%b %d')} ({stats['peak_val']}) · "
        f"Regular/advanced AI users: {stats['experienced_pct']}% · "
        f"Left a question: {stats['engagement_pct']}%"
    )
    notion_url = upload_to_notion(title, summary_text, full_png_path, card_pngs)
    if notion_url:
        print(f"  Notion page: {notion_url}")

    print(f"\nDone. Everything is in: {out_dir}")


if __name__ == "__main__":
    main()
