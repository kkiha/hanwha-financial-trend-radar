"""Collect recent RSS headlines and rebuild the trend feed.

    python -m scripts.refresh_trend_feed
    python -m scripts.refresh_trend_feed --skip-llm    # collection only

Without OPENAI_API_KEY the collection still runs and is saved; the existing cached
trends are left untouched, so a demo never turns synthetic data into "live".
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from rag_finance.llm.openai_runtime import resolve_api_key

from app.trend_feed_data import (
    LIVE_DIR,
    WINDOW_DAYS,
    save_company_briefs,
    save_company_relevance,
    save_live_payload,
    save_refresh_status,
    preserve_previous_briefs,
)
from rag_finance.ingestion.rss_collector import (
    SOURCE_MODES,
    REASON_ALL_FEEDS_FAILED,
    REASON_EMPTY_FEEDS,
    REASON_MISSING_DEPENDENCY,
    REASON_NO_RECENT_ARTICLES,
    collect_articles,
)
from rag_finance.llm.company_brief import (
    DEFAULT_BRIEF_MAX_TOKENS,
    generate_company_briefs,
)
from rag_finance.llm.trend_clusterer import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_TEMPERATURE,
    MAX_ARTICLES_FOR_LLM,
    TrendClusteringError,
    cluster_trends,
)
from rag_finance.llm.company_relevance import (
    DEFAULT_MAX_TOKENS_PER_COMPANY,
    DEFAULT_REASONING_EFFORT as DEFAULT_RELEVANCE_REASONING_EFFORT,
    classify_company_relevance,
)


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
    "기사 수집은 완료됐지만 OPENAI_API_KEY가 없어 AI 분석을 실행하지 못했습니다."
)
MISSING_OPENAI_PACKAGE_MESSAGE = (
    "기사 수집은 완료됐지만 openai 패키지가 없어 AI 분석을 실행하지 못했습니다.\n"
    "pip install openai 를 실행해 주세요."
)
SKIPPED_LLM_MESSAGE = "기사 수집만 실행했습니다. 기존 트렌드 결과를 유지합니다."
RELEVANCE_FAILURE_MESSAGE = (
    "트렌드는 생성했지만 회사 관련성 분류를 완료하지 못했습니다. "
    "트렌드 결과는 정상 저장했고 관련성은 UNCLASSIFIED로 기록했습니다."
)
BRIEF_FAILURE_MESSAGE = (
    "트렌드와 관련성 결과는 저장했지만 회사별 Brief를 생성하지 못했습니다. "
    "기존 결과는 유지하고 Brief 상태를 실패로 기록했습니다."
)
AI_VALIDATION_MESSAGE = (
    "AI 분석 결과가 필수 형식을 충족하지 못했습니다. 자동 재시도 후에도 "
    "복구되지 않아 기존 트렌드 결과를 유지합니다."
)
AI_REQUEST_MESSAGE = (
    "AI 분석 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요. "
    "기존 트렌드 결과를 유지합니다."
)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/service.json"


def load_env_file(path: str | Path = ".env") -> None:
    """Load local API credentials without overriding server environment values."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    env_file = Path(path)
    if env_file.is_file():
        load_dotenv(env_file)
    else:
        load_dotenv()


def _load_llm_settings(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "temperature": DEFAULT_TEMPERATURE,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "relevance_max_tokens_per_company": DEFAULT_MAX_TOKENS_PER_COMPANY,
        "brief_max_tokens": DEFAULT_BRIEF_MAX_TOKENS,
        "max_articles": MAX_ARTICLES_FOR_LLM,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "relevance_reasoning_effort": DEFAULT_RELEVANCE_REASONING_EFFORT,
        "max_attempts": DEFAULT_MAX_ATTEMPTS,
        "retry_base_delay_seconds": DEFAULT_RETRY_BASE_DELAY,
    }
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        llm = config.get("llm", {})
        if not isinstance(llm, Mapping):
            return defaults
    except (OSError, ValueError, AttributeError):
        return defaults

    settings = dict(defaults)
    if isinstance(llm.get("model"), str) and llm["model"].strip():
        settings["model"] = llm["model"].strip()
    if isinstance(llm.get("temperature"), (int, float)) and not isinstance(
        llm["temperature"], bool
    ):
        settings["temperature"] = float(llm["temperature"])
    for field in (
        "max_tokens",
        "relevance_max_tokens_per_company",
        "brief_max_tokens",
        "max_articles",
        "max_attempts",
    ):
        value = llm.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            settings[field] = value
    reasoning = llm.get("reasoning_effort")
    if reasoning in {"none", "low", "medium", "high", None}:
        settings["reasoning_effort"] = reasoning
    relevance_reasoning = llm.get("relevance_reasoning_effort")
    if relevance_reasoning in {"none", "low", "medium", "high", None}:
        settings["relevance_reasoning_effort"] = relevance_reasoning
    delay = llm.get("retry_base_delay_seconds")
    if isinstance(delay, (int, float)) and not isinstance(delay, bool) and delay >= 0:
        settings["retry_base_delay_seconds"] = float(delay)
    return settings


def _load_rss_settings(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "source_mode": "profiles",
        "profiles_dir": "configs/company_profiles",
    }
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        rss = config.get("rss", {})
        if not isinstance(rss, Mapping):
            return defaults
    except (OSError, ValueError, AttributeError):
        return defaults

    settings = dict(defaults)
    if rss.get("source_mode") in SOURCE_MODES:
        settings["source_mode"] = rss["source_mode"]
    if isinstance(rss.get("profiles_dir"), str) and rss["profiles_dir"].strip():
        settings["profiles_dir"] = rss["profiles_dir"].strip()
    return settings


def _finish_refresh(
    report: dict[str, Any], *, live_dir: Path, attempted_at: str
) -> dict[str, Any]:
    status = {
        "attempted_at": attempted_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome": report.get("outcome", "failed"),
        "stage": report.get("stage", "unknown"),
        "error_code": report.get("error_code"),
        "message": report.get("error", ""),
        "technical_error": report.get("technical_error", ""),
        "summary": report.get("summary", ""),
        "collected": report.get("collected", 0),
        "trends": report.get("trends", 0),
        "relevance_status": report.get("relevance_status"),
        "relevance_evaluations": report.get("relevance_evaluations", 0),
        "relevance_calls": report.get("relevance_calls", {}),
        "brief_status": report.get("brief_status"),
        "brief_calls": report.get("brief_calls", {}),
        "main_briefs": report.get("main_briefs", 0),
        "monitoring_items": report.get("monitoring_items", 0),
        "model": report.get("model"),
        "llm_diagnostics": report.get("llm_diagnostics", {}),
    }
    target = save_refresh_status(status, live_dir=live_dir)
    report["refresh_status_path"] = str(target)
    return report


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
    if debug.get("source_mode"):
        lines.append(
            f"검색 모드 {debug['source_mode']} · 프로파일 {debug.get('profile_count', 0)}개"
            f" · 쿼리 {debug.get('query_count', 0)}개"
        )

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
    skip_relevance: bool = False,
    skip_briefs: bool = False,
    live_dir: Path = LIVE_DIR,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    source_mode: str | None = None,
    profiles_dir: str | Path | None = None,
) -> dict:
    """Returns a report. Never raises for expected failures (network, key, feeds)."""
    load_env_file()
    preserve_previous_briefs(Path(live_dir))
    attempted_at = datetime.now(timezone.utc).isoformat()
    rss = _load_rss_settings(config_path)
    if source_mode is not None:
        if source_mode not in SOURCE_MODES:
            raise ValueError(
                f"Invalid RSS source mode {source_mode!r}; expected one of {', '.join(SOURCE_MODES)}"
            )
        rss["source_mode"] = source_mode
    if profiles_dir is not None:
        rss["profiles_dir"] = str(profiles_dir)
    articles, debug = collect_articles(
        window_days=window_days,
        source_mode=rss["source_mode"],
        profiles_dir=rss["profiles_dir"],
    )
    report: dict = {
        "collected": len(articles),
        "collection": debug,
        "summary": collection_summary(debug),
        "clustered": False,
        "relevance_classified": False,
        "relevance_evaluations": 0,
        "briefs_generated": False,
        "main_briefs": 0,
        "monitoring_items": 0,
        "ok": False,
        "outcome": "failed",
        "stage": "collection",
    }

    if not articles:
        report["error"] = MESSAGES.get(
            debug.get("reason"), MESSAGES[REASON_ALL_FEEDS_FAILED]
        )
        report["error_code"] = str(debug.get("reason") or "collection_failed")
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)

    Path(live_dir).mkdir(parents=True, exist_ok=True)
    (Path(live_dir) / "latest_articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report["articles_path"] = str(Path(live_dir) / "latest_articles.json")

    if skip_llm:
        report["error"] = SKIPPED_LLM_MESSAGE
        report.update(outcome="partial", stage="collection", error_code="llm_skipped")
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)

    if not resolve_api_key():
        report["error"] = NO_API_KEY_MESSAGE
        report.update(outcome="partial", stage="llm", error_code="missing_api_key")
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)

    llm = _load_llm_settings(config_path)
    if model:
        llm["model"] = model
    report["model"] = llm["model"]

    try:
        trends = cluster_trends(
            articles,
            model=llm["model"],
            temperature=llm["temperature"],
            max_tokens=llm["max_tokens"],
            max_articles=llm["max_articles"],
            reasoning_effort=llm["reasoning_effort"],
            max_attempts=llm["max_attempts"],
            retry_base_delay=llm["retry_base_delay_seconds"],
            window_days=window_days,
        )
    except RuntimeError as exc:
        message = str(exc)
        report["error"] = (
            MISSING_OPENAI_PACKAGE_MESSAGE if "openai package" in message else message
        )
        report.update(stage="llm", error_code="missing_openai_package")
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)
    except Exception as exc:  # noqa: BLE001 - keep the previous trends on any failure
        diagnostics = getattr(exc, "diagnostics", {})
        attempts = diagnostics.get("attempts", []) if isinstance(diagnostics, Mapping) else []
        last_outcome = attempts[-1].get("outcome") if attempts else ""
        validation_failure = isinstance(exc, TrendClusteringError) and last_outcome == "validation_error"
        report.update(
            stage="llm",
            error_code="llm_invalid_response" if validation_failure else "llm_request_failed",
            error=AI_VALIDATION_MESSAGE if validation_failure else (
                attempts[-1].get("message", AI_REQUEST_MESSAGE) if attempts else AI_REQUEST_MESSAGE),
            technical_error=type(exc).__name__,
            llm_diagnostics=diagnostics,
        )
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)

    report["path"] = str(
        save_live_payload(trends, articles, collection=debug, live_dir=live_dir)
    )
    report.update(
        clustered=True,
        ok=True,
        outcome="success",
        stage="complete",
        trends=len(trends.get("trends", [])),
        model=trends.get("model"),
        llm_diagnostics=trends.get("llm_diagnostics", {}),
    )

    if skip_relevance:
        report.update(
            relevance_status="SKIPPED",
            relevance_classified=False,
            relevance_evaluations=0,
            brief_status="SKIPPED",
        )
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)

    relevance = classify_company_relevance(
        trends,
        articles,
        profiles_dir=rss["profiles_dir"],
        model=llm["model"],
        temperature=llm["temperature"],
        max_tokens=llm["relevance_max_tokens_per_company"],
        reasoning_effort=llm["relevance_reasoning_effort"],
        max_attempts=min(llm["max_attempts"], 2),
        retry_base_delay=llm["retry_base_delay_seconds"],
    )
    relevance_path = save_company_relevance(relevance, live_dir=Path(live_dir))
    relevance_status = str(relevance.get("status") or "UNCLASSIFIED")
    relevance_count = len(relevance.get("evaluations") or [])
    report.update(
        relevance_status=relevance_status,
        relevance_classified=relevance_status == "CLASSIFIED",
        relevance_evaluations=relevance_count,
        relevance_calls=relevance.get("relevance_calls", {}),
        relevance_path=str(relevance_path),
    )
    if relevance_status != "CLASSIFIED":
        report.update(
            outcome="partial",
            stage="relevance",
            error_code="relevance_partial" if relevance_status == "PARTIAL" else "relevance_unclassified",
            error=("회사 관련성 분류가 일부 완료됐습니다. 성공한 회사의 결과를 저장했으며, 실패한 회사는 아래 사유를 확인해 주세요."
                   if relevance_status == "PARTIAL" else RELEVANCE_FAILURE_MESSAGE),
        )

    if skip_briefs:
        report["brief_status"] = "SKIPPED"
        return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)

    briefs = generate_company_briefs(
        trends,
        relevance,
        articles,
        profiles_dir=rss["profiles_dir"],
        model=llm["model"],
        temperature=llm["temperature"],
        max_tokens=llm["brief_max_tokens"],
        reasoning_effort=llm["reasoning_effort"],
        max_attempts=min(llm["max_attempts"], 2),
        retry_base_delay=llm["retry_base_delay_seconds"],
    )
    briefs_path = save_company_briefs(briefs, live_dir=Path(live_dir), articles=articles)
    brief_status = str(briefs.get("status") or "UNGENERATED")
    company_results = briefs.get("companies") or []
    main_brief_count = sum(len(company.get("briefs") or []) for company in company_results)
    monitoring_count = sum(
        len(company.get("monitoring_items") or []) for company in company_results
    )
    report.update(
        brief_status=brief_status,
        brief_calls=briefs.get("brief_calls", {}),
        briefs_generated=brief_status == "GENERATED",
        main_briefs=main_brief_count,
        monitoring_items=monitoring_count,
        briefs_path=str(briefs_path),
    )
    if brief_status != "GENERATED":
        report.update(
            outcome="partial",
            stage="briefs",
            error_code="briefs_partial" if brief_status == "PARTIAL" else "briefs_not_generated",
            error="일부 Main Brief를 생성하지 못했습니다. 성공한 Brief와 Monitoring은 저장했습니다. 이전 성공 자료가 있으면 별도로 표시합니다." if brief_status == "PARTIAL" else BRIEF_FAILURE_MESSAGE,
        )
    return _finish_refresh(report, live_dir=Path(live_dir), attempted_at=attempted_at)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the Global Finance Radar trend feed")
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--model", default=None)
    parser.add_argument("--skip-llm", action="store_true", help="Collect articles only")
    parser.add_argument(
        "--skip-relevance",
        action="store_true",
        help="Generate trends but skip company relevance classification",
    )
    parser.add_argument(
        "--skip-briefs",
        action="store_true",
        help="Generate trends and relevance but skip company briefs",
    )
    parser.add_argument(
        "--source-mode",
        choices=SOURCE_MODES,
        default=None,
        help="RSS query source (default: config value, profiles)",
    )
    args = parser.parse_args()

    report = refresh(
        window_days=args.window_days,
        model=args.model,
        skip_llm=args.skip_llm,
        skip_relevance=args.skip_relevance,
        skip_briefs=args.skip_briefs,
        source_mode=args.source_mode,
    )
    print(report["summary"])
    if report.get("error"):
        print()
        print(report["error"])
    if report.get("clustered"):
        print()
        print(f"트렌드 {report['trends']}건 생성 · {report['path']}")
    if report.get("relevance_status"):
        print(
            f"관련성 {report['relevance_status']} · "
            f"평가 {report.get('relevance_evaluations', 0)}건"
        )
    if report.get("brief_status"):
        print(
            f"Brief {report['brief_status']} · Main {report.get('main_briefs', 0)}건"
            f" · Monitoring {report.get('monitoring_items', 0)}건"
        )


if __name__ == "__main__":
    main()
