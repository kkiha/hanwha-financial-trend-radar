# Hanwha Financial Trend Radar
## Self-Contained Agent Specification for Claude Code / Codex

---

> **⚠ ARCHIVED — 이 문서는 Signal Radar(`app/streamlit_app.py`) 단계의 계획 문서다.**
>
> 프로젝트는 이후 **Hanwha Global Finance Radar**(`app/trend_feed_app.py`)로 다시
> 확장됐다 — 실제 RSS 자동수집, Groq 트렌드 군집화, Runtime Company Profile 기반
> 회사 관련성 분류, 회사별 Company Intelligence Brief까지 포함한다. 이 아래 내용
> (Day 1~4 빌드 플랜, Business Lens, Scope Guardrail 등)은 **그 이전 단계의 기록으로
> 보존**하며, 지금 무엇이 구현돼 있는지는 이 문서가 아니라 다음을 기준으로 삼는다.
>
> - [`README.md`](README.md) — 두 앱 모두의 현재 실행 방법과 구현 범위
> - [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) — Company Intelligence
>   파이프라인의 원칙과 진행 로그 (날짜별 append)
> - [`FEEDBACK_GUIDE.md`](FEEDBACK_GUIDE.md) / [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) —
>   현재 메인 프로덕트 기준 데모·피드백 가이드
>
> Signal Radar 자체는 삭제되지 않았고 `streamlit run app/streamlit_app.py`로 계속
> 실행할 수 있다. 아래 내용을 새 기능 판단 근거로 쓰지 말 것.

---

# 0. Executive Summary

이 문서는 Claude Code 또는 Codex가 **추가 설명 없이도 프로젝트 맥락을 이해하고, 기존 `rag-finance`를 기반으로 3일 내 피드백 가능한 Prototype을 구현하도록 하기 위한 자급자족형 작업 명세서**다.

> **제품 정의 갱신 (현행)** — PoC 기간과 검증 가능성을 고려해 제품의 주장을 아래
> 수준으로 낮췄다. 이 문서의 이후 서술 중 "회사별 영향 판정"을 전제한 부분보다
> 이 정의가 우선한다.
>
> "글로벌 금융시장의 이례적인 Signal을 포착하고, 관련 Evidence를 검색·요약한 뒤,
> 보험 / 증권 / 자산운용 관점에서 추가로 확인할 항목을 제시하는
> Trend Intelligence Briefing Tool"
>
> `Market Signal → Evidence Retrieval → AI Brief → Business Lens → Check Points`
>
> 시스템은 회사별 손익 영향, 긍정/부정 방향, 민감도를 확정적으로 판정하는 도구가 아니다.

## 프로젝트 한 줄 정의

**Hanwha Financial Trend Radar**는 글로벌 금융시장 Signal을 탐지하고, 관련 Evidence를 검색한 뒤, 동일한 Signal이 한화 금융계열사별로 어떤 의미를 가지는지 차등 해석하여 보여주는 AI 기반 Trend Intelligence Prototype이다.

핵심 흐름:

```text
Financial Signal
→ Evidence Retrieval
→ Hanwha Financial Company Profile
→ Company-specific AI Interpretation
→ Streamlit Dashboard
```

## 이번 Prototype의 목표

이번 목표는 완전 자동화 시스템이 아니다.

**3일차 공식 피드백 시간까지 실제로 시연 가능한 End-to-End Prototype을 확보하는 것**이 최우선이다.

따라서:

- 실제 데이터 자동수집은 최소화한다.
- 필요하면 Snapshot / Sample data를 사용한다.
- LLM 결과도 Demo 안정성을 위해 캐시할 수 있다.
- 기존 Retrieval Core는 최대한 재사용한다.
- 화려한 기술보다 “실제로 돌아가는 Demo”를 우선한다.

---

# 1. Original Assignment Context

과제 요구사항은 다음과 같다.

> 한화그룹의 주요 사업 도메인 중 하나를 선택하여 글로벌 최신 트렌드를 자동으로 수집하고 분석하는 시스템을 구축한다.

본 프로젝트에서는 **금융(Finance)** 도메인을 선택한다.

차별점은 단순 금융 트렌드 요약이 아니라:

> 동일한 글로벌 금융 Signal을  
> **한화생명 / 한화투자증권 / 한화자산운용**  
> 각 비즈니스 모델 관점에서 다르게 해석하는 것

이다.

## PoC 대상 계열사

- 한화생명
- 한화투자증권
- 한화자산운용

## PoC 핵심 Trend Category

- `interest_rate`
- `equity`
- `fx`
- `credit`
- `volatility`

---

# 2. Product Concept

사용자가 Dashboard에서 특정 Signal을 선택하면 다음 정보를 확인할 수 있어야 한다.

## 2.1 What's Trending?

예:

```text
US Treasury 10Y
Weekly Change: -23bp
Z-score: -2.2
Direction: DOWN
```

## 2.2 Why Did It Move?

관련 Evidence:

```text
- CPI 둔화
- 고용지표 약화
- Fed 완화적 발언
```

각 Evidence는 가능하면:

- title
- source
- date
- URL
- short excerpt

를 포함한다.

## 2.3 What Does It Mean for Hanwha?

동일 Signal을 세 계열사별로 다르게 표시한다.

예:

### 한화생명

```text
Relevance: HIGH
Direction: MIXED
Transmission:
- 채권 운용
- 재투자수익률
- ALM
```

### 한화투자증권

```text
Relevance: HIGH
Direction: POSITIVE
Transmission:
- Brokerage
- IB
- Fixed Income Trading
```

### 한화자산운용

```text
Relevance: HIGH
Direction: MIXED
Transmission:
- Bond Price
- Asset Allocation
- Fund Flow
```

---

# 3. Existing Repository Contract

## Source Repository

```text
https://github.com/kkiha/rag-finance
```

이 프로젝트를 기존 기반 코드로 사용한다.

## Important Rule

**원본의 핵심 Retrieval 구조를 갈아엎지 않는다.**

기존 `rag-finance`에는 이미 다음 구성요소가 존재한다.

- ingestion
- chunking
- FAISS indexing
- BM25 retrieval
- RRF fusion
- Cross-Encoder reranking
- MMR
- company metadata
- keyword expansion
- LLM report generation

## Preserve

가능하면 다음은 그대로 유지한다.

```text
rag_finance/indexing/
rag_finance/retrieval/rrf.py
rag_finance/retrieval/reranker_ce.py
rag_finance/retrieval/mmr.py
rag_finance/retrieval/hybrid.py
```

## Do Not Break

기존 기업 리포트용 함수:

```python
retrieve_with_keywords()
```

는 유지한다.

기존 report generation CLI도 가능한 한 동작 상태를 유지한다.

## New Function

Trend Retrieval용 신규 함수:

```python
retrieve_trend_evidence()
```

를 추가한다.

---

# 4. Current Architectural Gap

기존 Retrieval은 **기업 중심**이다.

현재 핵심 흐름은 대략 다음과 같다.

```text
query
→ company extraction
→ company keyword expansion
→ company entity filtering
→ BM25 + FAISS
→ RRF
→ CE/MMR
```

Trend Radar에서는 기업명이 없는 query도 정상 검색되어야 한다.

예:

```text
"미국 장기금리가 급락했다"
```

따라서 신규 Trend Retrieval에서는:

- company extraction 사용 금지
- company entity filter 사용 금지
- trend category 기반 keyword expansion
- BM25 + FAISS
- RRF
- 기존 CE/MMR 선택적 재사용

방식으로 구현한다.

---

# 5. Demo Data Contract

## Critical Problem

기존 `rag-finance`의 원본 `data/`는 Git에 포함되지 않을 수 있다.

따라서 기존 index가 없거나 사용 불가능할 가능성을 반드시 고려한다.

**이 문제 때문에 Prototype 구현이 막혀서는 안 된다.**

## Required Fallback

다음 Demo Corpus를 프로젝트에 포함한다.

```text
data/
└─ demo_corpus/
   ├─ interest_rate/
   ├─ equity/
   ├─ fx/
   ├─ credit/
   └─ volatility/
```

최초 Prototype은 `interest_rate` 카테고리만 있어도 된다.

예:

```text
data/demo_corpus/interest_rate/
├─ doc_001.txt
├─ doc_002.txt
├─ doc_003.txt
...
```

최소:

```text
10~20 documents
```

정도면 충분하다.

## Rule

기존 index가 사용 가능하면 재사용한다.

기존 index가 없으면:

```text
demo_corpus
→ ingestion
→ chunking
→ FAISS/BM25 index
```

를 자동 또는 명시적 command로 생성한다.

## Acceptance

Agent는 반드시 다음 두 상황 모두를 고려해야 한다.

### Case A

기존 index 존재:

```text
load existing index
```

### Case B

index 없음:

```text
build demo index from demo_corpus
```

---

# 6. Demo Signal Contract

Prototype에서는 실제 Market API 없이도 실행되어야 한다.

## Required Sample Signals

최소 3개를 준비한다.

```text
data/sample_signals/
├─ us10y_drop.json
├─ vix_spike.json
└─ usdkrw_move.json
```

예:

```json
{
  "signal_id": "US10Y_SAMPLE",
  "metric": "US Treasury 10Y",
  "category": "interest_rate",
  "current": 3.89,
  "weekly_change": -0.23,
  "weekly_change_unit": "percentage_point",
  "z_score": -2.2,
  "direction": "down",
  "headline": "미국 장기금리 급락",
  "data_mode": "demo_snapshot"
}
```

---

# 7. Company Profile Ownership Contract

## Critical Rule

Agent는 한화 계열사의 사업구조나 KPI를 임의로 창작해서는 안 된다.

Company Profile의 사실 정보는:

- 사용자가 제공
- 공개 IR/사업보고서 기반으로 별도 검증
- 또는 Placeholder

중 하나여야 한다.

## Initial Profile Strategy

Prototype 3일차까지는 최소 Profile만 사용한다.

```text
profiles/
├─ hanwha_life.yaml
├─ hanwha_investment.yaml
└─ hanwha_asset_management.yaml
```

예:

```yaml
company: 한화생명
business_type: 생명보험

market_exposures:
  interest_rate:
    relevance: high
    direction: mixed

    positive_factors:
      - 보유 채권 평가환경 개선

    negative_factors:
      - 신규 재투자수익률 하락
      - ALM 관점의 자산·부채 듀레이션 부담

    transmission_paths:
      - 채권 운용
      - 신규 재투자수익률
      - ALM

    key_metrics:
      - 운용수익률
      - ALM 관련 지표

    watchpoints:
      - 신규 투자수익률 변화
      - 자산·부채 듀레이션 갭

    source_status: TODO_VERIFY
```

`transmission_paths`, `key_metrics`, `watchpoints`는 비어 있을 수 없다.
`positive_factors`와 `negative_factors`는 한쪽이 비어 있을 수 있으나
(한 방향으로만 작용하는 exposure) 둘 다 비어 있을 수는 없다.

## Source of Truth

`relevance`와 `direction`은 **Company Profile이 소유한다.** LLM은 이 두 값을 생성하지
않으며, 시스템이 해당 signal category exposure에서 읽어 최종 JSON에 주입한다.

주입 지점은 `rag_finance/profiles/loader.py:apply_profile_exposure()` 한 곳이며,
cached path·live path·Streamlit dashboard가 모두 이 함수를 통과해 동일한 최종 schema를
만든다. 주입 대상은 다음과 같다.

```text
relevance
direction
positive_factors
negative_factors
key_metrics
watchpoints
source_status
```

`transmission_paths`는 분석 결과에서 오되 `_validate_profile_grounding()`이 Profile에
정의된 경로의 부분집합인지 검증한다.

## Required Field

각 factual field에는 필요 시:

```text
source_status
```

를 둔다.

Allowed:

```text
VERIFIED
USER_PROVIDED
TODO_VERIFY
```

## Rule

`TODO_VERIFY` 내용은 LLM이 확장해서 사실처럼 서술하면 안 된다.

---

# 8. LLM Provider Contract

기존 `rag-finance`는 Groq 기반 LLM 호출을 사용할 수 있다.

Prototype에서는 **LLM Provider 교체 자체를 목표로 하지 않는다.**

## Rule

- 기존 Groq 호출부를 우선 재사용한다.
- OpenAI 등으로 갈아엎기 위해 시간을 쓰지 않는다.
- 단, `trend_analyzer.py`의 Prompt / Parsing 로직은 LLM provider와 과도하게 결합하지 않는다.

## Environment

예:

```text
GROQ_API_KEY
```

가 없을 경우 Demo는 실패하면 안 된다.

그 경우 Cached Output을 사용한다.

---

# 9. Demo Mode Contract

Demo Mode는 **P0 필수 기능**이다.

## Environment Variable

```text
DEMO_MODE=true
```

## DEMO_MODE=true

다음을 사용한다.

```text
Sample Signal
+
Frozen Evidence
+
Cached LLM Output
```

외부 API 없이도 Streamlit 전체 화면이 동작해야 한다.

## DEMO_MODE=false

가능한 경우 실제:

```text
Signal
→ Retrieval
→ LLM
```

을 실행한다.

## Suggested Structure

```text
data/
└─ demo_outputs/
   ├─ us10y_analysis.json
   ├─ vix_analysis.json
   └─ usdkrw_analysis.json
```

---

# 10. Trend Keyword Contract

Trend 기반 keyword expansion을 위한 파일을 둔다.

```text
trend_keywords/
├─ interest_rate.json
├─ equity.json
├─ fx.json
├─ credit.json
└─ volatility.json
```

예:

```json
{
  "category": "interest_rate",
  "hard_keywords": [
    "Federal Reserve",
    "Treasury yield",
    "FOMC",
    "금리",
    "국채"
  ],
  "soft_keywords": [
    "inflation",
    "CPI",
    "employment",
    "rate cut"
  ]
}
```

---

# 11. Required New Modules

권장 구조:

```text
rag_finance/
├─ signal/
│  ├─ __init__.py
│  ├─ loader.py
│  └─ schema.py
│
├─ entities/
│  └─ trend_maps.py
│
├─ retrieval/
│  └─ trend_pipeline.py
│
├─ llm/
│  └─ trend_analyzer.py
│
└─ profiles/
   └─ loader.py
```

Root:

```text
profiles/
trend_keywords/
data/sample_signals/
data/demo_corpus/
data/demo_outputs/
app/
```

---

# 12. Structured Output Contract

LLM Trend Analyzer는 자유 텍스트가 아니라 JSON을 반환한다.

## LLM Output Schema

LLM은 아래만 생성한다. `relevance`와 `direction`은 포함하지 않는다 (§7 Source of Truth).

```json
{
  "signal": {
    "metric": "",
    "category": "",
    "direction": "",
    "weekly_change": null,
    "z_score": null
  },
  "trend_summary": "",
  "causes": [],
  "companies": {
    "한화생명": {
      "impact_summary": "",
      "transmission_paths": [],
      "insight": ""
    },
    "한화투자증권": {
      "impact_summary": "",
      "transmission_paths": [],
      "insight": ""
    },
    "한화자산운용": {
      "impact_summary": "",
      "transmission_paths": [],
      "insight": ""
    }
  }
}
```

## Final Schema (Profile 주입 후)

`analyze_trend()` 및 dashboard payload가 소비하는 최종 회사 블록:

```json
{
  "relevance": "HIGH",
  "direction": "MIXED",
  "impact_summary": "",
  "positive_factors": [],
  "negative_factors": [],
  "transmission_paths": [],
  "key_metrics": [],
  "watchpoints": [],
  "source_status": "TODO_VERIFY",
  "insight": ""
}
```

cached path와 live path는 같은 주입 함수를 통과하므로 이 schema가 동일하게 보장된다.

## Allowed Enum

주입값 검증에 사용한다. LLM 출력 계약이 아니다.

### relevance

```text
HIGH
MEDIUM
LOW
```

### direction

```text
POSITIVE
NEGATIVE
MIXED
NEUTRAL
```

---

# 13. LLM Guardrails

Prompt에 다음 규칙을 포함한다.

1. Company Profile에 없는 사업구조를 임의 생성하지 않는다.
2. Evidence에 없는 사건을 만들지 않는다.
3. 근거 없는 숫자를 생성하지 않는다.
4. `relevance`와 `direction`은 생성하지 않는다 (Profile 주입).
5. 투자 추천, 매수/매도 의견을 만들지 않는다.
6. Profile의 `positive_factors` / `negative_factors`를 근거로 해석 문장을 작성한다.
7. JSON 외 텍스트를 출력하지 않는다.
8. 각 계열사 결과가 억지로 달라질 필요는 없지만, Profile에 근거한 차이는 반영한다.

## Insight Tone

Prototype 한계는 화면 상단 Demo/Snapshot 배너가 고지한다. 따라서 카드 내부
`insight` / `impact_summary`에는 "실제 민감도는 검증되지 않았다", "추가 사실로 확장하지
않는다", "특정 상품의 판단은 포함하지 않는다" 같은 반복 면책 문구를 쓰지 않는다.
Profile에 이미 존재하는 정보를 사람이 읽기 좋은 문장으로 푸는 수준으로 제한하며,
새로운 외부 사실을 추가하지 않는다.

---

# 14. Streamlit Contract

## Required Entry

```text
app/streamlit_app.py
```

## Required Section Order

Company Impact가 스크롤 없이 화면 상단에서 보이도록 아래 순서를 지킨다.

```text
1. Brand bar          로고 + PROTOTYPE / SNAPSHOT MODE badge
2. Snapshot 고지 + Provenance legend
3. Signal Selector    segmented control: [ 금리 ↓ ] [ VIX ↑ ] [ USD/KRW ↑ ]
4. What's Trending?   headline + metric chip / weekly change(hero) / z-score / direction
5. AI Brief           trend_summary 1~2문장
6. Business Lens      3-column 카드 (보험 / 증권 / 자산운용 관점)
7. Key Watchpoints    관점별 watchpoints (없으면 key_metrics)
8. 주요 관련 요인       함께 확인할 관련 요인 3개 (causes)
9. Evidence           Snapshot 5건, 기본 접힘
10. 이 화면의 AI · Snapshot 범위   분석 모드·모델·생성 범위 고지, 기본 접힘
```

`Company Impact`, `Why Did It Move?` 라는 표현은 사용하지 않는다. 전자는 영향 판정,
후자는 인과 확정을 주장한다.

Streamlit 기본 상단 헤더 바는 숨긴다. 콘텐츠 위에 겹쳐 떠서 brand bar를 가린다.

## Provenance Contract

화면의 모든 블록은 생성 주체를 표시한다. 상단 legend와 섹션 헤더 마커, 카드 내부
마커로 일관되게 노출한다.

```text
Snapshot      Signal 수치, headline          고정 합성 데이터
검색 선별      Evidence 5건                   BM25 + RRF (LLM 아님)
Profile 기준   relevance, direction, 요인,     Company Profile
              transmission paths, metrics,
              watchpoints
AI 생성        trend_summary, causes,          LLM
              impact_summary, insight
```

`metadata.analysis_mode`(`cached_llm_output` / `live_llm`)를 화면에 실제로 노출한다.
`cached_llm_output`은 사전 생성 후 검증된 출력이며 실시간 생성이 아니라는 점을 명시한다.

마커에는 brand orange를 쓰지 않는다. Orange accent 예산은 §Visual Identity가 정한
용도로만 쓴다.

## Stat Tile Contract

- Hero figure는 화면 전체에서 **정확히 하나**(Weekly Change)만 둔다.
- `metric`은 측정값이 아니라 개체 이름이므로 value가 아닌 eyebrow chip으로 표시한다.
- Direction에 빨강·초록을 쓰지 않는다. 좋고 나쁨을 색으로 부여하면 투자 판단 신호가
  되어 `investment_advice: false` 원칙과 충돌한다. 화살표 + 중립 잉크로 표시한다.

### Business Lens 카드 구성

```text
[보험 관점]                                            ← 관점 라벨
한화생명
한 줄 impact_summary                    [AI]          ← 카드에서 가장 눈에 띄는 문장
──────────────────────────────────────────
CHECK POINTS         〈chip〉〈chip〉〈chip〉           ← profile transmission_paths
KEY METRICS TO WATCH 〈chip〉〈chip〉                   ← 짧은 명사구는 chip
──────────────────────────────────────────
AI BRIEF                                 [AI]         ← 카드 하단 고정(3장 정렬)
```

### 화면에 표시하지 않는 것

`relevance`, `direction`, `positive_factors`, `negative_factors`는 Profile 데이터에
남아 있으나 **렌더링하지 않는다.** 영향도와 영향 방향을 자동 판정하는 도구라는 인상을
주지 않는 것이 이 화면의 요구사항이다.

카드 문구는 결과를 단정하지 않는다. 수익 증가·감소를 단정하지 않고, 회사의 실제
민감도를 안다고 표현하지 않으며, 검토 관점과 모니터링 포인트를 제공한다.

회사별 차이는 factor와 transmission path에서 즉시 드러나야 하며,
`direction` 값을 억지로 바꿔 차이를 만들지 않는다.

### Evidence

기본 접힘 상태(`st.expander`)로 표시한다. Snapshot 데이터라는 사실 자체는 숨기지 않되
카드마다 면책 문구를 반복하지 않는다. `demo://` URL은 사용자에게 의미가 없으므로
링크로 노출하지 않고 `document_id`만 caption에 표기한다.

각 항목: title / source / date / document_id / excerpt.

## Important

Multi-page는 구현하지 않는다.

한 페이지로 충분하다.

## Visual Identity

- Hanwha Orange `#F57E20`: 선택된 Signal, 핵심 숫자, badge 일부, 카드 상단 accent
- Dark Charcoal `#2B2B2B`: 제목 및 본문
- Warm Light Gray `#F7F5F3`: AI Trend Summary 배경
- White `#FFFFFF`: 전체 배경

Orange는 전체 UI의 약 10~15% 수준 accent로만 사용한다.

---

# 15. 4-Day Build Plan

## Day 1 — End-to-End CLI

### Goal

```text
Sample Signal
→ Trend Retrieval
→ Company Profile
→ LLM
→ Structured JSON
```

### TODO

- [ ] repository 분석
- [ ] existing index 확인
- [ ] demo_corpus fallback 확인
- [ ] sample signal loader
- [ ] profile loader
- [ ] trend keyword loader
- [ ] `retrieve_trend_evidence()`
- [ ] `trend_analyzer.py`
- [ ] JSON parser
- [ ] CLI

### Done

하나의 명령으로 JSON 결과가 생성된다.

---

## Day 2 — Streamlit

### Goal

저장된 JSON으로 화면을 만든다.

### TODO

- [ ] Streamlit one-page UI
- [ ] Signal selector
- [ ] Evidence section
- [ ] 3-company Impact cards
- [ ] Demo cached output loading
- [ ] empty/error state

### Done

```bash
streamlit run app/streamlit_app.py
```

로 화면이 뜬다.

---

## Day 3 — Feedback-ready Prototype

### Goal

공식 피드백 시연 가능.

### TODO

- [ ] Sample Signal 최소 3개
- [ ] 각 Signal별 Evidence
- [ ] 각 Signal별 Cached Output
- [ ] Company Profile 차별화 점검
- [ ] Demo Mode 완성
- [ ] UI 정리
- [ ] 1분 Demo Script 작성

### Done

인터넷 없이도 전체 Demo 가능.

Day 3 이후 신규 핵심 기능 추가 금지.

---

## Day 4 — Feedback Response (완료: Option C + D)

기능을 늘리지 않고 판단 정합성·표현력·정보 구조를 개선했다.

- relevance / direction의 Source of Truth를 Company Profile로 이관 (§7, §12)
- Company Profile exposure에 positive/negative factors, key_metrics, watchpoints 추가
- cached insight에서 반복 면책 문구 제거, `impact_summary` 추가
- Dashboard 정보 구조 재설계 — Company Impact를 Evidence 위로, Evidence는 접힘 (§14)
- AI Trend Summary / What to Watch 섹션 추가
- Hanwha 색상 체계 적용

---

# 15-A. 구현 범위 (Implemented vs Future)

문서와 구현의 정합성을 위해 아래를 명확히 구분한다.

## 현재 구현됨

- Sample / Snapshot Signal (3종: `interest_rate` / `volatility` / `fx`)
- Trend Retrieval (Snapshot corpus 26건, BM25 + RRF, 회사 필터 없음)
- Evidence 표시 (5건, `data_mode = demo_snapshot`)
- AI Brief (cached LLM output + live Groq path 보존)
- Business Lens (보험 / 증권 / 자산운용 관점별 Check Points, Profile 주입)
- Streamlit Dashboard (단일 페이지)

## 향후 확장 (미구현)

- 실시간 크롤링 및 최신 데이터 자동수집
- 실제 뉴스 API, FRED / ECOS 연동
- Signal Threshold 기반 Trigger Alert
- 담당부서 Routing
- PDF Brief 생성
- Real-time update
- Trend Detail 페이지

위 "향후 확장" 항목은 현재 저장소에 코드가 존재하지 않는다. 문서·데모·리포트에서
구현된 기능처럼 서술하지 않는다.

---

# 16. Acceptance Tests

## A. Repository

- [ ] 기존 기업 리포트용 코드 삭제 안 됨
- [ ] 기존 `retrieve_with_keywords()` 유지

## B. Demo

- [ ] `streamlit run app/streamlit_app.py` 성공
- [ ] Signal 최소 3개 선택 가능
- [ ] Signal 변경 시 Evidence 변경
- [ ] Evidence 최소 3개 표시
- [ ] 업무 관점 3개(보험 / 증권 / 자산운용) 모두 표시
- [ ] 각 관점의 Check Points 표시
- [ ] Business Lens가 Evidence보다 위에 표시
- [ ] Evidence는 기본 접힘
- [ ] 각 카드에 Check Points / Key Metrics / AI Brief 표시
- [ ] HIGH / MIXED 등 영향 판정 badge가 화면에 없음
- [ ] positive / negative 영향 판정 영역이 화면에 없음
- [ ] JSON parsing error 없음

## C. Reliability

- [ ] `DEMO_MODE=true`에서 외부 API 없이 실행
- [ ] LLM API Key 없어도 Demo 실행
- [ ] index가 없어도 Demo Corpus로 bootstrap 가능

## D. Data Safety

- [ ] Company Profile의 미검증 사실은 `TODO_VERIFY`
- [ ] AI가 새로운 KPI를 임의 생성하지 않음
- [ ] 투자 추천 출력 없음

---

# 17. Initial CLI Suggestions

## Build Demo Index

```bash
python -m scripts.build_demo_index
```

## Run Single Signal

```bash
python -m scripts.run_trend_sample --signal data/sample_signals/us10y_drop.json
```

## Run Streamlit

```bash
DEMO_MODE=true streamlit run app/streamlit_app.py
```

Windows PowerShell:

```powershell
$env:DEMO_MODE="true"
streamlit run app/streamlit_app.py
```

---

# 18. Git Strategy

## Suggested Repository

```text
hanwha-financial-trend-radar
```

## Initial Commit

```bash
git add .
git commit -m "chore: bootstrap from rag-finance"
```

## Suggested Branches

```text
feat/e2e-sample
feat/company-profiles
feat/trend-retrieval
feat/streamlit-dashboard
```

복잡한 Git Flow는 사용하지 않는다.

---

# 19. Scope Guardrail

P0 완료 전 아래를 구현하지 않는다.

- 대규모 웹 Scraper
- 실시간 Streaming
- Agent Framework
- 복잡한 Forecasting
- ML 기반 시장 예측
- GitHub Actions
- PDF generation
- Multi-page Dashboard
- 모든 한화 금융계열사
- 복잡한 Importance Score
- Portfolio Recommendation
- Investment Advice

---

# 20. Agent Working Protocol

Claude Code / Codex는 다음 순서를 반드시 따른다.

## Step 1

Repository를 먼저 분석한다.

아직 코드를 수정하지 않는다.

출력:

```text
1. 현재 구조
2. 재사용할 모듈
3. 수정할 모듈
4. 신규 모듈
5. Missing data/index
6. Day 1 파일 변경 계획
```

## Step 2

사용자에게 별도 확인이 꼭 필요한 Blocking Issue가 없으면 Day 1 구현을 시작한다.

## Step 3

각 Phase 완료 후 반드시 다음을 출력한다.

```text
Changed Files
Run Command
Test Result
Known Limitations
Next Step
```

## Step 4

항상 Demo 가능한 상태를 유지한다.

---

# 21. Agent Start Prompt

이 Repository에 이 파일이 존재한다면 Agent에게 아래만 입력해도 된다.

```text
PROJECT_SPEC.md를 먼저 끝까지 읽어라.

이 문서를 프로젝트의 단일 Source of Truth로 사용하라.

먼저 코드를 수정하지 말고 Repository를 분석하여
문서의 "Agent Working Protocol / Step 1" 형식으로 결과를 보고하라.

그 뒤 Blocking Issue가 없다면 Day 1 구현을 진행하라.

가장 중요한 목표는 3일차 공식 피드백 시간 전에
DEMO_MODE=true 상태에서 안정적으로 시연 가능한 Prototype을 확보하는 것이다.

과도한 리팩토링이나 Scope 확장은 하지 마라.
```

---

# 22. Definition of Done

3일차 피드백 시간에 아래 Scenario가 가능하면 성공이다.

```text
사용자가 금융 Signal 선택
        ↓
Signal 변화 확인
        ↓
관련 Evidence 확인
        ↓
한화생명 / 한화투자증권 / 한화자산운용
Impact 비교
        ↓
계열사별 Insight 확인
```

최종 메시지:

> 글로벌 금융시장에 동일한 변화가 발생하더라도
> 보험·증권·자산운용은 서로 다른 영향을 받는다.
>
> Hanwha Financial Trend Radar는
> 범용 금융정보를 한화 금융계열사별 관점의 Insight로 변환한다.

---

# 23. Final Principle

> **작동하는 한 줄의 Pipeline이,
> 미완성된 완전 자동화 시스템보다 중요하다.**

Prototype 단계에서는:

```text
Demo Stability
>
End-to-End Completion
>
Interpretation Quality
>
Automation Level
```

순으로 우선한다.
