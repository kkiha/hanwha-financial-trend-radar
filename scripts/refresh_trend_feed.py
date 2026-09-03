"""Collect recent RSS headlines and rebuild the trend feed.

    python -m scripts.refresh_trend_feed
    python -m scripts.refresh_trend_feed --skip-llm    # collection only

Without GROQ_API_KEY the collection still runs and is saved; the existing cached
trends are left untouched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.trend_feed_data import LIVE_DIR, WINDOW_DAYS, save_live_payload
from rag_finance.ingestion.rss_collector import collect_articles
from rag_finance.llm.trend_clusterer import DEFAULT_MODEL, cluster_trends


def _load_model_name(config_path: str | Path) -> str:
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return str(config.get("llm", {}).get("model") or DEFAULT_MODEL)
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MODEL


def refresh(
    *,
    window_days: int = WINDOW_DAYS,
    model: str | None = None,
    skip_llm: bool = False,
    live_dir: Path = LIVE_DIR,
) -> dict:
    """Returns a small report; raises only on unrecoverable errors."""
    articles, debug = collect_articles(window_days=window_days)
    report: dict = {"collected": len(articles), "collection": debug, "clustered": False}
    if not articles:
        report["error"] = "수집된 기사가 없습니다."
        return report

    Path(live_dir).mkdir(parents=True, exist_ok=True)
    (Path(live_dir) / "latest_articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if skip_llm:
        report["error"] = "LLM 군집화를 건너뛰었습니다. 기존 트렌드를 유지합니다."
        return report

    try:
        trends = cluster_trends(
            articles,
            model=model or _load_model_name("configs/trend_demo.yaml"),
            window_days=window_days,
        )
    except (RuntimeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    report["path"] = str(save_live_payload(trends, articles, collection=debug, live_dir=live_dir))
    report["clustered"] = True
    report["trends"] = len(trends.get("trends", []))
    report["model"] = trends.get("model")
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
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
