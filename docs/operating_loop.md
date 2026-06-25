# Reddit Pain Radar V1 Operating Loop

This is the stable daily loop for using Reddit Pain Radar as a personal research operating system.

## Purpose

Reddit Pain Radar is not just a scraper. It is a loop for finding repeated pain signals, turning them into research leads, and improving the agent memory system over time.

The goal is to avoid random browsing and build a compounding research memory.

## Daily Loop

Run this once per day, not every few minutes:

```powershell
.\.venv\Scripts\python pain_radar.py --use-memory --task-goal "Find high-signal Reddit pain points and business opportunities."
```

Then open the generated files:

```text
reports/YYYY-MM-DD.md
research_notes/YYYY-MM-DD.md
data/processed/YYYY-MM-DD.json
```

## Memory Review Loop

After a run, check pending memories:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-review-queue --limit 10
```

For each memory, choose one action:

- `approved`: useful enough to keep.
- `gold`: high-signal pattern worth prioritizing in future retrieval.
- `rejected`: weak, noisy, or not reusable.

Example:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-review 031920 --status approved --tag workflow_pain --reason "Useful recurring research pattern"
```

## Weekly Loop

Run a weekly summary after several daily runs:

```powershell
.\.venv\Scripts\python pain_radar.py --weekly
```

Then review:

```text
weekly_reports/YYYY-MM-DD.md
```

## Health Check

Use memory health to see whether the system is improving or turning into backlog:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-health
```

Healthy direction:

- pending review should not grow forever.
- rejected memories should exist; otherwise the filter is too soft.
- gold memories should be rare.
- impact ratings should be recorded after memory-assisted runs.

## Impact Evaluation

After a memory-assisted run, record whether memory helped:

```powershell
.\.venv\Scripts\python pain_radar.py --memory-impact 031920 --helpful true --rating 8 --influenced "Reused prior pattern" --avoided "Avoided weak search path" --improved "Found better leads" --note "Memory helped focus the run"
```

## Smoke Test Before Commit

Before committing changes, run:

```powershell
.\scripts\smoke_test.ps1
```

This avoids a live Reddit fetch and checks the core local loop.

## Commit Rule

Only commit source, config, scripts, and docs.

Do not commit:

```text
.ai-bridge/
agent_memory/
data/raw/
data/processed/
data/cache/
reports/
research_notes/
weekly_reports/
```

## V1 Definition of Done

V1 is usable when this loop works end to end:

1. daily run creates report, notes, processed data, and memory.
2. review queue shows pending memories.
3. review commands can approve, gold, or reject memories.
4. memory health gives a useful diagnosis.
5. smoke test passes before commits.
6. README points users to this operating loop.

## Next Product Direction

Do not add more memory commands until the daily loop has been used for several real days.

The next useful product direction is better lead quality:

- better subreddit selection.
- stronger scoring rules.
- better false-positive filters.
- clearer business opportunity templates.
