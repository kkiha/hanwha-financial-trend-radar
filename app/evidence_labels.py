"""Conservative title-based event hints for display only; never change scores."""
from datetime import datetime
import re


def _tokens(article):
    return set(re.findall(r"[가-힣a-z0-9]+", str(article.get("title", "")).casefold()))


def _same_event(left, right):
    try:
        dates = [datetime.fromisoformat(str(a.get("published_at", "")).replace("Z", "+00:00"))
                 for a in (left, right)]
        if abs((dates[0] - dates[1]).total_seconds()) > 48 * 3600:
            return False
    except (ValueError, TypeError):
        return False
    a, b = _tokens(left), _tokens(right)
    shared = a & b
    if len(shared) < 4:
        return False
    if a == b:
        return True
    # Require a shared named financial company and action, not just a topic.
    company = any(re.fullmatch(r"[가-힣]+(?:증권|은행|생명|자산운용|보험|금융)", t) for t in shared)
    action = any(t in shared for t in ("이벤트", "출시", "인수", "협약", "투자", "계약"))
    numbers_a = {t for t in a if re.match(r"\d", t)}
    numbers_b = {t for t in b if re.match(r"\d", t)}
    if numbers_a and numbers_b and numbers_a != numbers_b:
        return False
    return company and action and len(shared) / min(len(a), len(b)) >= 0.55


def label_event_reports(articles):
    """Annotate an already-copied list without removing or reordering articles.

    Complete-link grouping avoids merging unrelated stories through a bridge.
    Missing labels mean unknown, not independently corroborated events.
    """
    groups = []
    for article in articles:
        article.pop("event_label", None)
        group = next((g for g in groups if all(_same_event(article, other) for other in g)), None)
        if group is None:
            groups.append([article])
        else:
            group.append(article)
    number = 0
    for group in groups:
        if len(group) < 2:
            continue
        number += 1
        for article in group:
            article["event_label"] = f"동일 사건 보도 추정 · 묶음 {number} · {len(group)}건"
