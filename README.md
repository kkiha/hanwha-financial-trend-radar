# Hanwha Financial Trend Radar

글로벌 금융 시그널을 한화 금융계열사별 관점으로 해석하는 RAG 기반 Trend Intelligence Prototype

> **PROTOTYPE · SNAPSHOT MODE** — 이 저장소의 모든 시장 데이터와 Evidence는 시연용
> 합성 Snapshot입니다. 실시간 시장 데이터나 투자정보가 아닙니다.

---

## Project Goal

같은 금융 Signal이라도 보험·증권·자산운용은 서로 다른 사업구조를 통해 영향을 받습니다.
Trend Radar는 범용 금융 Signal 하나를 입력받아 **한화생명 / 한화투자증권 / 한화자산운용**
각각의 전달 경로(transmission path)와 긍정·부정 요인으로 분해해 보여줍니다.

핵심 질문은 "금리가 얼마나 움직였는가"가 아니라
**"그 움직임이 우리 계열사 각각에게 무엇을 의미하는가"** 입니다.

---

## Architecture

```
Snapshot Signal (JSON)
        │
        ▼
Trend Retrieval  ── data/demo_corpus (26 docs) → indexes/demo_trends/index.json
   BM25 + soft query + RRF, 회사 필터 없음
        │
        ▼
Evidence (5건, data_mode = demo_snapshot)
        │
        ▼
Structured AI Insight  ── rag_finance/llm/trend_analyzer.py
   LLM 생성:  trend_summary / causes / impact_summary / insight / transmission_paths
   Profile 주입: relevance / direction / positive·negative_factors / key_metrics / watchpoints
        │
        ▼
Streamlit Dashboard  ── app/streamlit_app.py
```

### AI 사용 범위

화면의 어떤 부분이 AI 생성물이고 어떤 부분이 아닌지 대시보드 상단 legend와 섹션별
마커로 표시합니다. 네 갈래로 구분됩니다.

| 구분 | 대상 | 생성 주체 |
|---|---|---|
| **Snapshot** | Signal 수치(metric / weekly change / z-score / direction), headline | 고정 합성 데이터 (사람이 작성) |
| **검색 선별** | Evidence 5건 | BM25 + RRF 검색 — LLM 아님 |
| **Profile 기준** | relevance, direction, 긍정·부정 요인, transmission paths, key metrics, watchpoints | Company Profile (사람이 정의) |
| **AI 생성** | trend_summary, causes, impact_summary, insight | LLM |

`DEMO_MODE=true`에서 AI 생성물은 **사전에 생성하고 검증한 cached output**이며 화면을 열
때 실시간으로 생성하지 않습니다. 현재 모드는 대시보드 하단 "이 화면의 AI 사용 범위"에
`metadata.analysis_mode` 값으로 그대로 노출됩니다.

AI는 투자 추천·매수/매도 의견·목표가를 생성하지 않습니다 (`metadata.investment_advice = false`).
모든 LLM 출력은 JSON schema 검증과 Profile grounding을 통과해야 사용됩니다.

### Source of Truth 규칙

`relevance`와 `direction`은 **LLM이 생성하지 않습니다.** 각 회사 Profile의 해당 signal
category exposure에서 직접 읽어 최종 JSON에 주입합니다. 주입은
`rag_finance/profiles/loader.py:apply_profile_exposure()` 한 곳에서만 일어나며,
cached path(`DEMO_MODE=true`)와 live path(`DEMO_MODE=false`), Streamlit dashboard가
모두 같은 함수를 통과하므로 최종 schema가 동일합니다.

LLM이 만들어낸 `transmission_paths`는 `_validate_profile_grounding()`이 Profile에 정의된
경로의 부분집합인지 검증하며, 위반 시 예외로 실패합니다.

---

## Demo Mode

`DEMO_MODE=true`(기본값)는 Snapshot corpus를 **실제로 검색**하되 검증된 cached LLM JSON을
사용합니다. API key나 네트워크가 필요 없습니다.

`DEMO_MODE=false`는 같은 Retrieval 결과와 Profile을 Groq structured-analysis prompt에
전달하며 `GROQ_API_KEY`가 필요합니다. 두 경우 모두 relevance/direction은 Profile에서
주입되므로 결과 schema는 같습니다.

---

## 3 Signals

| Signal ID | Category | Metric | Weekly Change | Z-score |
|---|---|---|---|---|
| `US10Y_SAMPLE` | `interest_rate` | US Treasury 10Y | −23 bp | −2.2 |
| `VIX_SPIKE` | `volatility` | CBOE Volatility Index (VIX) | +10.8 pts | +2.6 |
| `USDKRW_MOVE` | `fx` | USD/KRW | +32.4 KRW | +2.1 |

## 3 PoC Companies

| Company | Business Type | Profile |
|---|---|---|
| 한화생명 | 생명보험 | `profiles/hanwha_life.yaml` |
| 한화투자증권 | 증권 | `profiles/hanwha_investment.yaml` |
| 한화자산운용 | 자산운용 | `profiles/hanwha_asset_management.yaml` |

각 Profile은 signal category별로 `relevance`, `direction`, `positive_factors`,
`negative_factors`, `transmission_paths`, `key_metrics`, `watchpoints`, `source_status`를
가집니다. 현재 모든 exposure의 `source_status`는 `TODO_VERIFY`이며, IR 등 공개자료로
검증되기 전까지 Prototype 가정으로만 다룹니다.

---

## Run Command

```powershell
# 1. Snapshot trend index 구축
python -m scripts.build_demo_index --config configs/trend_demo.yaml

# 2. CLI 파이프라인 1건 실행 (API key 불필요)
$env:DEMO_MODE="true"
python -m scripts.run_trend_sample --signal data/sample_signals/us10y_drop.json

# 3. Dashboard
streamlit run app/streamlit_app.py

# 4. 3개 Signal 전체 artifact + Profile grounding 검증
python -m scripts.validate_demo_artifacts

# 5. 테스트
python -m unittest discover -s tests -t .
```

### Dashboard 화면 구조

```
Brand bar            로고 + PROTOTYPE / SNAPSHOT MODE badge
Demo 고지 + Provenance legend   AI 생성 / Profile 기준 / Snapshot / 검색 선별
Signal Selector      [ 금리 ↓ ] [ VIX ↑ ] [ USD/KRW ↑ ]
What's Trending?     headline + metric chip, Weekly Change(hero) / Z-score / Direction
AI Trend Summary     1~2문장 요약
Company Impact       3개 카드 (badge · 한 줄 요약 · ＋/－ 요인 · 경로 chip · 지표 chip · insight)
What to Watch        회사별 watchpoints
Why Did It Move?     핵심 원인 3개
Evidence             근거 Snapshot 5건 (접힘)
이 화면의 AI 사용 범위  분석 모드·모델·생성 범위 고지 (접힘)
```

---

## Current Limitations

- 모든 Signal·Evidence·수치는 **합성 Snapshot**이며 실시간 수집 기능이 없습니다.
- Company Profile의 exposure는 전부 `TODO_VERIFY` 상태로, 실제 민감도·포지션·규모를
  반영하지 않습니다.
- 투자 추천이나 상품·성과에 대한 판단을 생성하지 않습니다 (`metadata.investment_advice = false`).
- Signal 3개, 회사 3개, 카테고리 3개(`interest_rate` / `volatility` / `fx`)로 한정됩니다.
- Evidence는 Snapshot corpus 26건에서 검색되며 외부 뉴스·공시와 연결돼 있지 않습니다.

## Future Expansion

- 실제 최신 데이터 자동수집 (RSS / API / FRED / ECOS)
- Signal Threshold 기반 Trigger Alert
- 담당부서 Routing
- PDF Brief 생성
- Real-time update 및 Signal 카테고리 확장
- Company Profile의 IR 기반 검증 (`TODO_VERIFY` → `VERIFIED`)

---

## Reused Retrieval Asset (based on previous RAG engine)

이 Prototype은 기존 `rag-finance` 프로젝트(RAG 기반 증권 리포트 자동화)의 Retrieval
자산 위에 구축했습니다. 아래 구성요소는 **변경 없이 보존**되며 Trend Radar는 별도 경로를
사용합니다.

| 보존 자산 | 설명 |
|---|---|
| `rag_finance/retrieval/pipeline.py:retrieve_with_keywords()` | 기업 질의용 하이브리드 검색 진입점 |
| `indexes/all/` | `jhgan/ko-sroberta-nli` 기반 회사 문서 FAISS 인덱스 |
| `rag_finance/indexing`, `rrf.py`, `reranker_ce.py`, `mmr.py`, `hybrid.py` | BM25 + FAISS + RRF + Cross-Encoder + MMR 랭킹 |
| `rag_finance/llm/report_generator.py`, `scripts/generate_report.py` | 기존 리포트 생성 CLI (`[Title]/[Summary]/[Analysis]/[Opinion]/[Table]`) |
| `keyword_json/`, `tabular_db/` | 회사별 키워드 및 재무·주가 요약 JSON |

기존 엔진의 파이프라인은 `ingestion → chunking(800/100) → FAISS 인덱싱 →
BM25/FAISS 하이브리드 검색 → Cross-Encoder 재랭킹 → MMR → Groq 리포트 생성`이며,
리포트 CLI는 다음과 같이 실행합니다.

```powershell
python -m scripts.build_index --config configs/default.yaml
python -m scripts.generate_report `
   --config configs/default.yaml `
   --q "삼성전자의 최근 동향에 대한 한국어 리포트를 작성해 줘." `
   --topk 10 --model llama-3.3-70b-versatile `
   --output reports/samsung_latest.txt --tabular-dir tabular_db
```

Trend Radar는 회사 필터를 적용하지 않는 별도 Snapshot 인덱스
(`indexes/demo_trends/index.json`)를 사용하므로 위 경로와 간섭하지 않습니다.

> 참고: 용량 문제로 `data/raw/**` 원문 텍스트는 Git 저장소에 포함되지 않습니다.
> 기존 리포트 파이프라인을 재현하려면 데이터를 직접 배치한 뒤 `build_index`를 실행하세요.
> Trend Radar Demo는 저장소에 포함된 `data/demo_corpus`만으로 동작합니다.
