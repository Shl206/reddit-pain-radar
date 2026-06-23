# reddit-pain-radar

## Purpose

reddit-pain-radar is a personal/internal local developer tool for product discovery. It uses Reddit Data API read-only access to monitor a small set of public subreddits for repeated product pain-point signals and generate a private local Markdown report.

## What it does

* Reads a limited number of recent public posts from selected public subreddits.
* Reads a limited number of top-level public comments.
* Uses local rule-based scoring and clustering.
* Generates a private local Markdown report.
* Stores limited metadata locally in SQLite.

## What it does not do

* Does not post, comment, vote, send direct messages, or moderate.
* Does not store usernames, author IDs, profile URLs, avatars, or private messages.
* Does not infer sensitive personal attributes.
* Does not train, fine-tune, or build AI models with Reddit data.
* Does not redistribute, resell, or commercialize Reddit data.
* Does not bypass rate limits or access controls.
* Does not scrape Reddit web pages.

## Data storage

The tool stores only short excerpts, subreddit name, timestamps, Reddit score/comment count, permalink, URL, matched keywords, and local pain score in a local SQLite database.

## Data retention

Raw post/comment excerpts are intended to be deleted within 48 hours by default. Limited aggregate scoring data, subreddit names, timestamps, matched keywords, scores, and permalinks may be retained for private local reporting.

## Compliance

* OAuth only.
* Uses a registered Reddit API client.
* Uses a descriptive User-Agent.
* Read-only usage.
* Respects Reddit rate limits.
* Uses local-only SQLite storage.
* Stores no usernames.
* Uses no Reddit data for AI training.
* Does not commercially redistribute Reddit data.

## Setup

```powershell
python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Fill in `.env` with the Reddit app client ID, client secret, and a descriptive User-Agent:

```text
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USER_AGENT=windows:reddit-pain-radar:v0.1 (by /u/YOUR_REDDIT_USERNAME)
```

## Example command

```powershell
python pain_radar.py --subreddits SaaS,startups --limit 10 --comments 3
```

## Intended subreddits

r/SaaS, r/startups, r/Entrepreneur, r/smallbusiness, r/freelance, r/webdev, r/productivity

## Status

Personal/internal non-commercial MVP. API access pending Reddit approval.
