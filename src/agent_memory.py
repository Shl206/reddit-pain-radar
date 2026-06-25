from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from collections import Counter


MEMORY_DIR: Path = Path("agent_memory")
TRAJECTORIES_DIR: Path = MEMORY_DIR / "trajectories"
SUMMARIES_DIR: Path = MEMORY_DIR / "summaries"
INDEX_DIR: Path = MEMORY_DIR / "index"
FEEDBACK_PATH: Path = MEMORY_DIR / "feedback.jsonl"
MEMORY_IMPACT_PATH: Path = MEMORY_DIR / "memory_impact.jsonl"
MemoryStatus = Literal["pending_review", "approved", "rejected", "gold"]
STATUS_RANK: dict[str, int] = {"gold": 300, "approved": 200, "pending_review": 50, "rejected": -1000}


class Trajectory(TypedDict):
    run_id: str
    date: str
    task_goal: str
    mode: str
    queries_used: list[str]
    subreddits_checked: list[str]
    posts_found_count: int
    best_leads: list[dict[str, Any]]
    failed_paths: list[str]
    reusable_pattern: str
    source_report_path: str
    source_processed_path: str
    human_feedback: dict[str, Any]
    retrieved_memory_run_ids: list[str]
    retrieved_memory_context: str
    memory_status: MemoryStatus
    quality_tags: list[str]
    rejection_reason: str | None
    promoted_to_gold: bool
    created_at: str


class MemorySearchResult(TypedDict):
    score: int
    trajectory: Trajectory
    path: str


class MemoryImpact(TypedDict):
    date: str
    current_run_id: str
    task_goal: str
    retrieved_memory_run_ids: list[str]
    memory_helpful: bool | None
    memory_rating: int | None
    influenced_decisions: str
    avoided_failed_paths: str
    new_leads_improved: str
    note: str
    created_at: str


def ensure_memory_dirs() -> None:
    for path in (TRAJECTORIES_DIR, SUMMARIES_DIR, INDEX_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not FEEDBACK_PATH.exists():
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        FEEDBACK_PATH.write_text("", encoding="utf-8")
    if not MEMORY_IMPACT_PATH.exists():
        MEMORY_IMPACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_IMPACT_PATH.write_text("", encoding="utf-8")


def save_trajectory(
    run_id: str,
    date: str,
    task_goal: str,
    mode: str,
    queries_used: list[str],
    subreddits_checked: list[str],
    posts_found_count: int,
    best_leads: list[dict[str, Any]],
    failed_paths: list[str],
    reusable_pattern: str,
    source_report_path: Path,
    source_processed_path: Path,
    human_feedback: dict[str, Any],
    retrieved_memory_run_ids: list[str],
    retrieved_memory_context: str,
) -> Path:
    ensure_memory_dirs()
    trajectory: Trajectory = {
        "run_id": run_id,
        "date": date,
        "task_goal": task_goal,
        "mode": mode,
        "queries_used": queries_used,
        "subreddits_checked": subreddits_checked,
        "posts_found_count": posts_found_count,
        "best_leads": best_leads,
        "failed_paths": failed_paths,
        "reusable_pattern": reusable_pattern,
        "source_report_path": str(source_report_path),
        "source_processed_path": str(source_processed_path),
        "human_feedback": human_feedback,
        "retrieved_memory_run_ids": retrieved_memory_run_ids,
        "retrieved_memory_context": retrieved_memory_context,
        "memory_status": "pending_review",
        "quality_tags": [],
        "rejection_reason": None,
        "promoted_to_gold": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path: Path = TRAJECTORIES_DIR / f"{date}-{run_id}.json"
    path.write_text(json.dumps(trajectory, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def summarize_trajectory(trajectory: Trajectory) -> Path:
    ensure_memory_dirs()
    path: Path = SUMMARIES_DIR / f"{trajectory['date']}-{trajectory['run_id']}.md"
    lines: list[str] = [
        f"# Agent Memory Summary - {trajectory['date']} - {trajectory['run_id']}",
        "",
        "## What worked",
        f"- Checked {len(trajectory['subreddits_checked'])} subreddits and found {trajectory['posts_found_count']} qualified signals.",
        f"- Best leads captured: {len(trajectory['best_leads'])}.",
        "",
        "## What failed or was weak",
        *failed_lines(trajectory["failed_paths"]),
        "",
        "## Reusable pattern",
        trajectory["reusable_pattern"],
        "",
        "## Best future use case",
        best_future_use_case(trajectory),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def load_recent_memories(limit: int = 10) -> list[Trajectory]:
    ensure_memory_dirs()
    paths: list[Path] = sorted(TRAJECTORIES_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    memories: list[Trajectory] = []
    for path in paths[:limit]:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        memories.append(to_trajectory(payload))
    return memories


def search_memory(query: str, limit: int = 5, include_rejected: bool = False) -> list[MemorySearchResult]:
    ensure_memory_dirs()
    query_words: set[str] = words(query)
    if not query_words:
        return []
    results: list[MemorySearchResult] = []
    for path in TRAJECTORIES_DIR.glob("*.json"):
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        trajectory: Trajectory = to_trajectory(payload)
        if trajectory["memory_status"] == "rejected" and not include_rejected:
            continue
        searchable_text: str = memory_search_text(trajectory, path)
        content_score: int = len(query_words.intersection(words(searchable_text)))
        content_score = content_score + len(query_words.intersection(words(summary_text(trajectory))))
        if content_score <= 0:
            continue
        score: int = content_score + feedback_score_bonus(trajectory["run_id"]) + status_score_bonus(trajectory)
        results.append({"score": score, "trajectory": trajectory, "path": str(path)})
    sorted_results: list[MemorySearchResult] = sorted(
        results,
        key=lambda result: (
            STATUS_RANK.get(result["trajectory"]["memory_status"], 0),
            result["score"],
        ),
        reverse=True,
    )
    return sorted_results[:limit]


def build_memory_context(memories: list[MemorySearchResult]) -> str:
    if not memories:
        return "No relevant prior memory found."
    lines: list[str] = []
    for result in memories:
        trajectory: Trajectory = result["trajectory"]
        lines.extend(
            [
                f"- Run ID: {trajectory['run_id']}",
                f"  - Prior task goal: {trajectory['task_goal']}",
                f"  - Reusable pattern: {trajectory['reusable_pattern']}",
                f"  - Best leads: {lead_titles(trajectory['best_leads'])}",
                f"  - Failed paths to avoid: {failed_paths_text(trajectory['failed_paths'])}",
                f"  - Human feedback rating: {feedback_rating_text(trajectory['run_id'])}",
            ]
        )
    return "\n".join(lines)


def append_feedback(run_id: str, useful: bool, rating: int, note: str) -> Path:
    if rating < 1 or rating > 10:
        raise ValueError("rating must be between 1 and 10")
    ensure_memory_dirs()
    payload: dict[str, Any] = {
        "run_id": run_id,
        "useful": useful,
        "rating": rating,
        "note": note,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with FEEDBACK_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return FEEDBACK_PATH


def update_memory_review(run_id: str, status: str, tags: list[str] | None = None, reason: str | None = None) -> Path:
    if status not in STATUS_RANK:
        raise ValueError("status must be pending_review, approved, rejected, or gold")
    ensure_memory_dirs()
    path: Path | None = find_trajectory_path(run_id)
    if path is None:
        raise FileNotFoundError(f"No trajectory found for run id or filename fragment: {run_id}")
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    existing_tags: list[str] = string_list(payload.get("quality_tags", []))
    next_tags: list[str] = unique_strings([*existing_tags, *(tags or [])])
    payload["memory_status"] = status
    payload["quality_tags"] = next_tags
    payload["rejection_reason"] = reason if status == "rejected" else None
    payload["promoted_to_gold"] = status == "gold"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def append_memory_impact(
    date: str,
    current_run_id: str,
    task_goal: str,
    retrieved_memory_run_ids: list[str],
    memory_helpful: bool | None,
    memory_rating: int | None,
    influenced_decisions: str,
    avoided_failed_paths: str,
    new_leads_improved: str,
    note: str,
) -> Path:
    if memory_rating is not None and (memory_rating < 1 or memory_rating > 10):
        raise ValueError("memory_rating must be between 1 and 10")
    ensure_memory_dirs()
    payload: MemoryImpact = {
        "date": date,
        "current_run_id": current_run_id,
        "task_goal": task_goal,
        "retrieved_memory_run_ids": retrieved_memory_run_ids,
        "memory_helpful": memory_helpful,
        "memory_rating": memory_rating,
        "influenced_decisions": influenced_decisions,
        "avoided_failed_paths": avoided_failed_paths,
        "new_leads_improved": new_leads_improved,
        "note": note,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with MEMORY_IMPACT_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return MEMORY_IMPACT_PATH


def load_memory_impact(limit: int = 20) -> list[MemoryImpact]:
    ensure_memory_dirs()
    rows: list[MemoryImpact] = []
    for line in MEMORY_IMPACT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        rows.append(to_memory_impact(payload))
    return rows[-limit:]


def memory_review_queue(limit: int = 20, status: str = "pending_review") -> list[Trajectory]:
    if limit < 1:
        return []
    if status not in {"pending_review", "approved", "rejected", "gold", "all"}:
        raise ValueError("status must be pending_review, approved, rejected, gold, or all")
    memories: list[Trajectory] = load_recent_memories(limit=100000)
    if status == "all":
        return memories[:limit]
    filtered_memories: list[Trajectory] = [
        memory for memory in memories if memory["memory_status"] == status
    ]
    return filtered_memories[:limit]


def memory_stats() -> dict[str, Any]:
    ensure_memory_dirs()
    trajectories: list[Trajectory] = load_recent_memories(limit=100000)
    feedback_rows: list[dict[str, Any]] = load_jsonl_dicts(FEEDBACK_PATH)
    impact_rows: list[MemoryImpact] = load_memory_impact(limit=100000)
    ratings: list[int] = [
        int(row["memory_rating"])
        for row in impact_rows
        if isinstance(row["memory_rating"], int)
    ]
    reused_counts: Counter[str] = Counter()
    for row in impact_rows:
        reused_counts.update(row["retrieved_memory_run_ids"])
    highest_rated: list[tuple[str, int]] = sorted(
        [
            (row["current_run_id"], int(row["memory_rating"]))
            for row in impact_rows
            if isinstance(row["memory_rating"], int)
        ],
        key=lambda pair: pair[1],
        reverse=True,
    )[:5]
    average_rating: float | None = None
    if ratings:
        average_rating = sum(ratings) / len(ratings)
    status_counts: Counter[str] = Counter(trajectory["memory_status"] for trajectory in trajectories)
    stats: dict[str, Any] = {
        "total_memories": len(trajectories),
        "total_feedback_records": len(feedback_rows),
        "total_impact_records": len(impact_rows),
        "average_memory_rating": average_rating,
        "most_reused_memory_run_ids": reused_counts.most_common(5),
        "highest_rated_memory_run_ids": highest_rated,
        "memory_status_counts": {
            "pending_review": status_counts.get("pending_review", 0),
            "approved": status_counts.get("approved", 0),
            "rejected": status_counts.get("rejected", 0),
            "gold": status_counts.get("gold", 0),
        },
    }
    return stats


def to_trajectory(payload: dict[str, Any]) -> Trajectory:
    trajectory: Trajectory = {
        "run_id": str(payload.get("run_id", "")),
        "date": str(payload.get("date", "")),
        "task_goal": str(payload.get("task_goal", "")),
        "mode": str(payload.get("mode", "")),
        "queries_used": string_list(payload.get("queries_used", [])),
        "subreddits_checked": string_list(payload.get("subreddits_checked", [])),
        "posts_found_count": int(payload.get("posts_found_count", 0)),
        "best_leads": dict_list(payload.get("best_leads", [])),
        "failed_paths": string_list(payload.get("failed_paths", [])),
        "reusable_pattern": str(payload.get("reusable_pattern", "")),
        "source_report_path": str(payload.get("source_report_path", "")),
        "source_processed_path": str(payload.get("source_processed_path", "")),
        "human_feedback": dict_value(payload.get("human_feedback", {})),
        "retrieved_memory_run_ids": string_list(payload.get("retrieved_memory_run_ids", [])),
        "retrieved_memory_context": str(payload.get("retrieved_memory_context", "")),
        "memory_status": read_memory_status(payload.get("memory_status", "pending_review")),
        "quality_tags": string_list(payload.get("quality_tags", [])),
        "rejection_reason": optional_string(payload.get("rejection_reason")),
        "promoted_to_gold": bool(payload.get("promoted_to_gold", False)),
        "created_at": str(payload.get("created_at", "")),
    }
    return trajectory


def to_memory_impact(payload: dict[str, Any]) -> MemoryImpact:
    rating_value: Any = payload.get("memory_rating")
    memory_rating: int | None = int(rating_value) if isinstance(rating_value, int) else None
    helpful_value: Any = payload.get("memory_helpful")
    memory_helpful: bool | None = helpful_value if isinstance(helpful_value, bool) else None
    impact: MemoryImpact = {
        "date": str(payload.get("date", "")),
        "current_run_id": str(payload.get("current_run_id", "")),
        "task_goal": str(payload.get("task_goal", "")),
        "retrieved_memory_run_ids": string_list(payload.get("retrieved_memory_run_ids", [])),
        "memory_helpful": memory_helpful,
        "memory_rating": memory_rating,
        "influenced_decisions": str(payload.get("influenced_decisions", "")),
        "avoided_failed_paths": str(payload.get("avoided_failed_paths", "")),
        "new_leads_improved": str(payload.get("new_leads_improved", "")),
        "note": str(payload.get("note", "")),
        "created_at": str(payload.get("created_at", "")),
    }
    return impact


def load_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        rows.append(payload)
    return rows


def find_trajectory_path(run_id: str) -> Path | None:
    paths: list[Path] = sorted(TRAJECTORIES_DIR.glob("*.json"))
    for path in paths:
        if run_id in path.stem:
            return path
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("run_id", "")) == run_id:
            return path
    return None


def read_memory_status(value: Any) -> MemoryStatus:
    if value in STATUS_RANK:
        return value
    return "pending_review"


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned_value: str = value.strip()
        if not cleaned_value or cleaned_value in seen:
            continue
        seen.add(cleaned_value)
        result.append(cleaned_value)
    return result


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def dict_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return value


def failed_lines(failed_paths: list[str]) -> list[str]:
    if not failed_paths:
        return ["- No failed paths recorded."]
    return [f"- {path}" for path in failed_paths]


def best_future_use_case(trajectory: Trajectory) -> str:
    if trajectory["best_leads"]:
        return "Use this memory when researching similar subreddit pain patterns or prioritizing founder interview topics."
    return "Use this memory to avoid repeating weak subreddit or keyword paths."


def memory_search_text(trajectory: Trajectory, path: Path) -> str:
    lead_text: str = " ".join(json.dumps(lead, ensure_ascii=False) for lead in trajectory["best_leads"])
    parts: list[str] = [
        path.name,
        trajectory["run_id"],
        trajectory["task_goal"],
        trajectory["reusable_pattern"],
        " ".join(trajectory["subreddits_checked"]),
        " ".join(trajectory["queries_used"]),
        lead_text,
    ]
    return " ".join(parts)


def summary_text(trajectory: Trajectory) -> str:
    summary_path: Path = SUMMARIES_DIR / f"{trajectory['date']}-{trajectory['run_id']}.md"
    if not summary_path.exists():
        return ""
    return summary_path.read_text(encoding="utf-8")


def feedback_score_bonus(run_id: str) -> int:
    feedback: dict[str, Any] | None = latest_feedback(run_id)
    if feedback is None:
        return 0
    rating_value: Any = feedback.get("rating", 0)
    if not isinstance(rating_value, int):
        return 0
    useful_value: Any = feedback.get("useful", False)
    useful_bonus: int = 2 if useful_value is True else 0
    return useful_bonus + max(rating_value // 3, 0)


def status_score_bonus(trajectory: Trajectory) -> int:
    return STATUS_RANK.get(trajectory["memory_status"], 0)


def feedback_rating_text(run_id: str) -> str:
    feedback: dict[str, Any] | None = latest_feedback(run_id)
    if feedback is None:
        return "none"
    return f"{feedback.get('rating', 'unknown')} useful={feedback.get('useful', 'unknown')}"


def latest_feedback(run_id: str) -> dict[str, Any] | None:
    ensure_memory_dirs()
    if not FEEDBACK_PATH.exists():
        return None
    latest: dict[str, Any] | None = None
    for line in FEEDBACK_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        if str(payload.get("run_id", "")) == run_id:
            latest = payload
    return latest


def lead_titles(best_leads: list[dict[str, Any]]) -> str:
    titles: list[str] = [str(lead.get("title", "")) for lead in best_leads[:3] if str(lead.get("title", "")).strip()]
    if not titles:
        return "none"
    return "; ".join(titles)


def failed_paths_text(failed_paths: list[str]) -> str:
    if not failed_paths:
        return "none"
    return "; ".join(failed_paths)


def words(text: str) -> set[str]:
    tokens: list[str] = re.findall(r"[a-z0-9_]{3,}", text.lower())
    return set(tokens)
