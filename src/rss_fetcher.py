from __future__ import annotations

import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

import feedparser
import requests


USER_AGENT: str = "reddit-pain-radar/0.1 by personal-researcher contact: local-only"
REQUEST_TIMEOUT_SECONDS: int = 20
CACHE_MAX_AGE_HOURS: int = 6


class FetchSettings(TypedDict):
    base_delay_seconds: int
    jitter_min_seconds: int
    jitter_max_seconds: int
    max_retries: int
    retry_base_seconds: int


class RawEntry(TypedDict):
    title: str
    link: str
    published: str
    author: str
    summary: str
    subreddit: str
    fetched_at: str


class FetchError(TypedDict):
    subreddit: str
    url: str
    status_code: int | None
    response_body: str
    error: str


class FeedResult(TypedDict):
    subreddit: str
    url: str
    status: Literal["success", "cached", "failed"]


class FetchSummary(TypedDict):
    subreddits_attempted: int
    successful_feeds: int
    cached_feeds_used: int
    failed_feeds: int


class FetchResult(TypedDict):
    entries: list[RawEntry]
    errors: list[FetchError]
    feed_results: list[FeedResult]
    summary: FetchSummary


class SubredditFetchResult(TypedDict):
    entries: list[RawEntry]
    errors: list[FetchError]
    feed_result: FeedResult


def fetch_subreddits(subreddits: list[str], settings: FetchSettings, cache_dir: Path) -> FetchResult:
    entries: list[RawEntry] = []
    errors: list[FetchError] = []
    feed_results: list[FeedResult] = []
    total_subreddits: int = len(subreddits)
    for index, subreddit in enumerate(subreddits):
        result: SubredditFetchResult = fetch_subreddit(subreddit, settings, cache_dir)
        entries = [*entries, *result["entries"]]
        errors = [*errors, *result["errors"]]
        feed_results = [*feed_results, result["feed_result"]]
        if index < total_subreddits - 1 and result["feed_result"]["status"] != "cached":
            sleep_seconds: int = polite_delay_seconds(settings)
            print_warning({"event": "rss_polite_delay", "subreddit": subreddit, "sleep_seconds": sleep_seconds})
            time.sleep(sleep_seconds)
    summary: FetchSummary = build_fetch_summary(total_subreddits, feed_results)
    return {"entries": entries, "errors": errors, "feed_results": feed_results, "summary": summary}


def fetch_subreddit(subreddit: str, settings: FetchSettings, cache_dir: Path) -> SubredditFetchResult:
    url: str = f"https://www.reddit.com/r/{subreddit}/new/.rss"
    cache_path: Path = cache_file_path(cache_dir, subreddit)
    cached_text: str | None = read_fresh_cache(cache_path)
    if cached_text is not None:
        entries, errors = parse_rss_text(cached_text, subreddit, url)
        feed_result: FeedResult = {"subreddit": subreddit, "url": url, "status": "cached"}
        return {"entries": entries, "errors": errors, "feed_result": feed_result}

    response_text, fetch_error = fetch_rss_text_with_retries(subreddit, url, settings)
    if response_text is None:
        if fetch_error is None:
            raise RuntimeError(f"RSS fetch failed without error context: subreddit={subreddit} url={url}")
        failed_result: FeedResult = {"subreddit": subreddit, "url": url, "status": "failed"}
        return {"entries": [], "errors": [fetch_error], "feed_result": failed_result}

    write_cache(cache_path, response_text)
    entries, errors = parse_rss_text(response_text, subreddit, url)
    status: Literal["success", "failed"] = "failed" if errors else "success"
    feed_result = {"subreddit": subreddit, "url": url, "status": status}
    return {"entries": entries, "errors": errors, "feed_result": feed_result}


def parse_rss_text(response_text: str, subreddit: str, url: str) -> tuple[list[RawEntry], list[FetchError]]:
    parsed_feed: Any = feedparser.parse(response_text)
    if getattr(parsed_feed, "bozo", False):
        bozo_exception: object = getattr(parsed_feed, "bozo_exception", "unknown RSS parse error")
        fetch_error: FetchError = {
            "subreddit": subreddit,
            "url": url,
            "status_code": None,
            "response_body": "",
            "error": str(bozo_exception),
        }
        print_warning(
            {
                "event": "rss_parse_failed",
                "subreddit": subreddit,
                "url": url,
                "error": str(bozo_exception),
            }
        )
        return [], [fetch_error]

    fetched_at: str = datetime.now(timezone.utc).isoformat()
    raw_entries: list[RawEntry] = [entry_to_raw_entry(entry, subreddit, fetched_at) for entry in parsed_feed.entries]
    return raw_entries, []


def fetch_rss_text_with_retries(subreddit: str, url: str, settings: FetchSettings) -> tuple[str | None, FetchError | None]:
    last_error: FetchError | None = None
    for attempt in range(1, settings["max_retries"] + 1):
        try:
            response: requests.Response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.text, None
        except requests.RequestException as error:
            status_code: int | None = response_status_code(error)
            response_body: str = response_text_excerpt(error)
            last_error = build_fetch_error(subreddit, url, status_code, response_body, str(error))
            print_warning(
                {
                    "event": "rss_fetch_retry",
                    "subreddit": subreddit,
                    "url": url,
                    "attempt": attempt,
                    "max_retries": settings["max_retries"],
                    "status_code": status_code,
                    "response_body": response_body,
                    "error": str(error),
                }
            )
            if attempt < settings["max_retries"]:
                sleep_seconds: int = retry_delay_seconds(error, attempt, settings)
                print_warning(
                    {
                        "event": "rss_retry_delay",
                        "subreddit": subreddit,
                        "url": url,
                        "attempt": attempt,
                        "sleep_seconds": sleep_seconds,
                    }
                )
                time.sleep(sleep_seconds)
    print_warning(
        {
            "event": "rss_fetch_failed",
            "subreddit": subreddit,
            "url": url,
            "attempts": settings["max_retries"],
        }
    )
    return None, last_error


def build_fetch_error(subreddit: str, url: str, status_code: int | None, response_body: str, error: str) -> FetchError:
    fetch_error: FetchError = {
        "subreddit": subreddit,
        "url": url,
        "status_code": status_code,
        "response_body": response_body,
        "error": error,
    }
    return fetch_error


def response_status_code(error: requests.RequestException) -> int | None:
    response: requests.Response | None = error.response
    if response is None:
        return None
    return response.status_code


def response_text_excerpt(error: requests.RequestException) -> str:
    response: requests.Response | None = error.response
    if response is None:
        return ""
    text: str = response.text.replace("\r", " ").replace("\n", " ").strip()
    return text[:300]


def retry_delay_seconds(error: requests.RequestException, attempt: int, settings: FetchSettings) -> int:
    response: requests.Response | None = error.response
    if response is None:
        return backoff_delay_seconds(attempt, settings)
    retry_after: str | None = response.headers.get("Retry-After")
    if response.status_code == 429 and retry_after is None:
        return backoff_delay_seconds(attempt, settings)
    if retry_after is None or not retry_after.isdigit():
        return backoff_delay_seconds(attempt, settings)
    return int(retry_after)


def backoff_delay_seconds(attempt: int, settings: FetchSettings) -> int:
    return settings["retry_base_seconds"] * attempt + jitter_seconds(settings)


def polite_delay_seconds(settings: FetchSettings) -> int:
    return settings["base_delay_seconds"] + jitter_seconds(settings)


def jitter_seconds(settings: FetchSettings) -> int:
    return random.randint(settings["jitter_min_seconds"], settings["jitter_max_seconds"])


def read_fresh_cache(cache_path: Path) -> str | None:
    if not cache_path.exists():
        return None
    modified_at: datetime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
    cache_age: timedelta = datetime.now(timezone.utc) - modified_at
    if cache_age > timedelta(hours=CACHE_MAX_AGE_HOURS):
        return None
    return cache_path.read_text(encoding="utf-8")


def write_cache(cache_path: Path, response_text: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(response_text, encoding="utf-8")


def cache_file_path(cache_dir: Path, subreddit: str) -> Path:
    safe_name: str = re.sub(r"[^A-Za-z0-9_-]", "_", subreddit)
    return cache_dir / f"{safe_name}.xml"


def build_fetch_summary(total_subreddits: int, feed_results: list[FeedResult]) -> FetchSummary:
    successful_feeds: int = sum(1 for result in feed_results if result["status"] == "success")
    cached_feeds_used: int = sum(1 for result in feed_results if result["status"] == "cached")
    failed_feeds: int = sum(1 for result in feed_results if result["status"] == "failed")
    summary: FetchSummary = {
        "subreddits_attempted": total_subreddits,
        "successful_feeds": successful_feeds,
        "cached_feeds_used": cached_feeds_used,
        "failed_feeds": failed_feeds,
    }
    return summary


def entry_to_raw_entry(entry: Any, subreddit: str, fetched_at: str) -> RawEntry:
    summary: str = str(getattr(entry, "summary", "") or getattr(entry, "description", ""))
    raw_entry: RawEntry = {
        "title": str(getattr(entry, "title", "")),
        "link": str(getattr(entry, "link", "")),
        "published": str(getattr(entry, "published", "")),
        "author": str(getattr(entry, "author", "")),
        "summary": summary,
        "subreddit": subreddit,
        "fetched_at": fetched_at,
    }
    return raw_entry


def print_warning(fields: dict[str, object]) -> None:
    print(f"warning {fields}", file=sys.stderr)
