from __future__ import annotations

import re
from typing import Literal, TypedDict

from src.rss_fetcher import RawEntry


PainCategory = Literal[
    "workflow_pain",
    "tool_request",
    "compliance_pain",
    "technical_failure",
    "staffing_pain",
    "money_pain",
    "confusion_pain",
    "weak_signal",
]
FounderRelevance = Literal["high", "medium", "low"]
Language = Literal["english", "non_english"]

STRONG_PAIN_PATTERNS: dict[str, tuple[str, ...]] = {
    "explicit_complaint": ("i hate", "frustrating", "annoying", "painful", "terrible", "broken", "doesn't work"),
    "struggle_request": (
        "i'm struggling",
        "struggling to",
        "can't figure out",
        "need help",
        "how do i",
        "how can i",
        "why is it so hard",
    ),
    "tool_intent": ("is there a tool", "any tool", "looking for a tool", "software for", "app for", "platform for"),
    "manual_workaround": (
        "manual",
        "manually",
        "spreadsheet",
        "copy paste",
        "workaround",
        "currently using",
        "takes forever",
        "repetitive",
    ),
    "money_pain": ("too expensive", "expensive", "fees", "pricing", "can't afford", "overpriced"),
}
WEAK_TERMS: tuple[str, ...] = ("automation", "tool", "software", "spreadsheet", "saas", "startup", "idea", "user")
FALSE_POSITIVE_TITLE_PATTERNS: tuple[str, ...] = (
    "roast my idea",
    "looking for my first user",
    "my failures and what i learned",
    "why does every great saas company",
    "generic startup advice",
    "self promotion",
    "self-promotion",
    "check out my",
    "i built",
    "i launched",
    "launching my",
    "newsletter",
)
HIGH_RELEVANCE_CATEGORIES: set[PainCategory] = {
    "workflow_pain",
    "tool_request",
    "compliance_pain",
    "technical_failure",
    "staffing_pain",
}


class StrongPatternMatch(TypedDict):
    pattern_type: str
    phrase: str
    location: str


class ScoredPost(TypedDict):
    title: str
    subreddit: str
    link: str
    published: str
    author: str
    summary: str
    language: Language
    pain_score: int
    founder_relevance: FounderRelevance
    pain_categories: list[PainCategory]
    matched_keywords: list[str]
    matched_strong_patterns: list[str]
    exclusion_reasons: list[str]
    is_qualified: bool
    why_it_matters: str
    short_reason: str
    review_status: str
    research_status: str
    idea_status: str
    my_note: str
    follow_up_query: str


def score_entries(entries: list[RawEntry], pain_keywords: list[str]) -> list[ScoredPost]:
    scored_posts: list[ScoredPost] = [score_entry(entry, pain_keywords) for entry in entries]
    deduped_posts: list[ScoredPost] = mark_duplicate_titles_as_excluded(scored_posts)
    candidate_posts: list[ScoredPost] = [post for post in deduped_posts if has_reportable_signal(post)]
    sorted_posts: list[ScoredPost] = sorted(
        candidate_posts,
        key=lambda post: (post["is_qualified"], post["pain_score"]),
        reverse=True,
    )
    return sorted_posts


def mark_duplicate_titles_as_excluded(scored_posts: list[ScoredPost]) -> list[ScoredPost]:
    seen_titles: set[str] = set()
    deduped_posts: list[ScoredPost] = []
    for post in scored_posts:
        title_key: str = f"{post['subreddit']}:{normalize_text(post['title'])}"
        if title_key in seen_titles:
            deduped_posts.append(exclude_duplicate_post(post))
            continue
        seen_titles.add(title_key)
        deduped_posts.append(post)
    return deduped_posts


def exclude_duplicate_post(post: ScoredPost) -> ScoredPost:
    exclusion_reasons: list[str] = [*post["exclusion_reasons"], "duplicate title already included"]
    categories: list[PainCategory] = post["pain_categories"]
    if "weak_signal" not in categories:
        categories = [*categories, "weak_signal"]
    duplicate_post: ScoredPost = {
        "title": post["title"],
        "subreddit": post["subreddit"],
        "link": post["link"],
        "published": post["published"],
        "author": post["author"],
        "summary": post["summary"],
        "language": post["language"],
        "pain_score": max(post["pain_score"] - 4, 0),
        "founder_relevance": "low",
        "pain_categories": unique_categories(categories),
        "matched_keywords": post["matched_keywords"],
        "matched_strong_patterns": post["matched_strong_patterns"],
        "exclusion_reasons": exclusion_reasons,
        "is_qualified": False,
        "why_it_matters": "Duplicate title; review the first matching signal instead.",
        "short_reason": "duplicate title already included",
        "review_status": "unreviewed",
        "research_status": "new",
        "idea_status": "none",
        "my_note": "",
        "follow_up_query": "",
    }
    return duplicate_post


def score_entry(entry: RawEntry, pain_keywords: list[str]) -> ScoredPost:
    title: str = entry["title"]
    summary: str = entry["summary"]
    combined_text: str = f"{title}\n{summary}"
    strong_matches: list[StrongPatternMatch] = find_strong_pattern_matches(title, summary)
    matched_strong_patterns: list[str] = format_strong_matches(strong_matches)
    matched_keywords: list[str] = match_keywords(combined_text, pain_keywords)
    exclusion_reasons: list[str] = false_positive_reasons(title, combined_text, strong_matches)
    categories: list[PainCategory] = classify_categories(combined_text, strong_matches, exclusion_reasons)
    score: int = calculate_pain_score(title, combined_text, strong_matches, matched_keywords, exclusion_reasons)
    qualified: bool = bool(strong_matches) and not exclusion_reasons
    relevance: FounderRelevance = founder_relevance(score, categories, qualified)
    scored_post: ScoredPost = {
        "title": title,
        "subreddit": entry["subreddit"],
        "link": entry["link"],
        "published": entry["published"],
        "author": entry["author"],
        "summary": summary,
        "language": detect_language(combined_text),
        "pain_score": score,
        "founder_relevance": relevance,
        "pain_categories": categories,
        "matched_keywords": matched_keywords,
        "matched_strong_patterns": matched_strong_patterns,
        "exclusion_reasons": exclusion_reasons,
        "is_qualified": qualified,
        "why_it_matters": why_it_matters(categories, relevance, qualified),
        "short_reason": short_reason(matched_strong_patterns, exclusion_reasons, categories),
        "review_status": "unreviewed",
        "research_status": "new",
        "idea_status": "none",
        "my_note": "",
        "follow_up_query": "",
    }
    return scored_post


def find_strong_pattern_matches(title: str, summary: str) -> list[StrongPatternMatch]:
    matches: list[StrongPatternMatch] = []
    normalized_title: str = normalize_text(title)
    normalized_summary: str = normalize_text(summary)
    for pattern_type, phrases in STRONG_PAIN_PATTERNS.items():
        for phrase in phrases:
            normalized_phrase: str = normalize_text(phrase)
            if normalized_phrase in normalized_title:
                matches.append({"pattern_type": pattern_type, "phrase": phrase, "location": "title"})
            elif normalized_phrase in normalized_summary:
                matches.append({"pattern_type": pattern_type, "phrase": phrase, "location": "summary"})
    return matches


def false_positive_reasons(title: str, combined_text: str, strong_matches: list[StrongPatternMatch]) -> list[str]:
    normalized_title: str = normalize_text(title)
    reasons: list[str] = [
        f"title matches false-positive pattern: {pattern}"
        for pattern in FALSE_POSITIVE_TITLE_PATTERNS
        if pattern in normalized_title
    ]
    if contains_any(combined_text, ("startup advice", "growth hack", "follow me", "dm me", "subscribe")) and not strong_matches:
        reasons.append("generic startup advice or self-promotion without user pain")
    if not strong_matches:
        reasons.append("no strong pain pattern")
    return reasons


def classify_categories(
    combined_text: str,
    strong_matches: list[StrongPatternMatch],
    exclusion_reasons: list[str],
) -> list[PainCategory]:
    categories: list[PainCategory] = []
    pattern_types: set[str] = {match["pattern_type"] for match in strong_matches}
    if "manual_workaround" in pattern_types:
        categories.append("workflow_pain")
    if "tool_intent" in pattern_types:
        categories.append("tool_request")
    if "money_pain" in pattern_types:
        categories.append("money_pain")
    if "struggle_request" in pattern_types or contains_any(combined_text, ("confusing", "confused", "can't figure out")):
        categories.append("confusion_pain")
    if "explicit_complaint" in pattern_types and contains_any(combined_text, ("broken", "doesn't work", "error", "bug", "crash", "failed")):
        categories.append("technical_failure")
    if contains_any(combined_text, ("compliance", "tax", "legal", "regulation", "audit", "policy", "invoice", "payroll")) and strong_matches:
        categories.append("compliance_pain")
    if contains_any(combined_text, ("hire", "hiring", "employee", "staff", "staffing", "recruit", "team member")) and strong_matches:
        categories.append("staffing_pain")
    if exclusion_reasons and not categories:
        categories.append("weak_signal")
    if not categories:
        categories.append("weak_signal")
    return unique_categories(categories)


def calculate_pain_score(
    title: str,
    combined_text: str,
    strong_matches: list[StrongPatternMatch],
    matched_keywords: list[str],
    exclusion_reasons: list[str],
) -> int:
    title_match_count: int = sum(1 for match in strong_matches if match["location"] == "title")
    summary_match_count: int = sum(1 for match in strong_matches if match["location"] == "summary")
    score: int = title_match_count * 4 + summary_match_count * 3
    if contains_any(combined_text, WEAK_TERMS) and strong_matches:
        score = score + 1
    if "?" in title and strong_matches:
        score = score + 1
    if matched_keywords and strong_matches:
        score = score + min(len(matched_keywords), 3)
    if exclusion_reasons:
        score = max(score - 4, 0)
    return score


def founder_relevance(score: int, categories: list[PainCategory], qualified: bool) -> FounderRelevance:
    has_high_category: bool = any(category in HIGH_RELEVANCE_CATEGORIES for category in categories)
    if qualified and score >= 8 and has_high_category:
        return "high"
    if qualified and score >= 5:
        return "medium"
    return "low"


def detect_language(text: str) -> Language:
    compact_text: str = re.sub(r"\s+", "", text)
    if not compact_text:
        return "english"
    non_ascii_count: int = sum(1 for character in compact_text if ord(character) > 127)
    non_ascii_ratio: float = non_ascii_count / len(compact_text)
    if non_ascii_ratio > 0.04 or contains_any(text, ("¿", "qué", "cómo", "para", "por qué")):
        return "non_english"
    return "english"


def why_it_matters(categories: list[PainCategory], relevance: FounderRelevance, qualified: bool) -> str:
    if not qualified:
        return "Weak or generic signal; review only if this theme repeats."
    if relevance == "high":
        return "Strong founder-research lead because it ties a real pain pattern to an operational problem."
    if "money_pain" in categories:
        return "Worth checking because pricing or affordability pain can reveal urgent buying pressure."
    if "confusion_pain" in categories:
        return "Worth checking because confusion may indicate unclear workflows or unmet education/tooling needs."
    return "Worth checking if similar complaints appear across multiple posts or communities."


def short_reason(
    matched_strong_patterns: list[str],
    exclusion_reasons: list[str],
    categories: list[PainCategory],
) -> str:
    if exclusion_reasons:
        return "; ".join(exclusion_reasons)
    if matched_strong_patterns:
        return f"Matched strong pain pattern and classified as {', '.join(categories)}."
    return "No strong pain pattern matched."


def has_reportable_signal(post: ScoredPost) -> bool:
    return post["pain_score"] > 0 or bool(post["exclusion_reasons"]) or bool(post["matched_keywords"])


def format_strong_matches(matches: list[StrongPatternMatch]) -> list[str]:
    values: list[str] = [
        f"{match['pattern_type']}: {match['phrase']} ({match['location']})"
        for match in matches
    ]
    return unique_preserving_order(values)


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    normalized_text: str = normalize_text(text)
    matched: list[str] = [keyword for keyword in keywords if normalize_text(keyword) in normalized_text]
    return unique_preserving_order(matched)


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized_text: str = normalize_text(text)
    result: bool = any(normalize_text(term) in normalized_text for term in terms)
    return result


def unique_categories(values: list[PainCategory]) -> list[PainCategory]:
    seen: set[PainCategory] = set()
    unique_values: list[PainCategory] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized_value: str = normalize_text(value)
        if normalized_value in seen:
            continue
        seen.add(normalized_value)
        unique_values.append(value)
    return unique_values


def normalize_text(text: str) -> str:
    lowered: str = text.lower()
    normalized: str = re.sub(r"\s+", " ", lowered).strip()
    return normalized
