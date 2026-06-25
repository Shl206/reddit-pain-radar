# Reddit Pain Radar

Reddit Pain Radar is a local personal research script that scans public Reddit RSS feeds, scores posts for pain signals, and writes a daily Markdown report.

Version 0 uses RSS only. It does not use Reddit OAuth, login cookies, browser automation, scraping, a database, or LLM calls.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Configure

Edit the subreddit list:

```text
config/subreddits.txt
```

Edit the pain keyword list:

```text
config/pain_keywords.txt
```

Tune request timing:

```text
config/settings.json
```

## Run

Daily workflow:

```powershell
.\.venv\Scripts\python pain_radar.py
```

Daily workflow with memory retrieval:

```powershell
.\.venv\Scripts\python pain_radar.py --task-goal "Find Toronto restaurant missed calls automation pain points" --use-memory
```

The script writes:

```text
data/raw/YYYY-MM-DD.json
data/processed/YYYY-MM-DD.json
reports/YYYY-MM-DD.md
research_notes/YYYY-MM-DD.md
```

Use `reports/YYYY-MM-DD.md` to scan the daily findings. Use `research_notes/YYYY-MM-DD.md` as the editable personal journal file for manual review decisions.

Weekly summary:

```powershell
.\.venv\Scripts\python pain_radar.py --weekly
```

The weekly command reads existing files from `data/processed/` and writes:

```text
weekly_reports/YYYY-MM-DD_weekly.md
```

Agent memory search:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-search "restaurant missed calls automation"
```

Agent memory feedback:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-feedback RUN_ID --useful true --rating 8 --note "good reusable pattern"
```

Agent memory impact evaluation:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-impact 031920 --helpful true --rating 8 --influenced "Retrieved prior memory before run" --avoided "Avoided repeated weak searches" --improved "Improved focus on restaurant automation" --note "Memory was useful"
.\.venv\Scripts\python pain_radar.py --memory-stats
```

Agent memory quality review:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-review 031920 --status approved --tag restaurant --tag automation --reason "Useful local business pattern"
.\.venv\Scripts\python pain_radar.py --memory-search "restaurant automation"
.\.venv\Scripts\python pain_radar.py --memory-search "restaurant automation" --include-rejected-memory
```

## How Scoring Works

V0.2 only includes a post in the main report sections when it matches at least one strong pain pattern:

- explicit complaint
- struggle or request
- tool intent
- manual workaround
- money pain

Weak terms like `automation`, `tool`, `software`, `spreadsheet`, `SaaS`, `startup`, `idea`, and question marks do not qualify a post by themselves. They can add context only after a real pain pattern is present.

The report separates signals into high, medium, low, non-English, and excluded weak sections. V0.3 also adds a Manual Review section and a separate editable research note for high relevance signals.

## Agent Experience Index

The Agent Experience Index is a local memory layer for the research process. After each daily run, the tool saves what worked, what failed, the best leads, and a reusable research pattern so future runs can search prior experience before starting from zero.

It writes local files only:

```text
agent_memory/trajectories/
agent_memory/summaries/
agent_memory/index/
agent_memory/feedback.jsonl
```

Use memory search before a new research task to find prior patterns:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-search "pricing compliance workflow"
.\.venv\Scripts\python pain_radar.py --memory-search "restaurant missed calls automation"
```

When `--use-memory` is enabled, the daily report includes a `Retrieved Agent Memory` section with matched run IDs, reusable patterns, failed paths to avoid, and best prior leads. The saved trajectory also records the retrieved memory run IDs and context.

Use feedback after reviewing whether a saved run was useful:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-feedback 123456 --useful true --rating 8 --note "good reusable pattern"
```

Use memory impact evaluation after a memory-assisted run to record whether retrieved memories improved the current research:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-impact 031920 --helpful true --rating 8 --influenced "Retrieved prior memory before run" --avoided "Avoided repeated weak searches" --improved "Improved focus on restaurant automation" --note "Test impact record"
.\.venv\Scripts\python pain_radar.py --memory-stats
```

Impact records are saved locally to:

```text
agent_memory/memory_impact.jsonl
```

V0.4 adds a Memory Quality Gate. New memories start as `pending_review`. You can review them as `approved`, `rejected`, or `gold`, and add quality tags:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-review 031920 --status approved --tag restaurant --tag automation --reason "Useful local business pattern"
```

Memory search ranks `gold` first, `approved` next, and `pending_review` lower. Rejected memories are excluded unless you explicitly include them:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-search "restaurant automation" --include-rejected-memory
```



V0.5 adds a Memory Review Queue so pending memories can be reviewed before they pollute future retrieval. V0.6 adds queue filters with `--limit` and `--status`. V0.7 expands the queue output with ready-to-copy approve, gold, and reject review commands:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-review-queue
.\.venv\Scripts\python pain_radar.py --memory-review-queue --limit 5
.\.venv\Scripts\python pain_radar.py --memory-review-queue --status gold
.\.venv\Scripts\python pain_radar.py --memory-review-queue --status all --limit 20
```

## Notes

Reddit may return `429 Too Many Requests` even for public RSS feeds. The tool is intentionally slow and cache-aware:

- Uses a descriptive User-Agent.
- Waits between live subreddit requests using a base delay plus random jitter.
- Retries `429` responses with `Retry-After` when Reddit provides it.
- Uses exponential backoff with jitter when `Retry-After` is missing.
- Saves successful RSS XML responses in `data/cache/`.
- Reuses cached RSS for 6 hours to avoid unnecessary requests.

Recommended use: run this 1-2 times per day, not every few minutes.

