# Hanwha Financial Trend Radar

금융시장 Signal과 관련 Evidence를 연결하고, 보험·증권·자산운용 관점에서 추가 확인할
Check Point를 제공하는 Trend Intelligence Prototype

> **PROTOTYPE · SNAPSHOT MODE** — 이 Prototype은 분석 Workflow와 UX 검증을 위해
> Representative Snapshot Dataset을 사용합니다. 실시간 시장 데이터나 투자정보가 아닙니다.

---

## Project Goal

이례적인 금융 Signal을 포착하고, 관련 Evidence를 검색·요약한 뒤,
**보험 / 증권 / 자산운용 관점에서 추가로 확인할 항목**을 제시합니다.

```
Market Signal → Evidence Retrieval → AI Brief → Business Lens → Check Points
```

핵심 가치는 "금리가 얼마나 움직였는가"를 알려주는 것도, "우리 회사 손익이 얼마나
변한다"를 판정하는 것도 아닙니다. **금융정보 탐색에 드는 시간을 줄이고, 업무 관점별로
무엇을 더 확인해야 하는지 짚어주는 것**입니다.

> 이 도구는 회사별 손익 영향, 긍정·부정 방향, 민감도를 **확정적으로 판정하지 않습니다.**
> 검토 관점과 모니터링 포인트를 제시하는 데까지가 범위입니다.

---

## Architecture

```
Snapshot Signal (JSON)
        │
        ▼
Evidence Retrieval  ── data/demo_corpus (26 docs) → indexes/demo_trends/index.json
   BM25 + soft query + RRF, 회사 필터 없음
        │
        ▼
Evidence (5건, data_mode = demo_snapshot)
        │
        ▼
AI Brief  ── rag_finance/llm/trend_analyzer.py
   LLM 생성:  trend_summary / causes / impact_summary / insight / transmission_paths
   Profile 주입: check points, key_metrics, watchpoints (relevance·direction 포함, 화면 미표시)
        │
        ▼
Business Lens  ── 보험 / 증권 / 자산운용 관점별 Check Points
        │
        ▼
Streamlit Dashboard  ── app/streamlit_app.py
```

### AI 사용 범위

화면의 어떤 부분이 AI 생성물이고 어떤 부분이 아닌지 대시보드 상단 legend와 섹션별
마커로 표시합니다. 네 갈래로 구분됩니다.

| 구분 | 대상 | 생성 주체 |
|---|---|---|
| **Snapshot** | Signal 수치(metric / weekly change / z-score / direction), headline | Representative Snapshot Dataset |
| **검색 선별** | Evidence 5건 | BM25 + RRF 검색 — LLM 아님 |
| **Profile 기준** | Check Points, Key Metrics, Watchpoints | Company Profile (사람이 정의) |
| **AI 생성** | trend_summary, causes, impact_summary, insight | LLM |

`DEMO_MODE=true`에서 AI 생성물은 **사전에 생성하고 검증한 cached output**이며 화면을 열
때 실시간으로 생성하지 않습니다. 현재 모드는 대시보드 하단 "이 화면의 AI · Snapshot
범위"에 `metadata.analysis_mode` 값으로 그대로 노출됩니다.

AI는 투자 추천·매수/매도 의견·목표가를 생성하지 않습니다 (`metadata.investment_advice = false`).
모든 LLM 출력은 JSON schema 검증과 Profile grounding을 통과해야 사용됩니다.

`relevance` / `direction` 필드는 Profile 데이터에 남아 있지만 **화면에는 표시하지
않습니다.** 영향도를 자동 판정하는 도구라는 인상을 주지 않기 위한 의도적 선택입니다.

### Source of Truth 규칙

`relevance`와 `direction`은 **LLM이 생성하지 않습니다.** 각 회사 Profile의 해당 signal
category exposure에서 직접 읽어 최종 JSON에 주입합니다. 주입은
`rag_finance/profiles/loader.py:apply_profile_exposure()` 한 곳에서만 일어나며,
cached path(`DEMO_MODE=true`)와 live path(`DEMO_MODE=false`), Streamlit dashboard가
모두 같은 함수를 통과하므로 최종 schema가 동일합니다.

LLM이 만들어낸 `transmission_paths`는 `_validate_profile_grounding()`이 Profile에 정의된
경로의 부분집합인지 검증하며, 위반 시 예외로 실패합니다.

---

## Snapshot Mode / Live Mode

**Snapshot Mode** (`DEMO_MODE=true`, 기본값)
- Snapshot corpus를 **실제로 검색**하고, 사전에 생성·검증된 cached AI Brief를 사용합니다
- API key나 네트워크가 필요 없습니다 — 안정적인 Prototype 시연이 목적입니다

**Live Mode** (`DEMO_MODE=false`)
- 동일한 Retrieval Evidence를 LLM에 전달해 동적으로 분석할 수 있습니다
- `GROQ_API_KEY`가 필요하며, **현재 시연에서는 사용하지 않습니다**

두 경로 모두 Profile 주입 지점을 공유하므로 결과 schema는 같습니다.

---

## 3 Signals

| Signal ID | Category | Metric | Weekly Change | Z-score |
|---|---|---|---|---|
| `US10Y_SAMPLE` | `interest_rate` | US Treasury 10Y | −23 bp | −2.2 |
| `VIX_SPIKE` | `volatility` | CBOE Volatility Index (VIX) | +10.8 pts | +2.6 |
| `USDKRW_MOVE` | `fx` | USD/KRW | +32.4 KRW | +2.1 |

## 3 Business Lenses

| 관점 | PoC 대상 | Profile |
|---|---|---|
| 보험 관점 | 한화생명 | `profiles/hanwha_life.yaml` |
| 증권 관점 | 한화투자증권 | `profiles/hanwha_investment.yaml` |
| 자산운용 관점 | 한화자산운용 | `profiles/hanwha_asset_management.yaml` |

각 Profile은 signal category별로 `transmission_paths`(화면의 Check Points), `key_metrics`,
`watchpoints`, `source_status`를 가집니다. `relevance` / `direction` /
`positive_factors` / `negative_factors`도 데이터에는 남아 있으나 화면에 표시하지 않습니다.

현재 모든 exposure의 `source_status`는 `TODO_VERIFY`이며, IR 등 공개자료로 검증되기
전까지 Prototype 가정으로만 다룹니다.

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
Brand bar             로고 + PROTOTYPE / SNAPSHOT MODE badge
Snapshot 고지 + Provenance legend   AI 생성 / Profile 기준 / Snapshot / 검색 선별
Signal Selector       [ 금리 ↓ ] [ VIX ↑ ] [ USD/KRW ↑ ]
What's Trending?      headline + metric chip, Weekly Change(hero) / Z-score / Direction
AI Brief              1~2문장 요약
Business Lens         3개 카드 (관점 라벨 · 한 줄 요약 · Check Points · Key Metrics · AI Brief)
Key Watchpoints       관점별 모니터링 항목
주요 관련 요인          함께 확인할 관련 요인 3개
Evidence              관련 Evidence 5건 (접힘)
이 화면의 AI · Snapshot 범위   분석 모드·모델·생성 범위 고지 (접힘)
```

---

## 현재 구현

- Snapshot Signal 3종 (US10Y / VIX / USD/KRW)
- Trend Retrieval (BM25 + RRF, 회사 필터 없음)
- Evidence 표시 (5건, `data_mode = demo_snapshot`)
- AI Brief (사전 생성·검증된 cached output, Groq live path 보존)
- Business Lens (보험 / 증권 / 자산운용 관점별 Check Points)
- Streamlit Dashboard (단일 페이지)

## 현재 구현하지 않은 기능 (Future Expansion)

- 실시간 크롤링
- 실제 뉴스 API
- FRED / ECOS 연동
- Signal Threshold 기반 Trigger Alert
- 담당부서 Routing
- PDF Brief 생성
- Company Profile의 IR 기반 검증 (`TODO_VERIFY` → `VERIFIED`)

## Current Limitations

- 모든 Signal·Evidence·수치는 **Representative Snapshot Dataset**이며 실시간 수집
  기능이 없습니다.
- Company Profile의 exposure는 전부 `TODO_VERIFY` 상태로, 실제 민감도·포지션·규모를
  반영하지 않습니다.
- 회사별 손익 영향과 영향 방향을 **판정하지 않습니다.** 확인할 항목을 제시하는 데까지가
  범위입니다 (`metadata.investment_advice = false`).
- Signal 3개, 업무 관점 3개, 카테고리 3개(`interest_rate` / `volatility` / `fx`)로
  한정됩니다.
- Evidence는 Snapshot corpus 26건에서 검색되며 외부 뉴스·공시와 연결돼 있지 않습니다.

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
