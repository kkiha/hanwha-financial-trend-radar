# Executive briefing UI migration

Approved reference: `ui_mockup/executive-briefing-concept.html` (revision 02).

## 1. Baseline and architecture
- [x] Inspect the current app, approved concept, data loader and tests.
- [x] Preserve existing uncommitted work and the independent concept file.
- [x] Use a Streamlit component for the approved layout, backed by the existing loader and refresh pipeline.
- [x] Keep ingestion, ranking, relevance, brief selection and persisted JSON schemas unchanged.

## 2. Implementation
- [x] Compact header, number-free radar, actual KPI counts and refresh control.
- [x] Three trend rows; independent evidence buttons with article/source counts.
- [x] Company preview, three-company overview and full company brief detail.
- [x] Retain weekly summary fallback and distinguish unavailable from empty results.
- [x] Evidence drawer with full summaries, dated sources, safe external links and keyboard dismissal.
- [x] Group/company report preview, standalone HTML download and print layout.
- [x] Local licensed Pretendard; responsive typography matching the concept.
- [x] Refresh success/partial/failure feedback; retain old results while refreshing.

## 3. Verification
- [x] Python UI contract tests for LIVE/CACHED/DEMO, company states and refresh behavior.
- [x] Full unittest suite, without changing business assertions to mask failures.
- [x] Browser review at 1440px and 1366/1600px; compare with the approved concept.
- [x] Browser review at 768/390/320px; no horizontal overflow.
- [x] Company/trend selection, evidence independent of company data, Escape/focus return.
- [x] Report download and one-page print checks using the current data.
- [x] Browser refresh integration using a controlled fixture (no extra LLM calls).
- [x] Check hostile text/URLs, empty trends and failed company state.
- [x] Final diff review and backend invariance check.

## Verification log
- Baseline: existing app uses long stacked sections; the approved concept uses compact rows and a company preview.
- Installed runtime: Streamlit 1.63.0, with native components v2 support. Runtime requirement will be made explicit.


## Final verification (2026-09-07)
- Python suite: 182 tests passed. Existing collection, ranking, relevance and brief-generation modules were not changed.
- Browser: real Streamlit component callbacks verified with success / partial / exception fixtures; previous trends remain visible.
- States: three company brief combinations, one unavailable company, DEMO, empty trends, missing companies, hostile text/URLs.
- Evidence: all articles remain accessible, independent evidence button, Escape dismissal and focus return.
- Viewports: 1600, 1440, 1366, 768, 390 and 320px; no horizontal overflow or JavaScript errors.
- Report: fixture export plus actual saved-data group/company HTML exports each rendered as one A4 page. Longer future content may need additional pagination review.
- Actual saved-data desktop/mobile/evidence screenshots: `data/ui_review/app/live-*.png`.
- Runtime fixes during review: component registration moved out of resource cache; script strict-mode issue fixed; Korean source encoding verified.
- Test harness issue: the first browser refresh callback escaped its temporary mock and attempted real RSS collection. Collection failed before article/analysis writes. Only `data/live/latest_refresh.json` was updated at 15:32 KST; existing articles, trends, relevance and briefs retained their earlier timestamps. This record is preserved honestly rather than replaced with an invented successful result. No LLM stage ran.
- Harness corrected: fake refresh now remains installed across Streamlit pre-run callbacks in a separate server process. Stored live JSON hashes are compared before/after verification to detect unintended writes.

## Run / review
- Install `requirements.txt` (Streamlit >=1.63,<2 is required for the native component API).
- Run `.venv\Scripts\python.exe -m streamlit run app/trend_feed_app.py`.
- Unit checks: `.venv\Scripts\python.exe -m unittest discover -s tests -t .`.
- Browser checks: `.venv\Scripts\python.exe scripts/verify_briefing_ui.py` (Playwright and local Chrome required only for verification).
- Frontend source: `app/frontend/briefing.html`, `briefing.css`, `briefing.js`; UI data shaping: `app/briefing_view.py`.
- Approved standalone mockup remains available separately. No deployment or push performed.
