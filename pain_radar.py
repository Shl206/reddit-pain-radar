from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from src.agent_memory import (
    MemorySearchResult,
    append_feedback,
    append_memory_impact,
    build_memory_context,
    load_recent_memories,
    memory_review_queue,
    memory_stats,
    save_trajectory,
    search_memory,
    summarize_trajectory,
    to_trajectory,
    Trajectory,
    update_memory_review,
)
from src.pain_scorer import ScoredPost, score_entries
from src.report_writer import write_report, write_research_notes
from src.rss_fetcher import FetchError, FetchSettings, FetchSummary, RawEntry, fetch_subreddits
from src.weekly_summary import generate_weekly_summary


SUBREDDITS_PATH: Path = Path("config/subreddits.txt")
PAIN_KEYWORDS_PATH: Path = Path("config/pain_keywords.txt")
SETTINGS_PATH: Path = Path("config/settings.json")
RAW_DATA_DIR: Path = Path("data/raw")
PROCESSED_DATA_DIR: Path = Path("data/processed")
CACHE_DIR: Path = Path("data/cache")
REPORTS_DIR: Path = Path("reports")
RESEARCH_NOTES_DIR: Path = Path("research_notes")
WEEKLY_REPORTS_DIR: Path = Path("weekly_reports")
DEFAULT_TASK_GOAL: str = "Find high-signal Reddit pain points and business opportunities."


CommandMode = Literal[
    "daily",
    "weekly",
    "memory_search",
    "memory_feedback",
    "memory_impact",
    "memory_stats",
    "memory_review",
    "memory_review_queue",
]


class RunPaths(TypedDict):
    raw_path: Path
    processed_path: Path
    report_path: Path
    research_note_path: Path


class ParsedCommand(TypedDict):
    mode: CommandMode
    task_goal: str
    use_memory: bool
    include_rejected_memory: bool
    memory_query: str
    feedback_run_id: str
    feedback_useful: bool
    feedback_rating: int
    feedback_note: str
    impact_run_id: str
    impact_helpful: bool | None
    impact_rating: int | None
    impact_influenced: str
    impact_avoided: str
    impact_improved: str
    impact_note: str
    review_run_id: str
    review_status: str
    review_tags: list[str]
    review_reason: str | None
    review_queue_status: str
    review_queue_limit: int


def main(argv: list[str]) -> int:
    parsed_command: ParsedCommand | None = parse_command(argv)
    if parsed_command is None:
        print(
            "Invalid command. Use no options, --weekly, --memory-search, --memory-feedback, "
            "--memory-impact, --memory-stats, --memory-review, or --memory-review-queue.",
            file=sys.stderr,
        )
        return 2

    date_label: str = datetime.now().strftime("%Y-%m-%d")
    ensure_directories([RAW_DATA_DIR, PROCESSED_DATA_DIR, CACHE_DIR, REPORTS_DIR, RESEARCH_NOTES_DIR, WEEKLY_REPORTS_DIR])
    if parsed_command["mode"] == "weekly":
        weekly_path: Path = generate_weekly_summary(PROCESSED_DATA_DIR, WEEKLY_REPORTS_DIR, date_label)
        print("Reddit Pain Radar weekly summary complete")
        print(f"- Weekly report path: {weekly_path}")
        return 0
    if parsed_command["mode"] == "memory_search":
        print_memory_search_results(parsed_command["memory_query"], parsed_command["include_rejected_memory"])
        return 0
    if parsed_command["mode"] == "memory_feedback":
        feedback_path: Path = append_feedback(
            parsed_command["feedback_run_id"],
            parsed_command["feedback_useful"],
            parsed_command["feedback_rating"],
            parsed_command["feedback_note"],
        )
        print("Agent memory feedback saved")
        print(f"- Feedback path: {feedback_path}")
        return 0
    if parsed_command["mode"] == "memory_impact":
        impact_path: Path = append_memory_impact_for_command(parsed_command, date_label)
        print("Agent memory impact saved")
        print(f"- Impact path: {impact_path}")
        return 0
    if parsed_command["mode"] == "memory_stats":
        print_memory_stats()
        return 0
    if parsed_command["mode"] == "memory_review_queue":
        print_memory_review_queue(parsed_command["review_queue_status"], parsed_command["review_queue_limit"])
        return 0
    if parsed_command["mode"] == "memory_review":
        review_path: Path = update_memory_review(
            parsed_command["review_run_id"],
            parsed_command["review_status"],
            parsed_command["review_tags"],
            parsed_command["review_reason"],
        )
        print("Agent memory review updated")
        print(f"- Memory path: {review_path}")
        return 0
    return run_daily(date_label, parsed_command["task_goal"], parsed_command["use_memory"])


def parse_command(argv: list[str]) -> ParsedCommand | None:
    if not argv:
        return empty_command("daily")
    if argv == ["--weekly"]:
        return empty_command("weekly")
    if argv == ["--memory-stats"]:
        return empty_command("memory_stats")
    if argv and argv[0] == "--memory-review-queue":
        return parse_review_queue_command(argv)
    if len(argv) in (2, 3) and argv[0] == "--memory-search":
        command: ParsedCommand = empty_command("memory_search")
        command["memory_query"] = argv[1]
        if len(argv) == 3:
            if argv[2] != "--include-rejected-memory":
                return None
            command["include_rejected_memory"] = True
        return command
    if len(argv) == 8 and argv[0] == "--memory-feedback":
        return parse_feedback_command(argv)
    if len(argv) >= 2 and argv[0] == "--memory-impact":
        return parse_impact_command(argv)
    if len(argv) >= 2 and argv[0] == "--memory-review":
        return parse_review_command(argv)
    daily_command: ParsedCommand | None = parse_daily_options(argv)
    if daily_command is not None:
        return daily_command
    return None


def empty_command(mode: CommandMode) -> ParsedCommand:
    command: ParsedCommand = {
        "mode": mode,
        "task_goal": DEFAULT_TASK_GOAL,
        "use_memory": False,
        "include_rejected_memory": False,
        "memory_query": "",
        "feedback_run_id": "",
        "feedback_useful": False,
        "feedback_rating": 0,
        "feedback_note": "",
        "impact_run_id": "",
        "impact_helpful": None,
        "impact_rating": None,
        "impact_influenced": "",
        "impact_avoided": "",
        "impact_improved": "",
        "impact_note": "",
        "review_run_id": "",
        "review_status": "pending_review",
        "review_tags": [],
        "review_reason": None,
        "review_queue_status": "pending_review",
        "review_queue_limit": 20,
    }
    return command


def parse_daily_options(argv: list[str]) -> ParsedCommand | None:
    command: ParsedCommand = empty_command("daily")
    index: int = 0
    while index < len(argv):
        option: str = argv[index]
        if option == "--use-memory":
            command["use_memory"] = True
            index = index + 1
            continue
        if option == "--task-goal":
            if index + 1 >= len(argv):
                return None
            command["task_goal"] = argv[index + 1]
            index = index + 2
            continue
        return None
    return command


def parse_review_queue_command(argv: list[str]) -> ParsedCommand | None:
    command: ParsedCommand = empty_command("memory_review_queue")
    index: int = 1
    while index < len(argv):
        option: str = argv[index]
        if index + 1 >= len(argv):
            return None
        value: str = argv[index + 1]
        if option == "--limit":
            try:
                limit: int = int(value)
            except ValueError:
                return None
            if limit < 1 or limit > 100:
                return None
            command["review_queue_limit"] = limit
        elif option == "--status":
            if value not in {"pending_review", "approved", "rejected", "gold", "all"}:
                return None
            command["review_queue_status"] = value
        else:
            return None
        index = index + 2
    return command


def parse_feedback_command(argv: list[str]) -> ParsedCommand | None:
    if argv[2] != "--useful" or argv[4] != "--rating" or argv[6] != "--note":
        return None
    useful_value: bool | None = parse_bool(argv[3])
    if useful_value is None:
        return None
    try:
        rating: int = int(argv[5])
    except ValueError:
        return None
    command: ParsedCommand = empty_command("memory_feedback")
    command["feedback_run_id"] = argv[1]
    command["feedback_useful"] = useful_value
    command["feedback_rating"] = rating
    command["feedback_note"] = argv[7]
    return command


def parse_impact_command(argv: list[str]) -> ParsedCommand | None:
    command: ParsedCommand = empty_command("memory_impact")
    command["impact_run_id"] = argv[1]
    index: int = 2
    while index < len(argv):
        option: str = argv[index]
        if index + 1 >= len(argv):
            return None
        value: str = argv[index + 1]
        if option == "--helpful":
            helpful_value: bool | None = parse_bool(value)
            if helpful_value is None:
                return None
            command["impact_helpful"] = helpful_value
        elif option == "--rating":
            try:
                command["impact_rating"] = int(value)
            except ValueError:
                return None
        elif option == "--influenced":
            command["impact_influenced"] = value
        elif option == "--avoided":
            command["impact_avoided"] = value
        elif option == "--improved":
            command["impact_improved"] = value
        elif option == "--note":
            command["impact_note"] = value
        else:
            return None
        index = index + 2
    return command


def parse_review_command(argv: list[str]) -> ParsedCommand | None:
    command: ParsedCommand = empty_command("memory_review")
    command["review_run_id"] = argv[1]
    index: int = 2
    tags: list[str] = []
    while index < len(argv):
        option: str = argv[index]
        if index + 1 >= len(argv):
            return None
        value: str = argv[index + 1]
        if option == "--status":
            command["review_status"] = value
        elif option == "--tag":
            tags = [*tags, *parse_tag_values(value)]
        elif option == "--reason":
            command["review_reason"] = value
        else:
            return None
        index = index + 2
    command["review_tags"] = tags
    return command


def parse_tag_values(value: str) -> list[str]:
    tags: list[str] = [item.strip() for item in value.split(",") if item.strip()]
    return tags


def parse_bool(value: str) -> bool | None:
    normalized_value: str = value.lower().strip()
    if normalized_value == "true":
        return True
    if normalized_value == "false":
        return False
    return None


def run_daily(date_label: str, task_goal: str, use_memory: bool) -> int:
    paths: RunPaths = build_run_paths(date_label)
    retrieved_memories: list[MemorySearchResult] = retrieve_memory_for_daily_run(task_goal, use_memory)
    retrieved_memory_context: str = build_memory_context(retrieved_memories)

    subreddits: list[str] = read_config_lines(SUBREDDITS_PATH)
    pain_keywords: list[str] = read_config_lines(PAIN_KEYWORDS_PATH)
    settings: FetchSettings = read_settings(SETTINGS_PATH)
    fetch_result = fetch_subreddits(subreddits, settings, CACHE_DIR)
    raw_entries: list[RawEntry] = fetch_result["entries"]
    fetch_errors: list[FetchError] = fetch_result["errors"]
    fetch_summary: FetchSummary = fetch_result["summary"]

    write_json(
        paths["raw_path"],
        {
            "date": date_label,
            "settings": settings,
            "fetch_summary": fetch_summary,
            "feed_results": fetch_result["feed_results"],
            "entries": raw_entries,
            "errors": fetch_errors,
        },
    )

    scored_posts: list[ScoredPost] = score_entries(raw_entries, pain_keywords)
    qualified_count: int = count_qualified_signals(scored_posts)
    excluded_count: int = len(scored_posts) - qualified_count
    write_json(
        paths["processed_path"],
        {
            "date": date_label,
            "total_posts_scanned": len(raw_entries),
            "qualified_pain_signals": qualified_count,
            "excluded_weak_signals": excluded_count,
            "fetch_summary": fetch_summary,
            "posts": scored_posts,
            "fetch_errors": fetch_errors,
        },
    )

    write_report(paths["report_path"], date_label, subreddits, len(raw_entries), scored_posts, task_goal, retrieved_memories)
    write_research_notes(paths["research_note_path"], date_label, scored_posts)
    memory_path: Path = save_daily_memory(
        date_label,
        paths,
        subreddits,
        scored_posts,
        fetch_errors,
        task_goal,
        retrieved_memories,
        retrieved_memory_context,
    )
    print_run_summary(paths, raw_entries, scored_posts, fetch_summary)
    print(f"- Agent memory path: {memory_path}")
    return 0


def build_run_paths(date_label: str) -> RunPaths:
    paths: RunPaths = {
        "raw_path": RAW_DATA_DIR / f"{date_label}.json",
        "processed_path": PROCESSED_DATA_DIR / f"{date_label}.json",
        "report_path": REPORTS_DIR / f"{date_label}.md",
        "research_note_path": RESEARCH_NOTES_DIR / f"{date_label}.md",
    }
    return paths


def read_config_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    values: list[str] = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    if not values:
        raise ValueError(f"Config file has no values: {path}")
    return values


def read_settings(path: Path) -> FetchSettings:
    if not path.exists():
        raise FileNotFoundError(f"Missing settings file: {path}")
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Settings file must contain a JSON object: {path}")
    settings: FetchSettings = {
        "base_delay_seconds": read_positive_int(payload, "base_delay_seconds", path),
        "jitter_min_seconds": read_positive_int(payload, "jitter_min_seconds", path),
        "jitter_max_seconds": read_positive_int(payload, "jitter_max_seconds", path),
        "max_retries": read_positive_int(payload, "max_retries", path),
        "retry_base_seconds": read_positive_int(payload, "retry_base_seconds", path),
    }
    if settings["jitter_min_seconds"] > settings["jitter_max_seconds"]:
        raise ValueError(f"jitter_min_seconds must be <= jitter_max_seconds in {path}")
    return settings


def read_positive_int(payload: dict[str, Any], key: str, path: Path) -> int:
    value: Any = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer in {path}")
    if value < 1:
        raise ValueError(f"{key} must be at least 1 in {path}")
    return value


def ensure_directories(paths: list[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_memory_impact_for_command(command: ParsedCommand, date_label: str) -> Path:
    current_run_id: str = command["impact_run_id"]
    trajectory: Trajectory | None = find_memory_by_run_id(current_run_id)
    trajectory_date: str = date_label
    task_goal: str = ""
    retrieved_memory_run_ids: list[str] = []
    if trajectory is not None:
        trajectory_date = trajectory["date"]
        task_goal = trajectory["task_goal"]
        retrieved_memory_run_ids = trajectory["retrieved_memory_run_ids"]
    path: Path = append_memory_impact(
        date=trajectory_date,
        current_run_id=current_run_id,
        task_goal=task_goal,
        retrieved_memory_run_ids=retrieved_memory_run_ids,
        memory_helpful=command["impact_helpful"],
        memory_rating=command["impact_rating"],
        influenced_decisions=command["impact_influenced"],
        avoided_failed_paths=command["impact_avoided"],
        new_leads_improved=command["impact_improved"],
        note=command["impact_note"],
    )
    return path


def find_memory_by_run_id(run_id: str) -> Trajectory | None:
    memories: list[Trajectory] = load_recent_memories(limit=100000)
    for memory in memories:
        if memory["run_id"] == run_id:
            return memory
    return None


def retrieve_memory_for_daily_run(task_goal: str, use_memory: bool) -> list[MemorySearchResult]:
    if not use_memory:
        return []
    results: list[MemorySearchResult] = search_memory(task_goal, limit=3)
    print("Retrieved agent memory")
    if not results:
        print("- No relevant prior memory found.")
        return []
    for index, result in enumerate(results, start=1):
        trajectory = result["trajectory"]
        print(f"{index}. {trajectory['date']} {trajectory['run_id']} score={result['score']}")
        print(f"   - Pattern: {trajectory['reusable_pattern']}")
    return results


def save_daily_memory(
    date_label: str,
    paths: RunPaths,
    subreddits: list[str],
    scored_posts: list[ScoredPost],
    fetch_errors: list[FetchError],
    task_goal: str,
    retrieved_memories: list[MemorySearchResult],
    retrieved_memory_context: str,
) -> Path:
    run_id: str = datetime.now().strftime("%H%M%S")
    best_leads: list[dict[str, Any]] = best_memory_leads(scored_posts)
    failed_paths: list[str] = [f"{error['subreddit']}: {error['error']}" for error in fetch_errors]
    reusable_pattern: str = reusable_memory_pattern(scored_posts)
    memory_path: Path = save_trajectory(
        run_id=run_id,
        date=date_label,
        task_goal=task_goal,
        mode="daily",
        queries_used=[],
        subreddits_checked=subreddits,
        posts_found_count=count_qualified_signals(scored_posts),
        best_leads=best_leads,
        failed_paths=failed_paths,
        reusable_pattern=reusable_pattern,
        source_report_path=paths["report_path"],
        source_processed_path=paths["processed_path"],
        human_feedback={},
        retrieved_memory_run_ids=[result["trajectory"]["run_id"] for result in retrieved_memories],
        retrieved_memory_context=retrieved_memory_context,
    )
    trajectory = to_trajectory(json.loads(memory_path.read_text(encoding="utf-8")))
    summarize_trajectory(trajectory)
    return memory_path


def best_memory_leads(scored_posts: list[ScoredPost]) -> list[dict[str, Any]]:
    qualified_posts: list[ScoredPost] = [post for post in scored_posts if post["is_qualified"]]
    high_posts: list[ScoredPost] = [post for post in qualified_posts if post["founder_relevance"] == "high"]
    sorted_posts: list[ScoredPost] = sorted(high_posts, key=lambda post: post["pain_score"], reverse=True)
    leads: list[dict[str, Any]] = [
        {
            "title": post["title"],
            "subreddit": post["subreddit"],
            "pain_score": post["pain_score"],
            "pain_categories": post["pain_categories"],
            "why_it_matters": post["why_it_matters"],
            "link": post["link"],
        }
        for post in sorted_posts[:5]
    ]
    return leads


def reusable_memory_pattern(scored_posts: list[ScoredPost]) -> str:
    high_leads: list[dict[str, Any]] = best_memory_leads(scored_posts)
    if high_leads:
        category_values: list[str] = [
            str(category)
            for lead in high_leads
            for category in lead.get("pain_categories", [])
        ]
        categories: str = ", ".join(sorted(set(category_values)))
        return f"RSS scan plus V0.2 quality gate found high relevance leads around: {categories}."
    return "RSS scan found few high relevance leads; refine subreddit list or strong pain patterns before repeating."


def print_memory_review_queue(status: str, limit: int) -> None:
    queue: list[Trajectory] = memory_review_queue(limit=limit, status=status)
    print(f"Agent memory review queue status={status} limit={limit}")
    if not queue:
        print(f"- No memories found for status={status}.")
        return
    for index, trajectory in enumerate(queue, start=1):
        tags: str = ", ".join(trajectory["quality_tags"]) if trajectory["quality_tags"] else "none"
        print(f"{index}. {trajectory['date']} {trajectory['run_id']} status={trajectory['memory_status']}")
        print(f"   - Goal: {trajectory['task_goal']}")
        print(f"   - Pattern: {trajectory['reusable_pattern']}")
        print(f"   - Tags: {tags}")
        print(
            f"   - Review command: python pain_radar.py --memory-review {trajectory['run_id']} "
            '--status approved --tag useful --reason "Useful reusable research pattern"'
        )


def print_memory_search_results(query: str, include_rejected: bool) -> None:
    results = search_memory(query, limit=5, include_rejected=include_rejected)
    if not results:
        print("No matching agent memories found.")
        return
    print("Agent memory matches")
    for index, result in enumerate(results, start=1):
        trajectory = result["trajectory"]
        print(f"{index}. {trajectory['date']} {trajectory['run_id']} score={result['score']}")
        print(f"   - Goal: {trajectory['task_goal']}")
        print(f"   - Status: {trajectory['memory_status']}")
        print(f"   - Pattern: {trajectory['reusable_pattern']}")
        print(f"   - Report: {trajectory['source_report_path']}")


def print_memory_stats() -> None:
    stats: dict[str, Any] = memory_stats()
    average_rating: Any = stats["average_memory_rating"]
    average_text: str = "none" if average_rating is None else f"{float(average_rating):.2f}"
    print("Agent memory stats")
    print(f"- Total memories: {stats['total_memories']}")
    print(f"- Total feedback records: {stats['total_feedback_records']}")
    print(f"- Total impact records: {stats['total_impact_records']}")
    print(f"- Average memory rating: {average_text}")
    print(f"- Most reused memory run IDs: {format_pairs(stats['most_reused_memory_run_ids'])}")
    print(f"- Highest rated memory run IDs: {format_pairs(stats['highest_rated_memory_run_ids'])}")
    status_counts: Any = stats["memory_status_counts"]
    print("- Memory status counts:")
    print(f"  - pending_review: {status_counts['pending_review']}")
    print(f"  - approved: {status_counts['approved']}")
    print(f"  - rejected: {status_counts['rejected']}")
    print(f"  - gold: {status_counts['gold']}")


def format_pairs(pairs: Any) -> str:
    if not isinstance(pairs, list) or not pairs:
        return "none"
    values: list[str] = [f"{pair[0]} ({pair[1]})" for pair in pairs if isinstance(pair, tuple)]
    if not values:
        values = [str(pair) for pair in pairs]
    return ", ".join(values)


def count_qualified_signals(scored_posts: list[ScoredPost]) -> int:
    return sum(1 for post in scored_posts if post["is_qualified"])


def print_run_summary(
    paths: RunPaths,
    raw_entries: list[RawEntry],
    scored_posts: list[ScoredPost],
    fetch_summary: FetchSummary,
) -> None:
    print("Reddit Pain Radar run complete")
    print(f"- Subreddits attempted: {fetch_summary['subreddits_attempted']}")
    print(f"- Successful feeds: {fetch_summary['successful_feeds']}")
    print(f"- Cached feeds used: {fetch_summary['cached_feeds_used']}")
    print(f"- Failed feeds: {fetch_summary['failed_feeds']}")
    print(f"- Total posts scanned: {len(raw_entries)}")
    print(f"- Qualified pain signals: {count_qualified_signals(scored_posts)}")
    print(f"- Excluded weak signals: {len(scored_posts) - count_qualified_signals(scored_posts)}")
    print(f"- Report path: {paths['report_path']}")
    print(f"- Research note path: {paths['research_note_path']}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
