"""Collect recent RSS headlines and rebuild the trend feed.

    python -m scripts.refresh_trend_feed
    python -m scripts.refresh_trend_feed --skip-llm    # collection only

Without GROQ_API_KEY the collection still runs and is saved; the existing cached
trends are left untouched, so a demo never turns synthetic data into "live".
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.trend_feed_data import LIVE_DIR, WINDOW_DAYS, save_live_payload
from rag_finance.ingestion.rss_collector import (
    REASON_ALL_FEEDS_FAILED,
    REASON_EMPTY_FEEDS,
    REASON_MISSING_DEPENDENCY,
    REASON_NO_RECENT_ARTICLES,
    collect_articles,
)
from rag_finance.llm.trend_clusterer import DEFAULT_MODEL, cluster_trends


MESSAGES = {
    REASON_MISSING_DEPENDENCY: (
        "RSS 수집에 필요한 패키지가 설치되지 않았습니다.\n"
        "pip install -r requirements.txt를 실행해 주세요."
    ),
    REASON_ALL_FEEDS_FAILED: (
        "RSS 피드 수집에 실패했습니다.\n네트워크 연결 및 피드 응답 상태를 확인해 주세요."
    ),
    REASON_EMPTY_FEEDS: (
        "RSS 피드가 응답했지만 기사를 반환하지 않았습니다.\n"
        "짧은 간격으로 반복 요청하면 제공자가 빈 결과를 돌려줄 수 있습니다. "
        "잠시 후 다시 시도해 주세요."
    ),
    REASON_NO_RECENT_ARTICLES: (
        f"피드는 응답했지만 최근 {WINDOW_DAYS}일 기사를 찾지 못했습니다.\n"
        "피드 응답 내용을 확인해 주세요."
    ),
}
NO_API_KEY_MESSAGE = (
    "기사 수집은 완료됐지만 GROQ_API_KEY가 없어 AI 분석을 실행하지 못했습니다."
)
MISSING_GROQ_PACKAGE_MESSAGE = (
    "기사 수집은 완료됐지만 groq 패키지가 없어 AI 분석을 실행하지 못했습니다.\n"
    "pip install groq 를 실행해 주세요."
)
SKIPPED_LLM_MESSAGE = "기사 수집만 실행했습니다. 기존 트렌드 결과를 유지합니다."


def load_env_file(path: str | Path = ".env") -> None:
    """Optional .env support, mirroring scripts/generate_report.py."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    env_file = Path(path)
    if env_file.is_file():
        load_dotenv(env_file)
    else:
        load_dotenv()


def _load_model_name(config_path: str | Path) -> str:
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return str(config.get("llm", {}).get("model") or DEFAULT_MODEL)
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MODEL


def collection_summary(debug: dict) -> str:
    """The lines an operator needs to judge a partial failure.

    "responded" and "returned articles" are reported separately: a throttled
    provider answers 200 with an empty feed, and counting that as success would
    hide the real problem.
    """
    languages = debug.get("language_counts", {})
    total = debug.get("feeds_total", 0)
    responded = debug.get("feeds_ok", 0)
    with_articles = debug.get("feeds_with_articles", responded)

    head = f"RSS 피드 {responded}/{total} 응답"
    if with_articles != responded:
        head += f" · 기사 반환 {with_articles}/{total}"
    lines = [
        head,
        f"기사 {debug.get('in_window_count', 0)}건 수집",
        f"중복 제거 후 {debug.get('deduped_count', 0)}건",
        f"국내 {languages.get('ko', 0)}건 · 해외 {languages.get('en', 0)}건",
    ]

    empty_languages = [
        language
        for language, count in languages.items()
        if count == 0 and debug.get("ok_by_language", {}).get(language, 0) > 0
    ]
    if empty_languages:
        names = " · ".join("국내" if lang == "ko" else "해외" for lang in empty_languages)
        lines.append(f"경고: {names} 피드가 기사를 반환하지 않았습니다.")
    return "\n".join(lines)


def refresh(
    *,
    window_days: int = WINDOW_DAYS,
    model: str | None = None,
    skip_llm: bool = False,
    live_dir: Path = LIVE_DIR,
) -> dict:
    """Returns a report. Never raises for expected failures (network, key, feeds)."""
    load_env_file()
    articles, debug = collect_articles(window_days=window_days)
    report: dict = {
        "collected": len(articles),
        "collection": debug,
        "summary": collection_summary(debug),
        "clustered": False,
        "ok": False,
    }

    if not articles:
        report["error"] = MESSAGES.get(
            debug.get("reason"), MESSAGES[REASON_ALL_FEEDS_FAILED]
        )
        return report

    Path(live_dir).mkdir(parents=True, exist_ok=True)
    (Path(live_dir) / "latest_articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report["articles_path"] = str(Path(live_dir) / "latest_articles.json")

    if skip_llm:
        report["error"] = SKIPPED_LLM_MESSAGE
        return report

    if not os.environ.get("GROQ_API_KEY", "").strip():
        report["error"] = NO_API_KEY_MESSAGE
        return report

    try:
        trends = cluster_trends(
            articles,
            model=model or _load_model_name("configs/trend_demo.yaml"),
            window_days=window_days,
        )
    except RuntimeError as exc:
        message = str(exc)
        report["error"] = (
            MISSING_GROQ_PACKAGE_MESSAGE if "groq package" in message else message
        )
        return report
    except Exception as exc:  # noqa: BLE001 - keep the previous trends on any failure
        report["error"] = f"AI 분석에 실패했습니다: {type(exc).__name__}: {exc}"
        return report

    report["path"] = str(
        save_live_payload(trends, articles, collection=debug, live_dir=live_dir)
    )
    report.update(
        clustered=True,
        ok=True,
        trends=len(trends.get("trends", [])),
        model=trends.get("model"),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the Global Finance Radar trend feed")
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--model", default=None)
    parser.add_argument("--skip-llm", action="store_true", help="Collect articles only")
    args = parser.parse_args()

    report = refresh(
        window_days=args.window_days, model=args.model, skip_llm=args.skip_llm
    )
    print(report["summary"])
    if report.get("error"):
        print()
        print(report["error"])
    if report.get("clustered"):
        print()
        print(f"트렌드 {report['trends']}건 생성 · {report['path']}")


if __name__ == "__main__":
    main()
