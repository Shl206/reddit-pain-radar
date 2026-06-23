# AGENTS.md

You are working on a personal/internal-use Python MVP called reddit-pain-radar.

Primary goal:
Build the smallest working local tool that finds repeated pain points from Reddit posts/comments and generates a Markdown report.

User constraints:
- Codex usage limits are tight.
- Prefer simple working code over perfect architecture.
- Avoid unnecessary refactors.
- Avoid web app, Docker, cloud deploy, auth system, frontend, or complex framework.
- First version should be a single Python script unless there is a strong reason otherwise.
- The app is for personal research only.

Coding rules:
- Python 3.10+.
- Use PRAW, python-dotenv, pandas optional, scikit-learn optional, sqlite3 standard library.
- Keep dependencies minimal.
- Use clear functions in one file.
- Use Reddit API through PRAW, not browser scraping.
- Do not attempt to bypass rate limits.
- Store short excerpts, metadata, scores, and permalinks.
- Do not store usernames.
- Do not use Reddit data for model training.
- Do not add LLM calls in v1.

Work style:
- First inspect existing files.
- Then implement directly.
- Do not ask for clarification unless blocked.
- After implementation, run a small smoke test command.
- If credentials are missing, the script should print clear setup instructions instead of crashing.
- At the end, summarize changed files and exact command to run.