# Project Context

## 목표와 처리 흐름

최근 7일간 국내외 금융·산업 뉴스를 RSS로 수집하고, 한화생명·한화자산운용·한화투자증권의 사업 특성에 맞는 후보 기사를 선별해 회사별 Intelligence Brief와 근거를 제공한다.

```text
RSS 수집 → 중복 제거 → 주요 트렌드 추출 → 회사 관련성 판정
→ 회사별 Intelligence Brief 생성 → 근거 기사와 함께 UI 표시
```

## 확정된 원칙

- 런타임에는 `configs/company_profiles/*.json`만 사용한다. 장문의 원본 리서치 보고서는 직접 입력하지 않는다.
- RSS 검색 결과와 기사 메타데이터는 후보 신호이며 회사 관련성 확정 결과가 아니다.
- 한 기사는 여러 회사·감시 주제·쿼리의 후보가 될 수 있다.
- `excluded_rules`는 회사 관련성 AI 판정에 사용하며, RSS 단계에서 단순 문자열 필터로 처리하지 않는다.
- 신규 회사 흐름에는 기존 RAG·FAISS·BM25·RRF 및 매크로 지표를 연결하지 않는다.
- 회사별 Brief가 준비되기 전에는 현재 UI를 재설계하지 않는다.

## 현재 상태

완료:

- RSS 피드 수집과 중복 제거
- 세 회사 사전 리서치 및 Runtime Company Profile 정제
- Runtime Profile 공통 로더와 스키마·참조 무결성 검증
- 24개 회사별 한국어·영어 RSS 쿼리 FeedSpec 생성
- 기사 후보 회사·감시 주제·쿼리 메타데이터 저장 및 중복 병합
- `profiles`, `common`, `both` 수집 모드 (`profiles`가 신규 앱 기본값)
- 트렌드 3건을 회사별 3회 순차 호출한 뒤 9개 조합으로 병합하는 Groq 관련성 분류
- 트렌드당 대표 기사 최대 3건 선정과 관련성 입력 프로필·기사 압축
- 회사별 1,200 출력 토큰, Strict Structured Output, 낮은 reasoning effort 적용
- 429 `retry-after` 기반 회사별 격리 재시도와 안전한 호출 진단 정보
- 회사별 주제·태그 및 트렌드별 근거 기사 ID의 엄격한 참조 검증
- 코드 기반 근거 기사·출처·최근 48시간 통계 계산
- `data/live/latest_company_relevance.json` 별도 저장과 `UNCLASSIFIED` 실패 상태
- 회사별 Main Brief 후보와 Monitoring Item의 결정론적 선정
- 선정된 Main Brief 문장만 Groq로 생성하고 검증된 태그·근거·통계를 코드로 결합
- `data/live/latest_company_briefs.json` 별도 안전 저장

남은 TODO:

1. 현재 UI에 회사별 탭과 근거 기사 표시
2. 실데이터 기반 최종 QA
3. 발표용 실제 기사 Snapshot 준비

원본 리서치 보고서는 프로필을 작성·검증하기 위한 근거 자료다. Runtime Profile은 그중 런타임 판정에 필요한 사업 영역, 감시 주제, 검색어, 제외 규칙만 정제한 실행 입력이다.

## 주요 파일과 실행

- `configs/company_profiles/schema.json`: Runtime Profile 스키마
- `configs/company_profiles/hanwha_*.json`: 회사별 Runtime Profile
- `rag_finance/profiles/company_profiles.py`: 공통 로더와 검증기
- `rag_finance/ingestion/rss_collector.py`: 프로필 쿼리 FeedSpec 및 후보 메타데이터
- `rag_finance/llm/company_relevance.py`: 관련성 프롬프트, 엄격 검증, 재시도 및 근거 통계
- `rag_finance/llm/company_brief.py`: Brief 후보 선정, 문장 생성·검증 및 Monitoring Item 구성
- `data/live/latest_company_relevance.json`: 현재 트렌드 세대의 관련성 결과
- `data/live/latest_company_briefs.json`: 회사별 Main Brief와 Monitoring Item
- `configs/trend_demo.yaml`: 기본 RSS 모드와 프로필 경로

관련성 결과는 `high`, `medium`, `low`, `none`만 허용한다. `high`와 `medium`만 후속 Brief 후보이며, 모든 평가는 회사 프로필의 실제 감시주제·업무 태그와 해당 트렌드의 실제 기사만 참조할 수 있다. 모델은 점수와 기사 수를 만들지 않고, `article_count`, `source_count`, `recent_48h_count`, `recent_48h_share`, `corroboration`은 코드가 계산한다.

관련성 분류는 회사별로 해당 회사 프로필 하나와 트렌드 3건만 전달한다. 각 트렌드의 모델 입력 기사는 최대 3건이며, 서로 다른 출처를 먼저 확보한 뒤 최신 발행시각, 유효한 요약 존재 여부, `article_id` 순으로 결정론적으로 선택한다. 기사 입력은 ID·제목·출처·발행시각·160자 요약·후보 회사·감시주제만 남긴다. 프로필은 회사 ID·이름·요약, 사업영역 ID·이름, 감시주제 ID·이름·전이경로, 업무 태그와 제외 규칙만 남긴다. 원본 트렌드와 전체 기사 registry는 변경하지 않는다.

각 회사는 API·파싱·검증 오류에 대해 최대 두 번 시도한다. 429는 `retry-after`를 우선하며 한 번의 대기는 최대 30초로 제한한다. 413은 같은 요청을 반복하지 않는다. 한 회사가 실패해도 다른 회사 호출은 계속하고 이미 성공한 회사를 다시 호출하지 않지만, 하나라도 최종 실패하면 불완전한 평가를 공개하지 않고 전체를 `UNCLASSIFIED`로 저장한다. 회사별 상태·시도 횟수·입력 문자 수·대표 기사 수·감시주제 수·출력 예약 토큰·대기시간만 진단 정보로 남긴다.

Main Brief는 `high`이면서 근거 수준이 `strong` 또는 `moderate`인 평가 중 회사별 최대 2건이다. `medium`과 `high + limited`는 Groq를 거치지 않는 Monitoring Item으로 회사별 최대 2건을 구성한다. `low`와 `none`은 모두 제외하며, Main 후보가 없는 회사를 억지로 채우지 않는다.

Groq는 주간 요약·제목·상황·회사 관련성·사업 영향 가능성·관찰사항 문장만 작성한다. `company_id`, `trend_id`, `business_tags`, `evidence_article_ids`, `evidence_metrics`는 검증된 관련성 결과에서 코드가 결합한다. 한 기사가 같은 회사의 여러 Brief나 서로 다른 회사의 Brief에 함께 쓰이는 것을 허용하며, Brief 생성 단계에서는 관련성 결과의 근거 ID와 통계를 제거·재선정·재계산하지 않고 그대로 복사한다. 중복 노출이 필요하면 이후 UI 표시 단계에서 처리한다.

트렌드 생성은 기존 `llm.max_tokens`를 사용한다. 관련성은 회사별 `llm.relevance_max_tokens_per_company` 기본값 1200과 `llm.relevance_reasoning_effort` 기본값 `low`를 사용한다. Brief는 `llm.brief_max_tokens` 기본값 4000을 사용한다. Groq SDK 1.7.0과 `openai/gpt-oss-120b`이 지원하는 JSON Schema Strict Structured Output을 관련성 호출에도 유지하고, 자체 3건·9건 validator를 최종 방어선으로 사용한다. Brief 프롬프트의 목표 분량은 주간 요약과 본문 각 100~150자, 제목 20~35자, 관찰사항 각 40~70자이며, 기존 최대 길이 검증은 유지한다.

Brief 생성 전 트렌드 `generated_at`과 관련성 `source_trends_generated_at`의 완전 일치를 확인한다. 전제조건 오류는 `NOT_GENERATED`, 두 차례 API·검증 실패는 `UNGENERATED`로 저장하며 기존 트렌드와 관련성 파일을 유지한다.

## 2026-09-04 실제 전체 Refresh 검증

가상환경에서 네트워크를 허용해 `python -m scripts.refresh_trend_feed`를 실행했다. 24개 RSS 요청이 모두 응답했고 그중 20개에서 최근 기사를 확보했다. 원문 후보 507건을 중복 제거해 452건(한국어 237건, 영어 215건)을 저장했으며, Groq가 트렌드 3건을 생성했다.

기존 9개 통합 관련성 요청의 메시지 입력 약 17,287자는 회사별 5,909~6,063자로 감소했다. 실제 각 회사 요청에는 트렌드 전체에서 대표 기사 8건과 감시주제 6개가 들어갔고, 세 요청 모두 재시도 없이 성공했다. 최종 결과는 `CLASSIFIED` 9건이며 회사별 `high` 1건씩, `low` 1건, `none` 5건이다. 근거 ID는 모두 대표 기사 집합에 속하고 회사별 감시주제·업무 태그 whitelist 및 코드 계산 통계와 일치한다.

Brief도 `GENERATED`로 완료돼 세 회사에 Main Brief가 1건씩 생성됐고 Monitoring Item은 0건이다. 문장 잘림과 JSON 손상은 없고 Brief 근거·태그·통계는 관련성 결과와 완전히 일치했다. 다만 한화투자증권 RWA Brief에서 외부 기업의 라이선스·파트너십 기사를 한화투자증권의 직접 실행처럼 표현한 문장이 있어, UI 공개 전 주체 일치 검증 또는 프롬프트 보강이 필요하다. 또한 한화자산운용 프로필에는 토큰증권 감시주제가 있지만 RWA 트렌드를 `none`으로 분류한 결과는 사람이 재검토할 품질 항목이다.

데이터 계약과 실제 회사별 결과 생성까지 검증했으므로 다음 기능 단계는 UI 회사별 탭과 근거 기사 표시다. 다만 위 두 가지 내용 품질 항목을 UI 작업과 함께 보완하거나 사전 검수 게이트로 두는 것이 안전하다.

## 주체 귀속·간접 관련성 품질 보완

관련성과 Brief 입력에는 근거 기사에 대상 회사명이 직접 등장하는지를 코드가 계산한 `company_mentioned_in_articles`를 포함한다. 기사에 회사가 없으면 외부 기업의 라이선스·협력·투자·출시를 대상 회사의 행동으로 바꾸지 않고, 회사 관련 문장은 영향 가능성·검토 필요·기회 또는 위험 요인처럼 조건부로 작성하도록 프롬프트에 명시한다. 관련성 validator는 근거에 회사가 없는데 조건부 표현도 전혀 없는 출력을 거부하고, Brief validator는 회사의 직접 행동으로 바꾼 요약·상황 문장과 비조건부 회사 영향 문장을 거부한다.

반대로 기사에 회사명이 없다는 사실만으로 `none`을 선택하지 않도록 명시했다. 트렌드와 프로필의 감시주제 이름·전이경로가 구체적으로 연결되면 간접 관련성을 판단할 수 있지만, 코드가 특정 등급이나 토픽을 강제하지는 않는다. 외부 RWA·토큰증권 기사와 한화자산운용의 `fund_digital_investment` 연결을 `medium`으로 허용하는 회귀 테스트와 외부 라이선스를 회사 행동으로 바꾼 문장을 거부하는 테스트를 추가했다.

보완 후 실제 refresh 1회에서는 RSS 24/24 응답, 원문 후보 513건, 중복 제거 458건, 트렌드 3건까지 생성됐다. 한화자산운용과 한화투자증권 관련성 호출은 첫 시도에 성공했지만 한화생명 응답이 새 조건부 표현 validator를 두 번 통과하지 못해 전체 계약에 따라 `UNCLASSIFIED`와 `NOT_GENERATED`로 저장됐다. 이 실행에서 확인된 과도한 검사를 조정해 각 전이경로 문장마다 표지를 요구하지 않고 `reason_ko`와 `transmission_path_ko` 전체가 조건부 의미를 가지면 허용하도록 수정했으며, 전체 165개 테스트는 통과했다. 요청된 실제 refresh는 한 번만 실행했으므로 이 마지막 완화 이후의 라이브 결과는 아직 재검증하지 않았다.

```powershell
# 기본값: profiles
python -m scripts.refresh_trend_feed --skip-llm

# 수집 → 트렌드 생성 → 회사 관련성 분류
python -m scripts.refresh_trend_feed

# 진단용: 트렌드까지만 생성
python -m scripts.refresh_trend_feed --skip-relevance

# 진단용: 관련성까지만 생성
python -m scripts.refresh_trend_feed --skip-briefs

# 기존 공통 쿼리 또는 결합 모드
python -m scripts.refresh_trend_feed --skip-llm --source-mode common
python -m scripts.refresh_trend_feed --skip-llm --source-mode both

python -m unittest discover -s tests -t .
```
