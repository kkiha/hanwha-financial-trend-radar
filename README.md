# Hanwha Global Finance Radar

글로벌 금융 흐름을 압축하는 AI 트렌드 브리핑

최근 7일 동안의 글로벌·국내 금융뉴스를 자동으로 수집하고, AI가 유사 기사를 주요 트렌드로
군집화한 뒤, 이번 주 주목할 변화 3건과 관련 근거를 보여주는 Prototype입니다.

```
최근 7일 RSS 수집 → 기사 정규화·중복 제거 → Groq 주제 군집화
→ 트렌드별 기사 연결 → Runtime Company Profile 기반 관련성 분류
→ 회사별 Intelligence Brief 생성 → 기사 수·출처 수·최근 집중도 계산
```

핵심 가치는 깊은 투자분석이나 계열사 손익 예측이 아닙니다. **수십 건의 금융정보를 사람이
일일이 읽기 전에, AI가 이번 주 부상한 주제와 관련 근거를 압축해 보여주는 것**입니다.

## 실행

```powershell
# 메인 앱 — Global Finance Radar
streamlit run app/trend_feed_app.py

# 최신 데이터 수집 + 트렌드 재생성 (GROQ_API_KEY 필요)
python -m scripts.refresh_trend_feed

# 진단용: 트렌드까지만 생성하고 회사 관련성 분류 생략
python -m scripts.refresh_trend_feed --skip-relevance

# 진단용: 관련성까지만 생성하고 회사별 Brief 생략
python -m scripts.refresh_trend_feed --skip-briefs

# 수집만 (API key 없이 동작 확인)
python -m scripts.refresh_trend_feed --skip-llm

# RSS 검색 소스 선택 (기본값 profiles)
python -m scripts.refresh_trend_feed --skip-llm --source-mode common
python -m scripts.refresh_trend_feed --skip-llm --source-mode both

# 테스트
python -m unittest discover -s tests -t .
```

앱 안의 `최신 데이터 불러오기` 버튼도 같은 수집·분석을 수행합니다.
브라우저는 자동으로 열리지 않습니다 — http://localhost:8501 을 직접 여세요.

신규 앱의 기본 RSS 모드는 세 Runtime Company Profile의 한국어·영어 검색어 24개를 사용하는
`profiles`입니다. 기존 공통 금융 검색어는 `common`, 두 종류를 함께 쓰려면 `both`를 사용합니다.
프로파일 쿼리로 수집된 기사는 후보 회사·감시주제·쿼리 ID를 가지며, 이는 회사 관련성 확정
결과가 아닙니다.

## 상태 배지

| 배지 | 의미 |
|---|---|
| `LIVE` | 24시간 이내의 마지막 성공 결과 |
| `CACHED` | 그보다 오래된 직전 성공 결과 |
| `DEMO` | 저장소에 포함된 합성 예시 (`data/demo_outputs/trend_feed_fallback.json`) |

`GROQ_API_KEY`가 없으면 RSS 수집까지만 수행하고 기존 결과를 유지합니다. 네트워크·RSS·Groq
오류가 나도 앱이 죽지 않고 직전 결과를 그대로 보여줍니다. 화면 헤더는 표시 중인 데이터의
생성 시각과 최근 갱신 시도의 시각·성공 여부를 분리해 보여줍니다. 최근 시도 상태와 안전한
LLM 진단 정보는 `data/live/latest_refresh.json`에 기록됩니다.
회사 관련성 결과는 트렌드 파일과 분리된
`data/live/latest_company_relevance.json`에 저장됩니다. 3사를 순차 호출한 뒤, 한 회사가
검증에 실패해도 이미 성공한 다른 회사의 결과까지 버리지 않습니다 — 상태는 3사 모두 성공하면
`CLASSIFIED`, 일부만 성공하면 `PARTIAL`(성공한 회사만 evaluations에 포함), 전부 실패하면
`UNCLASSIFIED`입니다. Brief 생성 단계도 관련성이 `CLASSIFIED` 또는 `PARTIAL`이면 진행하며,
관련성이 없는 회사는 결과 배열에서 자연히 빠지고 UI가 이를 "생성 결과에 데이터가 없습니다"로
안내합니다.
회사별 Brief는 `data/live/latest_company_briefs.json`에 별도로 저장되며, Brief 생성만
실패하면 트렌드와 관련성 결과를 유지합니다.

## 현재 구현

- 최근 7일 글로벌·국내 RSS 수집 (금리·물가·유동성 / 시장위험·자금 흐름 / 금융규제·디지털금융)
- URL·유사 제목 기반 중복 제거
- Groq Strict Structured Outputs 기반 트렌드 군집화
  (정확히 3건, 기사 ID 검증, 업무 태그 whitelist, 형식 오류·일시적 API 오류 자동 재시도)
- Runtime Company Profile 기반 트렌드×회사 관련성 분류
  (회사별 순차 호출, `high / medium / low / none`, 회사별 주제·태그 및 근거 기사 ID 검증)
- 관련성 입력은 트렌드당 서로 다른 출처·최신순 기준 대표 기사 최대 3건과 축약 프로필만 사용
- `high + strong/moderate` 기반 회사별 Main Brief와 코드 기반 Monitoring Item 생성
- 기사 수·고유 출처 수·최근 48시간 집중도·일별 기사량을 **코드에서 계산**
- Trend Feed UI (Hero + 2·3위 카드 + Trend Detail + Methodology)
- Live / Cached / Demo fallback

LLM 모델·temperature·출력 토큰·입력 기사 수·reasoning effort·재시도 설정은
`configs/trend_demo.yaml`의 `llm` 섹션을 단일 기준으로 사용합니다. 트렌드 생성은
`max_tokens`, 회사별 관련성 분류는 기본값 1200인 `relevance_max_tokens_per_company`,
Brief는 기본값 4000인 `brief_max_tokens`를 사용합니다. 관련성 호출은 `reasoning_effort=low`와
Strict Structured Output을 사용하며, 429 응답은 `retry-after`를 우선해 실패한 회사만 한 번
재시도합니다.

## 구현하지 않은 것

- 기사 본문 전체 크롤링 — RSS가 주는 제목·출처·발행시각·URL·짧은 설명까지만 사용합니다
- 범용 웹 크롤러
- 계열사 손익 영향 분석
- 투자 추천
- 완전한 실시간 스트리밍
- 미래 사건 예측
- 생산환경용 데이터 거버넌스

## AI가 하는 일과 하지 않는 일

LLM은 기사를 3개 주제로 묶고 한국어 요약 문장을 씁니다. **화면의 모든 숫자는 코드에서
계산합니다** — 기사 수, 출처 수, 48시간 집중도, 일별 차트, 우선순위 모두. "전주 대비 N%
증가"처럼 과거 데이터 없이 검증할 수 없는 수치는 표시하지 않습니다.

우선순위 = `0.5 × 기사 수 비중 + 0.3 × 출처 수 비중 + 0.2 × 최근 48시간 비중`.
기사 수만으로 정렬하면 한 통신사의 재배포가 순위를 지배합니다.

관련 업무는 장문 분석이 아니라 정해진 목록 안의 짧은 태그로만 표시하며, 목록 밖의 태그는
제거합니다.

## UI 목업 (`ui_mockup/`)

팀원이 실제 Python/Streamlit 프로젝트를 실행하지 않고도 디자인만 자유롭게 수정할 수 있도록,
현재 화면 구조를 그대로 옮긴 standalone HTML을 별도로 두었습니다.

```
ui_mockup/
  ui-mockup.html      더블클릭으로 바로 열리는 정적 HTML (서버·Python 불필요)
  assets/hanwha_logo.png
```

CSS·JS는 전부 파일 내부에 있고 외부 CDN·npm 의존성이 없습니다. 데이터는 backend와 연결되지
않은 정적 샘플이며, Company Intelligence 탭은 Main Brief만 있는 경우 / Monitoring만 있는
경우 / 둘 다 있는 경우 세 가지 상태를 각각 다른 회사에 담아 한 화면에서 비교할 수 있게
했습니다. 이 파일을 고치는 것은 실제 앱 코드(`app/trend_feed_app.py`)에 영향을 주지 않으며,
반대로 실제 앱 코드를 고쳐도 이 목업은 자동으로 갱신되지 않습니다.

---

# Legacy — Hanwha Financial Trend Radar (Signal Radar)

아래는 이전 단계의 Signal Radar Prototype입니다. **삭제하지 않고 보존**되며 독립적으로
실행할 수 있습니다.

```powershell
streamlit run app/streamlit_app.py
```

금융시장 Signal과 관련 Evidence를 연결하고, 보험·증권·자산운용 관점에서 추가 확인할
Check Point를 제공합니다.

> **PROTOTYPE · SNAPSHOT MODE** — 이 Prototype은 분석 Workflow와 UX 검증을 위해
> Representative Snapshot Dataset을 사용합니다. 실시간 시장 데이터나 투자정보가 아닙니다.

---

## Project Goal (legacy)

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

# 3. Legacy Signal Radar dashboard
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
