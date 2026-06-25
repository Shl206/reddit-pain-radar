from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict


STOPWORDS: set[str] = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "before",
    "being",
    "from",
    "have",
    "into",
    "just",
    "like",
    "more",
    "need",
    "over",
    "that",
    "their",
    "there",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


class WeeklySource(TypedDict):
    date: str
    total_posts_scanned: int
    posts: list[dict[str, Any]]


def generate_weekly_summary(processed_dir: Path, weekly_dir: Path, date_label: str) -> Path:
    sources: list[WeeklySource] = read_weekly_sources(processed_dir, date_label)
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_path: Path = weekly_dir / f"{date_label}_weekly.md"
    lines: list[str] = build_weekly_lines(date_label, sources)
    weekly_path.write_text("\n".join(lines), encoding="utf-8")
    return weekly_path


def read_weekly_sources(processed_dir: Path, date_label: str) -> list[WeeklySource]:
    end_date: datetime = datetime.strptime(date_label, "%Y-%m-%d")
    start_date: datetime = end_date - timedelta(days=6)
    sources: list[WeeklySource] = []
    for path in sorted(processed_dir.glob("*.json")):
        file_date: datetime | None = date_from_path(path)
        if file_date is None:
            continue
        if file_date < start_date or file_date > end_date:
            continue
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        sources.append(
            {
                "date": file_date.strftime("%Y-%m-%d"),
                "total_posts_scanned": int(payload.get("total_posts_scanned", 0)),
                "posts": read_posts(payload),
            }
        )
    return sources


def date_from_path(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d")
    except ValueError:
        return None


def read_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    posts_value: Any = payload.get("posts", [])
    if not isinstance(posts_value, list):
        return []
    posts: list[dict[str, Any]] = [post for post in posts_value if isinstance(post, dict)]
    return posts


def build_weekly_lines(date_label: str, sources: list[WeeklySource]) -> list[str]:
    all_posts: list[dict[str, Any]] = [post for source in sources for post in source["posts"]]
    qualified_posts: list[dict[str, Any]] = [post for post in all_posts if bool(post.get("is_qualified"))]
    high_posts: list[dict[str, Any]] = [
        post for post in qualified_posts if str(post.get("founder_relevance", "")) == "high"
    ]
    total_posts_scanned: int = sum(source["total_posts_scanned"] for source in sources)
    lines: list[str] = [
        f"# Reddit Pain Radar Weekly - {date_label}",
        "",
        "## Summary",
        f"- Total posts scanned: {total_posts_scanned}",
        f"- Total qualified pain signals: {len(qualified_posts)}",
        f"- High relevance count: {len(high_posts)}",
        f"- Processed days included: {len(sources)}",
        "",
        "## Top Pain Categories",
        *counter_lines(category_counts(qualified_posts)),
        "",
        "## Top Subreddits",
        *counter_lines(subreddit_counts(qualified_posts)),
        "",
        "## Repeated Pain Themes",
        *counter_lines(theme_counts(qualified_posts)),
        "",
        "## Top 10 Research Leads From The Week",
        *research_lead_lines(high_posts),
        "",
    ]
    return lines


def category_counts(posts: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for post in posts:
        categories_value: Any = post.get("pain_categories", [])
        if isinstance(categories_value, list):
            counts.update(str(category) for category in categories_value)
    return counts


def subreddit_counts(posts: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter(str(post.get("subreddit", "unknown")) for post in posts)
    return counts


def theme_counts(posts: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for post in posts:
        title: str = str(post.get("title", ""))
        tokens: list[str] = title_keywords(title)
        categories_value: Any = post.get("pain_categories", [])
        if isinstance(categories_value, list):
            tokens = [*tokens, *[str(category) for category in categories_value]]
        counts.update(set(tokens))
    return Counter({theme: count for theme, count in counts.items() if count >= 2})


def title_keywords(title: str) -> list[str]:
    lowered: str = title.lower()
    tokens: list[str] = re.findall(r"[a-z][a-z0-9_]{3,}", lowered)
    keywords: list[str] = [token for token in tokens if token not in STOPWORDS]
    return keywords


def counter_lines(counts: Counter[str]) -> list[str]:
    if not counts:
        return ["- None"]
    lines: list[str] = [f"- {label}: {count}" for label, count in counts.most_common(10)]
    return lines


def research_lead_lines(high_posts: list[dict[str, Any]]) -> list[str]:
    sorted_posts: list[dict[str, Any]] = sorted(
        high_posts,
        key=lambda post: int(post.get("pain_score", 0)),
        reverse=True,
    )
    if not sorted_posts:
        return ["No high relevance research leads found this week."]
    lines: list[str] = []
    for index, post in enumerate(sorted_posts[:10], start=1):
        categories: str = ", ".join(post_categories(post))
        lines.extend(
            [
                f"{index}. {post.get('title', 'Untitled')}",
                f"   - Subreddit: r/{post.get('subreddit', 'unknown')}",
                f"   - Pain score: {post.get('pain_score', 0)}",
                f"   - Pain categories: {categories}",
                f"   - Why it matters: {post.get('why_it_matters', '')}",
                f"   - Link: {post.get('link', '')}",
                "",
            ]
        )
    return lines


def post_categories(post: dict[str, Any]) -> list[str]:
    categories_value: Any = post.get("pain_categories", [])
    if not isinstance(categories_value, list):
        return []
    categories: list[str] = [str(category) for category in categories_value]
    return categories
