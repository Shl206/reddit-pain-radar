from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.agent_memory import MemorySearchResult
from src.pain_scorer import ScoredPost


def write_report(
    report_path: Path,
    date_label: str,
    subreddits: list[str],
    total_posts: int,
    scored_posts: list[ScoredPost],
    task_goal: str,
    retrieved_memories: list[MemorySearchResult],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = build_report_lines(date_label, subreddits, total_posts, scored_posts, task_goal, retrieved_memories)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def write_research_notes(note_path: Path, date_label: str, scored_posts: list[ScoredPost]) -> None:
    if note_path.exists():
        return
    note_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = build_research_note_lines(date_label, scored_posts)
    note_path.write_text("\n".join(lines), encoding="utf-8")


def build_report_lines(
    date_label: str,
    subreddits: list[str],
    total_posts: int,
    scored_posts: list[ScoredPost],
    task_goal: str,
    retrieved_memories: list[MemorySearchResult],
) -> list[str]:
    qualified_posts: list[ScoredPost] = qualified_signals(scored_posts)
    english_posts: list[ScoredPost] = [post for post in qualified_posts if post["language"] == "english"]
    non_english_posts: list[ScoredPost] = [post for post in qualified_posts if post["language"] == "non_english"]
    excluded_posts: list[ScoredPost] = excluded_signals(scored_posts)
    high_posts: list[ScoredPost] = relevance_posts(english_posts, "high")
    medium_posts: list[ScoredPost] = relevance_posts(english_posts, "medium")
    low_posts: list[ScoredPost] = relevance_posts(english_posts, "low")
    lines: list[str] = [
        f"# Reddit Pain Radar - {date_label}",
        "",
        "## Summary",
        f"- Total posts scanned: {total_posts}",
        f"- Qualified pain signals: {len(qualified_posts)}",
        f"- Excluded weak signals: {len(excluded_posts)}",
        f"- High relevance count: {len(relevance_posts(qualified_posts, 'high'))}",
        f"- Medium relevance count: {len(relevance_posts(qualified_posts, 'medium'))}",
        f"- Low relevance count: {len(relevance_posts(qualified_posts, 'low'))}",
        f"- Subreddits scanned: {', '.join(subreddits)}",
        "",
        "## Retrieved Agent Memory",
        "",
        *retrieved_memory_lines(task_goal, retrieved_memories),
        "",
        "## Best 5 Research Leads",
        "",
    ]
    lines.extend(best_research_leads(relevance_posts(qualified_posts, "high")[:5]))
    lines.extend(manual_review_lines(relevance_posts(qualified_posts, "high")))
    lines.extend(section_lines("High Relevance Signals", high_posts))
    lines.extend(section_lines("Medium Relevance Signals", medium_posts))
    lines.extend(section_lines("Low Relevance Signals", low_posts))
    lines.extend(section_lines("Non-English Signals", non_english_posts))
    lines.extend(excluded_summary_lines(excluded_posts))
    lines.extend(memory_impact_review_lines())
    return lines


def retrieved_memory_lines(task_goal: str, retrieved_memories: list[MemorySearchResult]) -> list[str]:
    lines: list[str] = [f"- Query/task goal: {task_goal}"]
    if not retrieved_memories:
        lines.append("- No relevant prior memory found.")
        return lines
    run_ids: str = ", ".join(result["trajectory"]["run_id"] for result in retrieved_memories)
    lines.append(f"- Matched run IDs: {run_ids}")
    lines.append("- Reusable patterns:")
    for result in retrieved_memories:
        trajectory = result["trajectory"]
        lines.append(f"  - {trajectory['run_id']}: {trajectory['reusable_pattern']}")
    lines.append("- Failed paths to avoid:")
    failed_paths: list[str] = [
        failed_path
        for result in retrieved_memories
        for failed_path in result["trajectory"]["failed_paths"]
    ]
    if failed_paths:
        for failed_path in failed_paths:
            lines.append(f"  - {failed_path}")
    else:
        lines.append("  - none")
    lines.append("- Best prior leads:")
    prior_leads: list[str] = [
        str(lead.get("title", ""))
        for result in retrieved_memories
        for lead in result["trajectory"]["best_leads"][:3]
        if str(lead.get("title", "")).strip()
    ]
    if prior_leads:
        for lead_title in prior_leads[:5]:
            lines.append(f"  - {lead_title}")
    else:
        lines.append("  - none")
    return lines


def build_research_note_lines(date_label: str, scored_posts: list[ScoredPost]) -> list[str]:
    high_posts: list[ScoredPost] = relevance_posts(qualified_signals(scored_posts), "high")
    lines: list[str] = [
        f"# Research Notes - {date_label}",
        "",
        "## High Relevance Signals To Review",
        "",
    ]
    if not high_posts:
        lines.extend(["No high relevance signals to review today.", ""])
        return lines
    for post in high_posts:
        categories: str = ", ".join(post["pain_categories"])
        lines.extend(
            [
                f"### {post['title']}",
                "",
                f"- Title: {post['title']}",
                f"- Subreddit: r/{post['subreddit']}",
                f"- Link: {post['link']}",
                f"- Pain categories: {categories}",
                f"- Why it matters: {post['why_it_matters']}",
                "- My notes:",
                "- Decision:",
                "",
            ]
        )
    return lines


def qualified_signals(scored_posts: list[ScoredPost]) -> list[ScoredPost]:
    posts: list[ScoredPost] = [post for post in scored_posts if post["is_qualified"]]
    return sorted(posts, key=lambda post: post["pain_score"], reverse=True)


def excluded_signals(scored_posts: list[ScoredPost]) -> list[ScoredPost]:
    posts: list[ScoredPost] = [post for post in scored_posts if not post["is_qualified"]]
    return sorted(posts, key=lambda post: post["pain_score"], reverse=True)


def relevance_posts(scored_posts: list[ScoredPost], relevance: str) -> list[ScoredPost]:
    posts: list[ScoredPost] = [post for post in scored_posts if post["founder_relevance"] == relevance]
    return sorted(posts, key=lambda post: post["pain_score"], reverse=True)


def best_research_leads(high_posts: list[ScoredPost]) -> list[str]:
    if not high_posts:
        return ["No high relevance research leads found today.", ""]
    lines: list[str] = []
    for index, post in enumerate(high_posts, start=1):
        categories: str = ", ".join(post["pain_categories"])
        lines.extend(
            [
                f"{index}. {post['title']}",
                f"   - Pain: {plain_title(post['title'])}",
                f"   - Who has it: people posting in r/{post['subreddit']}",
                f"   - Why it matters: {post['why_it_matters']}",
                f"   - What to search next: more posts mentioning {search_terms(post)}",
                f"   - Possible product angle: hypothesis only - {product_angle(categories)}",
                "",
            ]
        )
    return lines


def manual_review_lines(high_posts: list[ScoredPost]) -> list[str]:
    lines: list[str] = ["## Manual Review", ""]
    if not high_posts:
        lines.extend(["No high relevance signals to review today.", ""])
        return lines
    for post in high_posts:
        lines.extend(
            [
                f"### {post['title']}",
                "",
                "- Is this a real pain? yes / no / unsure:",
                "- Who has this pain:",
                "- Existing workaround:",
                "- Would they pay or spend time to solve it?:",
                "- My founder note:",
                "- Follow-up search query:",
                "- Decision: ignore / research_more / possible_project",
                "",
            ]
        )
    return lines


def section_lines(title: str, posts: list[ScoredPost]) -> list[str]:
    lines: list[str] = [f"## {title}", ""]
    if not posts:
        lines.extend(["No signals in this section.", ""])
        return lines
    for index, post in enumerate(posts, start=1):
        lines.extend(signal_lines(index, post))
    return lines


def signal_lines(index: int, post: ScoredPost) -> list[str]:
    categories: str = ", ".join(post["pain_categories"])
    patterns: str = ", ".join(post["matched_strong_patterns"]) if post["matched_strong_patterns"] else "None"
    lines: list[str] = [
        f"{index}. {post['title']}",
        f"   - Subreddit: r/{post['subreddit']}",
        f"   - Pain score: {post['pain_score']}",
        f"   - Founder relevance: {post['founder_relevance']}",
        f"   - Pain categories: {categories}",
        f"   - Matched strong patterns: {patterns}",
        f"   - Why it matters: {post['why_it_matters']}",
        f"   - Link: {post['link']}",
        "",
    ]
    return lines


def excluded_summary_lines(excluded_posts: list[ScoredPost]) -> list[str]:
    lines: list[str] = ["## Excluded / Weak Signals Summary", ""]
    if not excluded_posts:
        lines.extend(["No weak signals excluded today.", ""])
        return lines
    reason_counts: Counter[str] = Counter()
    for post in excluded_posts:
        reason_counts.update(post["exclusion_reasons"])
    lines.append(f"- Total excluded: {len(excluded_posts)}")
    for reason, count in reason_counts.most_common(5):
        lines.append(f"- {reason}: {count}")
    lines.append("")
    lines.append("Sample excluded signals:")
    for index, post in enumerate(excluded_posts[:10], start=1):
        reasons: str = "; ".join(post["exclusion_reasons"]) if post["exclusion_reasons"] else "weak or generic"
        lines.append(f"{index}. {post['title']} - {reasons}")
    lines.append("")
    return lines


def memory_impact_review_lines() -> list[str]:
    lines: list[str] = [
        "## Memory Impact Review",
        "",
        "Suggested impact command:",
        "",
        '```powershell',
        'python pain_radar.py --memory-impact <current_run_id> --helpful true/false --rating 1-10 --note "..."',
        '```',
        "",
        "Suggested memory review command:",
        "",
        '```powershell',
        'python pain_radar.py --memory-review <current_run_id> --status approved --tag "..." --reason "..."',
        '```',
        "",
    ]
    return lines


def plain_title(title: str) -> str:
    stripped_title: str = title.strip()
    if stripped_title:
        return stripped_title
    return "Untitled pain signal"


def search_terms(post: ScoredPost) -> str:
    if post["matched_strong_patterns"]:
        terms: list[str] = [pattern.split(": ", maxsplit=1)[-1].split(" (", maxsplit=1)[0] for pattern in post["matched_strong_patterns"][:2]]
        return ", ".join(terms)
    return ", ".join(post["pain_categories"])


def product_angle(categories: str) -> str:
    if "tool_request" in categories:
        return "research a focused tool comparison or workflow replacement"
    if "workflow_pain" in categories:
        return "research automation for the repeated manual workflow"
    if "compliance_pain" in categories:
        return "research a guided checklist or compliance workflow helper"
    if "technical_failure" in categories:
        return "research monitoring, repair, or integration reliability tooling"
    if "staffing_pain" in categories:
        return "research hiring, delegation, or staffing operations support"
    if "money_pain" in categories:
        return "research lower-cost alternatives or pricing transparency"
    return "research the problem before proposing a solution"
