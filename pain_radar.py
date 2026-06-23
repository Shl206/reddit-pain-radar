from __future__ import annotations

import argparse
import importlib
import math
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, TypedDict


PAIN_KEYWORDS: tuple[str, ...] = (
    "hate",
    "frustrated",
    "frustrating",
    "annoying",
    "painful",
    "struggle",
    "struggling",
    "can't find",
    "cannot find",
    "tired of",
    "too expensive",
    "takes too long",
    "manual",
    "spreadsheet",
    "workaround",
    "alternative to",
    "is there a tool",
    "how do you manage",
    "anyone know",
    "i wish",
    "problem with",
    "hard to",
    "waste time",
    "overwhelmed",
    "no good solution",
    "looking for a tool",
    "automate",
    "repetitive",
    "tedious",
)

URGENCY_KEYWORDS: tuple[str, ...] = (
    "money",
    "expensive",
    "cost",
    "pricing",
    "invoice",
    "client",
    "customer",
    "hours",
    "time",
    "manual",
    "spreadsheet",
    "admin",
    "repetitive",
    "tedious",
)

TOOL_KEYWORDS: tuple[str, ...] = (
    "tool",
    "software",
    "app",
    "platform",
    "alternative",
    "automate",
    "integration",
    "dashboard",
    "workflow",
    "template",
    "script",
)


class Config(TypedDict):
    subreddits: list[str]
    limit: int
    comments: int
    sorts: list[str]
    min_score: float
    report_dir: Path
    db_path: Path
    retention_hours: int
    dry_run_config: bool


class Credentials(TypedDict):
    client_id: str
    client_secret: str
    user_agent: str


class PostRecord(TypedDict):
    id: str
    subreddit: str
    title: str
    selftext_excerpt: str
    score: int
    num_comments: int
    created_utc: float
    permalink: str
    url: str
    sort_source: str
    collected_at: str


class CommentRecord(TypedDict):
    id: str
    post_id: str
    body_excerpt: str
    score: int
    created_utc: float
    permalink: str
    collected_at: str


class PainItem(TypedDict):
    source_type: str
    source_id: str
    post_id: str
    subreddit: str
    text_excerpt: str
    pain_score: float
    matched_keywords: str
    permalink: str
    created_utc: float
    collected_at: str


class Cluster(TypedDict):
    title: str
    score: float
    items: list[PainItem]
    representative_text: str
    representative_index: int


class RunResult(TypedDict):
    posts_collected: int
    comments_collected: int
    pain_items_found: int
    report_path: Path
    clusters: list[Cluster]


class MissingCredentialsError(RuntimeError):
    pass


class MissingDependencyError(RuntimeError):
    pass


class RedditCollectionError(RuntimeError):
    pass


def parse_args(argv: list[str]) -> Config:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Find repeated pain points from Reddit posts and comments."
    )
    parser.add_argument(
        "--subreddits",
        default="SaaS,startups",
        help="Comma-separated subreddit names, for example SaaS,startups",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Posts per subreddit per sort.",
    )
    parser.add_argument(
        "--comments",
        type=int,
        default=3,
        help="Max top-level comments per post.",
    )
    parser.add_argument(
        "--sorts",
        default="hot,new",
        help="Comma-separated sorts: hot,new,top_week.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=8.0,
        help="Minimum pain score to save.",
    )
    parser.add_argument(
        "--report-dir",
        default="reports",
        help="Directory for Markdown reports.",
    )
    parser.add_argument(
        "--db",
        default="data/pain_radar.sqlite",
        help="SQLite database path.",
    )
    parser.add_argument(
        "--retention-hours",
        type=int,
        default=48,
        help="Hours to retain raw post/comment excerpts before redaction.",
    )
    parser.add_argument(
        "--dry-run-config",
        action="store_true",
        help="Print request, storage, and retention settings without calling Reddit.",
    )
    namespace: argparse.Namespace = parser.parse_args(argv)
    subreddits: list[str] = parse_csv(namespace.subreddits)
    sorts: list[str] = parse_csv(namespace.sorts)
    validate_config_values(
        subreddits,
        namespace.limit,
        namespace.comments,
        sorts,
        namespace.min_score,
        namespace.retention_hours,
    )
    config: Config = {
        "subreddits": subreddits,
        "limit": namespace.limit,
        "comments": namespace.comments,
        "sorts": sorts,
        "min_score": namespace.min_score,
        "report_dir": Path(namespace.report_dir),
        "db_path": Path(namespace.db),
        "retention_hours": namespace.retention_hours,
        "dry_run_config": namespace.dry_run_config,
    }
    return config


def parse_csv(value: str) -> list[str]:
    items: list[str] = [item.strip() for item in value.split(",") if item.strip()]
    return items


def validate_config_values(
    subreddits: list[str],
    limit: int,
    comments: int,
    sorts: list[str],
    min_score: float,
    retention_hours: int,
) -> None:
    allowed_sorts: set[str] = {"hot", "new", "top_week"}
    invalid_sorts: list[str] = [sort for sort in sorts if sort not in allowed_sorts]
    if not subreddits:
        raise ValueError("--subreddits must include at least one subreddit.")
    if limit < 1:
        raise ValueError("--limit must be at least 1.")
    if comments < 0:
        raise ValueError("--comments must be 0 or greater.")
    if not sorts:
        raise ValueError("--sorts must include at least one sort.")
    if invalid_sorts:
        raise ValueError(f"--sorts contains unsupported values: {', '.join(invalid_sorts)}")
    if min_score < 0:
        raise ValueError("--min-score must be 0 or greater.")
    if retention_hours < 1:
        raise ValueError("--retention-hours must be at least 1.")


def load_credentials() -> Credentials:
    load_dotenv_if_available()
    client_id: str = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user_agent: str = os.getenv("REDDIT_USER_AGENT", "").strip()
    warn_about_user_agent(user_agent)
    missing_names: list[str] = [
        name
        for name, value in (
            ("REDDIT_CLIENT_ID", client_id),
            ("REDDIT_CLIENT_SECRET", client_secret),
            ("REDDIT_USER_AGENT", user_agent),
        )
        if not value
    ]
    if missing_names:
        raise MissingCredentialsError(", ".join(missing_names))
    credentials: Credentials = {
        "client_id": client_id,
        "client_secret": client_secret,
        "user_agent": user_agent,
    }
    return credentials


def load_dotenv_if_available() -> None:
    try:
        dotenv_module: Any = importlib.import_module("dotenv")
    except ModuleNotFoundError:
        return
    dotenv_module.load_dotenv()


def warn_about_user_agent(user_agent: str) -> None:
    warnings: list[str] = user_agent_warnings(user_agent)
    for warning in warnings:
        print_warning({"event": "user_agent_warning", "warning": warning})


def user_agent_warnings(user_agent: str) -> list[str]:
    normalized_user_agent: str = user_agent.strip().lower()
    warnings: list[str] = []
    if not normalized_user_agent:
        warnings.append("REDDIT_USER_AGENT is missing; use an app-specific value like reddit-pain-radar/0.1 (by /u/your_username).")
        return warnings
    generic_values: set[str] = {"python", "praw", "bot", "script", "test", "useragent", "reddit-pain-radar"}
    if normalized_user_agent in generic_values or len(normalized_user_agent) < 16:
        warnings.append("REDDIT_USER_AGENT looks generic; use an app-specific value.")
    if "(by /u/" not in user_agent:
        warnings.append('REDDIT_USER_AGENT should identify the Reddit account and contain "(by /u/".')
    return warnings


def create_reddit_client(credentials: Credentials) -> Any:
    try:
        praw_module: Any = importlib.import_module("praw")
    except ModuleNotFoundError:
        raise MissingDependencyError("praw")
    reddit: Any = praw_module.Reddit(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        user_agent=credentials["user_agent"],
        check_for_async=False,
    )
    reddit.read_only = True
    return reddit


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection: sqlite3.Connection = sqlite3.connect(db_path)
    return connection


def create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            subreddit TEXT,
            title TEXT,
            selftext_excerpt TEXT,
            score INTEGER,
            num_comments INTEGER,
            created_utc REAL,
            permalink TEXT,
            url TEXT,
            sort_source TEXT,
            collected_at TEXT
        );

        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            post_id TEXT,
            body_excerpt TEXT,
            score INTEGER,
            created_utc REAL,
            permalink TEXT,
            collected_at TEXT
        );

        CREATE TABLE IF NOT EXISTS pain_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT,
            source_id TEXT,
            post_id TEXT,
            subreddit TEXT,
            text_excerpt TEXT,
            pain_score REAL,
            matched_keywords TEXT,
            permalink TEXT,
            created_utc REAL,
            collected_at TEXT
        );
        """
    )
    connection.commit()


def redact_expired_raw_content(connection: sqlite3.Connection, retention_hours: int, now: datetime) -> None:
    cutoff: str = (now - timedelta(hours=retention_hours)).isoformat()
    post_cursor: sqlite3.Cursor = connection.execute(
        """
        UPDATE posts
        SET title = '', selftext_excerpt = ''
        WHERE collected_at < ?
          AND (title != '' OR selftext_excerpt != '');
        """,
        (cutoff,),
    )
    comment_cursor: sqlite3.Cursor = connection.execute(
        """
        UPDATE comments
        SET body_excerpt = ''
        WHERE collected_at < ?
          AND body_excerpt != '';
        """,
        (cutoff,),
    )
    pain_cursor: sqlite3.Cursor = connection.execute(
        """
        UPDATE pain_items
        SET text_excerpt = ''
        WHERE collected_at < ?
          AND text_excerpt != '';
        """,
        (cutoff,),
    )
    connection.commit()
    print_warning(
        {
            "event": "retention_redaction",
            "retention_hours": retention_hours,
            "cutoff": cutoff,
            "posts_redacted": post_cursor.rowcount,
            "comments_redacted": comment_cursor.rowcount,
            "pain_items_redacted": pain_cursor.rowcount,
        }
    )


def collect_posts_and_comments(reddit: Any, config: Config, collected_at: str) -> tuple[list[PostRecord], list[CommentRecord]]:
    posts_by_id: dict[str, PostRecord] = {}
    comments_by_id: dict[str, CommentRecord] = {}
    for subreddit_name in config["subreddits"]:
        for sort_name in config["sorts"]:
            submissions: list[Any] = fetch_submissions_with_retries(
                reddit,
                subreddit_name,
                sort_name,
                config["limit"],
            )
            for submission in submissions:
                post_id: str = str(submission.id)
                if post_id in posts_by_id:
                    continue
                post_record: PostRecord = submission_to_post_record(submission, sort_name, collected_at)
                posts_by_id[post_id] = post_record
                comment_records: list[CommentRecord] = collect_top_level_comments(
                    reddit,
                    submission,
                    config["comments"],
                    collected_at,
                )
                for comment_record in comment_records:
                    comments_by_id[comment_record["id"]] = comment_record
    posts: list[PostRecord] = list(posts_by_id.values())
    comments: list[CommentRecord] = list(comments_by_id.values())
    return posts, comments


def fetch_submissions_with_retries(reddit: Any, subreddit_name: str, sort_name: str, limit: int) -> list[Any]:
    try:
        prawcore_module: Any = importlib.import_module("prawcore")
    except ModuleNotFoundError:
        raise MissingDependencyError("prawcore")
    max_attempts: int = 2
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            subreddit: Any = reddit.subreddit(subreddit_name)
            submissions: list[Any] = list(get_submission_listing(subreddit, sort_name, limit))
            log_rate_limit_info(reddit, f"listing:{subreddit_name}:{sort_name}")
            sleep_if_rate_limit_low(reddit)
            return submissions
        except prawcore_module.exceptions.PrawcoreException as error:
            last_error = error
            print_warning(
                {
                    "event": "reddit_api_retry",
                    "subreddit": subreddit_name,
                    "sort": sort_name,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            time.sleep(float(attempt))
    raise RedditCollectionError(
        f"Reddit API failed after {max_attempts} attempts for subreddit={subreddit_name} sort={sort_name}: {last_error}"
    ) from last_error


def get_submission_listing(subreddit: Any, sort_name: str, limit: int) -> Iterable[Any]:
    if sort_name == "hot":
        return subreddit.hot(limit=limit)
    if sort_name == "new":
        return subreddit.new(limit=limit)
    if sort_name == "top_week":
        return subreddit.top(time_filter="week", limit=limit)
    raise ValueError(f"Unsupported sort: {sort_name}")


def submission_to_post_record(submission: Any, sort_name: str, collected_at: str) -> PostRecord:
    record: PostRecord = {
        "id": str(submission.id),
        "subreddit": str(submission.subreddit.display_name),
        "title": str(submission.title or ""),
        "selftext_excerpt": excerpt(str(submission.selftext or ""), 700),
        "score": int(submission.score or 0),
        "num_comments": int(submission.num_comments or 0),
        "created_utc": float(submission.created_utc or 0.0),
        "permalink": reddit_permalink(str(submission.permalink or "")),
        "url": str(submission.url or ""),
        "sort_source": sort_name,
        "collected_at": collected_at,
    }
    return record


def collect_top_level_comments(reddit: Any, submission: Any, max_comments: int, collected_at: str) -> list[CommentRecord]:
    if max_comments == 0:
        return []
    records: list[CommentRecord] = []
    for comment in submission.comments:
        if len(records) >= max_comments:
            break
        if not has_comment_fields(comment):
            continue
        record: CommentRecord = {
            "id": str(comment.id),
            "post_id": str(submission.id),
            "body_excerpt": excerpt(str(comment.body or ""), 500),
            "score": int(comment.score or 0),
            "created_utc": float(comment.created_utc or 0.0),
            "permalink": reddit_permalink(str(comment.permalink or "")),
            "collected_at": collected_at,
        }
        records.append(record)
    log_rate_limit_info(reddit, f"comments:{submission.id}")
    sleep_if_rate_limit_low(reddit)
    return records


def log_rate_limit_info(reddit: Any, context: str) -> None:
    limits: dict[str, Any] | None = get_rate_limit_info(reddit)
    if limits is None:
        return
    print_warning(
        {
            "event": "reddit_rate_limit",
            "context": context,
            "remaining": limits.get("remaining"),
            "used": limits.get("used"),
            "reset_timestamp": limits.get("reset_timestamp"),
        }
    )


def sleep_if_rate_limit_low(reddit: Any) -> None:
    limits: dict[str, Any] | None = get_rate_limit_info(reddit)
    if limits is None:
        return
    remaining_value: Any = limits.get("remaining")
    reset_timestamp_value: Any = limits.get("reset_timestamp")
    if not isinstance(remaining_value, float | int):
        return
    if remaining_value > 10:
        return
    sleep_seconds: float = rate_limit_sleep_seconds(float(remaining_value), reset_timestamp_value)
    print_warning(
        {
            "event": "reddit_rate_limit_backoff",
            "remaining": remaining_value,
            "sleep_seconds": sleep_seconds,
        }
    )
    time.sleep(sleep_seconds)


def get_rate_limit_info(reddit: Any) -> dict[str, Any] | None:
    auth: Any = getattr(reddit, "auth", None)
    if auth is None:
        return None
    limits: Any = getattr(auth, "limits", None)
    if not isinstance(limits, dict):
        return None
    return limits


def rate_limit_sleep_seconds(remaining: float, reset_timestamp: Any) -> float:
    if remaining <= 2 and isinstance(reset_timestamp, float | int):
        seconds_until_reset: float = max(float(reset_timestamp) - time.time(), 0.0)
        return min(max(seconds_until_reset, 5.0), 60.0)
    return 2.0


def has_comment_fields(comment: Any) -> bool:
    required_fields: tuple[str, ...] = ("id", "body", "score", "created_utc", "permalink")
    result: bool = all(hasattr(comment, field_name) for field_name in required_fields)
    return result


def reddit_permalink(path_or_url: str) -> str:
    if path_or_url.startswith("https://"):
        return path_or_url
    if path_or_url.startswith("/"):
        return f"https://www.reddit.com{path_or_url}"
    return path_or_url


def excerpt(text: str, max_chars: int) -> str:
    compact: str = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    clipped: str = compact[: max_chars - 1].rstrip()
    return f"{clipped}..."


def upsert_posts(connection: sqlite3.Connection, posts: list[PostRecord]) -> None:
    rows: list[tuple[str, str, str, str, int, int, float, str, str, str, str]] = [
        (
            post["id"],
            post["subreddit"],
            post["title"],
            post["selftext_excerpt"],
            post["score"],
            post["num_comments"],
            post["created_utc"],
            post["permalink"],
            post["url"],
            post["sort_source"],
            post["collected_at"],
        )
        for post in posts
    ]
    connection.executemany(
        """
        INSERT OR REPLACE INTO posts (
            id, subreddit, title, selftext_excerpt, score, num_comments,
            created_utc, permalink, url, sort_source, collected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    connection.commit()


def upsert_comments(connection: sqlite3.Connection, comments: list[CommentRecord]) -> None:
    rows: list[tuple[str, str, str, int, float, str, str]] = [
        (
            comment["id"],
            comment["post_id"],
            comment["body_excerpt"],
            comment["score"],
            comment["created_utc"],
            comment["permalink"],
            comment["collected_at"],
        )
        for comment in comments
    ]
    connection.executemany(
        """
        INSERT OR REPLACE INTO comments (
            id, post_id, body_excerpt, score, created_utc, permalink, collected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    connection.commit()


def create_pain_items(
    posts: list[PostRecord],
    comments: list[CommentRecord],
    min_score: float,
    collected_at: str,
) -> list[PainItem]:
    post_by_id: dict[str, PostRecord] = {post["id"]: post for post in posts}
    items: list[PainItem] = []
    for post in posts:
        post_text: str = f"{post['title']}\n\n{post['selftext_excerpt']}".strip()
        post_item: PainItem | None = score_text_as_pain_item(
            "post",
            post["id"],
            post["id"],
            post["subreddit"],
            post_text,
            post["score"],
            post["num_comments"],
            post["permalink"],
            post["created_utc"],
            collected_at,
            min_score,
        )
        if post_item is not None:
            items.append(post_item)
    for comment in comments:
        parent_post: PostRecord | None = post_by_id.get(comment["post_id"])
        if parent_post is None:
            continue
        comment_item: PainItem | None = score_text_as_pain_item(
            "comment",
            comment["id"],
            comment["post_id"],
            parent_post["subreddit"],
            comment["body_excerpt"],
            comment["score"],
            parent_post["num_comments"],
            comment["permalink"],
            comment["created_utc"],
            collected_at,
            min_score,
        )
        if comment_item is not None:
            items.append(comment_item)
    return items


def score_text_as_pain_item(
    source_type: str,
    source_id: str,
    post_id: str,
    subreddit: str,
    text: str,
    reddit_score: int,
    num_comments: int,
    permalink: str,
    created_utc: float,
    collected_at: str,
    min_score: float,
) -> PainItem | None:
    matched_keywords: list[str] = find_matched_keywords(text, PAIN_KEYWORDS)
    pain_score: float = calculate_pain_score(text, reddit_score, num_comments, matched_keywords)
    if pain_score < min_score:
        return None
    item: PainItem = {
        "source_type": source_type,
        "source_id": source_id,
        "post_id": post_id,
        "subreddit": subreddit,
        "text_excerpt": excerpt(text, 500),
        "pain_score": pain_score,
        "matched_keywords": ", ".join(matched_keywords),
        "permalink": permalink,
        "created_utc": created_utc,
        "collected_at": collected_at,
    }
    return item


def find_matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    normalized_text: str = normalize_for_matching(text)
    matched: list[str] = [keyword for keyword in keywords if keyword in normalized_text]
    return matched


def normalize_for_matching(text: str) -> str:
    lowered: str = text.lower()
    normalized: str = re.sub(r"\s+", " ", lowered).strip()
    return normalized


def calculate_pain_score(text: str, reddit_score: int, num_comments: int, matched_keywords: list[str]) -> float:
    normalized_text: str = normalize_for_matching(text)
    base: int = len(matched_keywords) * 3
    engagement: float = math.log(max(reddit_score, 0) + 1) + math.log(max(num_comments, 0) + 1)
    urgency_boost: int = 3 if contains_any_keyword(normalized_text, URGENCY_KEYWORDS) else 0
    tool_boost: int = 4 if contains_any_keyword(normalized_text, TOOL_KEYWORDS) else 0
    question_boost: int = 2 if "?" in text and matched_keywords else 0
    final_score: float = base + engagement + urgency_boost + tool_boost + question_boost
    return final_score


def contains_any_keyword(normalized_text: str, keywords: tuple[str, ...]) -> bool:
    result: bool = any(keyword in normalized_text for keyword in keywords)
    return result


def replace_pain_items(connection: sqlite3.Connection, pain_items: list[PainItem]) -> None:
    source_keys: list[tuple[str, str]] = [
        (
            item["source_type"],
            item["source_id"],
        )
        for item in pain_items
    ]
    connection.executemany(
        "DELETE FROM pain_items WHERE source_type = ? AND source_id = ?;",
        source_keys,
    )
    rows: list[tuple[str, str, str, str, str, float, str, str, float, str]] = [
        (
            item["source_type"],
            item["source_id"],
            item["post_id"],
            item["subreddit"],
            item["text_excerpt"],
            item["pain_score"],
            item["matched_keywords"],
            item["permalink"],
            item["created_utc"],
            item["collected_at"],
        )
        for item in pain_items
    ]
    connection.executemany(
        """
        INSERT INTO pain_items (
            source_type, source_id, post_id, subreddit, text_excerpt, pain_score,
            matched_keywords, permalink, created_utc, collected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    connection.commit()


def build_clusters(pain_items: list[PainItem]) -> list[Cluster]:
    sorted_items: list[PainItem] = sorted(pain_items, key=lambda item: item["pain_score"], reverse=True)
    if not sorted_items:
        return []
    clustering_dependencies: tuple[Any, Any] | None = load_clustering_dependencies()
    if clustering_dependencies is None:
        return build_fallback_clusters(sorted_items)
    vectorizer_type, similarity_function = clustering_dependencies
    texts: list[str] = [item["text_excerpt"] for item in sorted_items]
    try:
        vectorizer: Any = vectorizer_type(stop_words="english", max_features=2000)
        matrix: Any = vectorizer.fit_transform(texts)
    except ValueError:
        return build_fallback_clusters(sorted_items)
    clusters: list[Cluster] = []
    for item_index, item in enumerate(sorted_items):
        assigned_cluster: Cluster | None = find_matching_cluster(clusters, matrix, item_index, similarity_function)
        if assigned_cluster is None:
            clusters.append(
                {
                    "title": cluster_title(item["text_excerpt"]),
                    "score": item["pain_score"],
                    "items": [item],
                    "representative_text": item["text_excerpt"],
                    "representative_index": item_index,
                }
            )
        else:
            assigned_cluster["items"] = [*assigned_cluster["items"], item]
            assigned_cluster["score"] = assigned_cluster["score"] + item["pain_score"]
    top_clusters: list[Cluster] = sorted(clusters, key=lambda cluster: cluster["score"], reverse=True)[:10]
    return top_clusters


def load_clustering_dependencies() -> tuple[Any, Any] | None:
    try:
        vectorizer_module: Any = importlib.import_module("sklearn.feature_extraction.text")
        pairwise_module: Any = importlib.import_module("sklearn.metrics.pairwise")
    except ModuleNotFoundError:
        return None
    return vectorizer_module.TfidfVectorizer, pairwise_module.cosine_similarity


def find_matching_cluster(clusters: list[Cluster], matrix: Any, item_index: int, similarity_function: Any) -> Cluster | None:
    for cluster in clusters:
        similarity: float = float(similarity_function(matrix[item_index], matrix[cluster["representative_index"]])[0][0])
        if similarity >= 0.42:
            return cluster
    return None


def build_fallback_clusters(sorted_items: list[PainItem]) -> list[Cluster]:
    clusters: list[Cluster] = [
        {
            "title": cluster_title(item["text_excerpt"]),
            "score": item["pain_score"],
            "items": [item],
            "representative_text": item["text_excerpt"],
            "representative_index": index,
        }
        for index, item in enumerate(sorted_items[:10])
    ]
    return clusters


def cluster_title(text: str) -> str:
    cleaned: str = re.sub(r"[^A-Za-z0-9\s'?]", "", text).strip()
    words: list[str] = cleaned.split()
    if not words:
        return "Untitled pain signal"
    title: str = " ".join(words[:9])
    return title[0].upper() + title[1:]


def write_report(
    report_dir: Path,
    config: Config,
    clusters: list[Cluster],
    pain_items: list[PainItem],
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    today: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path: Path = report_dir / f"pain_points_{today}.md"
    lines: list[str] = build_report_lines(today, config, clusters, pain_items)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_report_lines(
    today: str,
    config: Config,
    clusters: list[Cluster],
    pain_items: list[PainItem],
) -> list[str]:
    lines: list[str] = [
        f"# Reddit Pain Radar - {today}",
        "",
        "## Run Config",
        f"- Subreddits: {', '.join(config['subreddits'])}",
        f"- Limit: {config['limit']}",
        f"- Comments per post: {config['comments']}",
        f"- Min score: {config['min_score']}",
        f"- Raw content retention: {config['retention_hours']} hours",
        "",
        "## Top Pain Clusters",
        "",
    ]
    if not clusters:
        lines.extend(["No pain clusters found with the current minimum score.", ""])
    for index, cluster in enumerate(clusters, start=1):
        representative: str = cluster["representative_text"]
        lines.extend(
            [
                f"### {index}. {cluster['title']}",
                f"- Cluster score: {cluster['score']:.2f}",
                f"- Repeated signal: {repeated_signal(cluster)}",
                f"- Target user guess: {target_user_guess(cluster)}",
                f"- Product angle: {product_angle(representative)}",
                f"- Validation question: Would you pay for a tool that helps you solve: {cluster['title']}?",
                "- Evidence:",
            ]
        )
        evidence_items: list[PainItem] = sorted(
            cluster["items"],
            key=lambda item: item["pain_score"],
            reverse=True,
        )[:5]
        for item in evidence_items:
            lines.append(
                f"  - r/{item['subreddit']}, score {item['pain_score']:.2f}, "
                f"{item['text_excerpt']} ({item['permalink']})"
            )
        lines.append("")
    lines.extend(["## Top Raw Pain Items", ""])
    top_items: list[PainItem] = sorted(pain_items, key=lambda item: item["pain_score"], reverse=True)[:20]
    if not top_items:
        lines.extend(["No raw pain items found with the current minimum score.", ""])
    for index, item in enumerate(top_items, start=1):
        lines.append(
            f"{index}. r/{item['subreddit']} | score {item['pain_score']:.2f} | "
            f"{item['text_excerpt']} | {item['permalink']}"
        )
    lines.append("")
    return lines


def repeated_signal(cluster: Cluster) -> str:
    keyword_counts: dict[str, int] = {}
    for item in cluster["items"]:
        keywords: list[str] = parse_csv(item["matched_keywords"])
        for keyword in keywords:
            keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
    sorted_keywords: list[tuple[str, int]] = sorted(keyword_counts.items(), key=lambda pair: pair[1], reverse=True)
    if sorted_keywords:
        top_keywords: list[str] = [keyword for keyword, count in sorted_keywords[:4]]
        return f"Repeated mentions of {', '.join(top_keywords)}."
    return excerpt(cluster["representative_text"], 160)


def target_user_guess(cluster: Cluster) -> str:
    combined_text: str = normalize_for_matching(
        " ".join([cluster["representative_text"], *[item["subreddit"] for item in cluster["items"]]])
    )
    if "saas" in combined_text or "startup" in combined_text or "founder" in combined_text:
        return "SaaS founder"
    if "freelance" in combined_text or "client" in combined_text:
        return "freelancer"
    if "smallbusiness" in combined_text or "small business" in combined_text:
        return "small business owner"
    if "developer" in combined_text or "api" in combined_text or "bug" in combined_text:
        return "developer"
    if "marketing" in combined_text or "content" in combined_text:
        return "marketer"
    if "ops" in combined_text or "operator" in combined_text or "workflow" in combined_text:
        return "operator"
    return "unknown"


def product_angle(text: str) -> str:
    normalized_text: str = normalize_for_matching(text)
    if contains_any_keyword(normalized_text, ("automate", "manual", "spreadsheet")):
        return "automation tool / workflow assistant"
    if contains_any_keyword(normalized_text, ("client", "invoice", "admin")):
        return "client ops or admin tool"
    if contains_any_keyword(normalized_text, ("content", "marketing")):
        return "marketing workflow tool"
    if contains_any_keyword(normalized_text, ("developer", "api", "bug")):
        return "developer tool"
    return "research further before productizing"


def print_warning(fields: dict[str, object]) -> None:
    print(f"warning {fields}", file=sys.stderr)


def print_missing_credentials_message(error: MissingCredentialsError) -> None:
    print("Missing Reddit API credentials.")
    print(f"Missing environment variables: {error}")
    print("")
    print("Setup steps:")
    print("1. Create a Reddit app at https://www.reddit.com/prefs/apps")
    print("2. Copy the client ID and client secret")
    print("3. Put them into a .env file with REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT")
    print("4. Re-run the command")


def print_missing_dependency_message(error: MissingDependencyError) -> None:
    print(f"Missing dependency: {error}")
    print("Install project dependencies with:")
    print("python -m pip install -r requirements.txt")


def print_dry_run_config(config: Config) -> None:
    estimated_listings: int = len(config["subreddits"]) * len(config["sorts"])
    estimated_posts_seen: int = estimated_listings * config["limit"]
    estimated_comment_fetches: int = estimated_posts_seen
    print("Dry run config")
    print(f"- subreddits: {', '.join(config['subreddits'])}")
    print(f"- sorts: {', '.join(config['sorts'])}")
    print(f"- limit: {config['limit']}")
    print(f"- comments per post: {config['comments']}")
    print(f"- estimated maximum listings requested: {estimated_listings} listings, up to {estimated_posts_seen} posts")
    print(f"- estimated maximum comment fetches: {estimated_comment_fetches}")
    print("- data stored: aggregate pain items, cluster summaries in reports, subreddit, timestamps, scores, permalinks, URLs, matched keywords, and short raw excerpts within retention window")
    print("- data not stored: usernames, votes you cast, private messages, training data, browser-scraped pages, or Reddit content beyond the retention window")
    print(f"- retention policy: raw post/comment/pain excerpts are redacted after {config['retention_hours']} hours on startup")


def print_summary(result: RunResult) -> None:
    print(f"posts collected: {result['posts_collected']}")
    print(f"comments collected: {result['comments_collected']}")
    print(f"pain items found: {result['pain_items_found']}")
    print(f"report path: {result['report_path']}")
    print("top clusters:")
    for cluster in result["clusters"]:
        print(f"- {cluster['title']} ({cluster['score']:.2f})")


def run(config: Config) -> RunResult:
    collected_at: str = datetime.now(timezone.utc).isoformat()
    connection: sqlite3.Connection = connect_db(config["db_path"])
    try:
        create_tables(connection)
        redact_expired_raw_content(connection, config["retention_hours"], datetime.now(timezone.utc))
        credentials: Credentials = load_credentials()
        reddit: Any = create_reddit_client(credentials)
        posts, comments = collect_posts_and_comments(reddit, config, collected_at)
        upsert_posts(connection, posts)
        upsert_comments(connection, comments)
        pain_items: list[PainItem] = create_pain_items(posts, comments, config["min_score"], collected_at)
        replace_pain_items(connection, pain_items)
    finally:
        connection.close()
    clusters: list[Cluster] = build_clusters(pain_items)
    report_path: Path = write_report(config["report_dir"], config, clusters, pain_items)
    result: RunResult = {
        "posts_collected": len(posts),
        "comments_collected": len(comments),
        "pain_items_found": len(pain_items),
        "report_path": report_path,
        "clusters": clusters,
    }
    return result


def main(argv: list[str]) -> int:
    try:
        config: Config = parse_args(argv)
        if config["dry_run_config"]:
            print_dry_run_config(config)
            return 0
        result: RunResult = run(config)
        print_summary(result)
        return 0
    except MissingCredentialsError as error:
        print_missing_credentials_message(error)
        return 1
    except MissingDependencyError as error:
        print_missing_dependency_message(error)
        return 1
    except RedditCollectionError as error:
        print(f"Reddit collection failed: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Invalid command: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
