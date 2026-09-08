# Hanwha Global Finance Radar

최근 7일의 국내·해외 금융 RSS 기사를 수집해 핵심 트렌드와 한화생명·한화투자증권·한화자산운용의 사업 관점별 브리핑을 제공하는 Streamlit 웹앱입니다.

- 핵심 이슈와 계열사별 주간 요약, Main Brief·Monitoring
- 근거 기사 제목·출처·발행 시각·원문 링크 확인
- 주간·계열사 논의자료 열람, 전체 또는 한 장 요약 HTML 다운로드 및 인쇄/PDF 저장

## 설치와 실행

Python 3.12 이상을 사용하고 모든 명령은 저장소 루트에서 실행합니다. 화면은 Streamlit 1.63 이상의 components v2 API를 사용합니다.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# .env 파일에 OPENAI_API_KEY 값을 입력합니다.
.\.venv\Scripts\python.exe -m streamlit run app/trend_feed_app.py
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 값을 입력합니다.
.venv/bin/python -m streamlit run app/trend_feed_app.py
```

브라우저에서 [localhost:8501](http://localhost:8501)을 엽니다. 기존 `.env`가 있다면 복사하지 말고 필요한 설정만 확인하세요.

```dotenv
OPENAI_API_KEY=발급받은_OpenAI_API_키
```

새 분석 생성에는 OpenAI API 키와 RSS·OpenAI에 접근할 수 있는 네트워크가 필요합니다. 키 없이도 저장된 결과나 합성 예시 화면은 열 수 있습니다. `.env`와 실제 키는 커밋하지 않습니다. 호스팅 환경에서는 같은 이름의 환경변수로 설정하세요.

기본 모델은 **GPT-5.4 mini**이며 세 분석 단계 모두 OpenAI를 사용합니다. 기존 설치에서는 `pip install -r requirements.txt`를 다시 실행하고 `.env`에 `OPENAI_API_KEY`를 추가한 뒤 앱을 재시작하면 됩니다. 기존 Groq 키는 사용하지 않습니다. OpenAI API 결제 잔액과 해당 모델 접근 권한이 필요하며 ChatGPT 구독과 API 결제는 별도입니다. 데이터 공유나 무료 토큰 혜택 설정은 실행 조건이 아닙니다.

Streamlit Community Cloud에서는 앱의 **Settings → Secrets**에 아래 한 줄을 넣습니다. 로컬에서도 `.streamlit/secrets.toml`로 설정할 수 있습니다. 서버 환경변수가 있으면 우선 적용됩니다.

```toml
OPENAI_API_KEY = "발급받은_API_키"
```

키는 서버에서만 사용합니다. HTML·JavaScript·GitHub 소스에 넣지 마세요.

## 사용 방법

모델은 `.env` 또는 배포 환경변수/Streamlit Secrets의 `OPENAI_MODEL`로 선택합니다.
예: `OPENAI_MODEL=gpt-5.5`, `OPENAI_REASONING_EFFORT=none`.
mini로 돌아가려면 모델을 `gpt-5.4-mini`로 바꾸세요. 변경 후 앱을 재시작합니다.
모델 우선순위는 CLI `--model` → 환경변수 → Streamlit Secrets → `configs/service.json`입니다.
로컬 `.env`는 서버 환경변수를 덮어쓰지 않습니다. 환경변수가 없으면 JSON의 mini 기본값을 유지합니다.
추론 환경변수는 세 단계 모두에 적용되며, 비워 두면 JSON의 단계별 설정을 사용합니다.
`none`, `low`, `medium`, `high`, `xhigh`를 지원합니다. 추론을 늘리면 출력 예산·45초 요청 제한에 도달할 수 있으므로 첫 비교는 `none`으로 진행하세요.
`latest_refresh.json`의 `llm_settings`에는 실행 설정, `api_calls`에는 단계별 각 요청의 모델·추론 강도·토큰 사용량·API 소요 시간이 저장됩니다.
API 소요 시간은 수집·검증·재시도 대기 시간을 제외합니다. 응답 없는 실패의 사용량은 알 수 없으므로 기록하지 않습니다.

1. **최신 데이터 불러오기**를 누르면 기사 수집 → 트렌드 생성 → 회사별 관련성 분류 → 브리핑 생성을 실행합니다. 처리 중 기존 결과를 볼 수 있으며 소요 시간은 네트워크와 API 응답에 따라 달라집니다.
2. **근거 보기**에서 기사 목록과 원문 링크를 확인합니다. 계열사 카드의 **브리핑 보기**를 누르면 회사별 상세 페이지가 열립니다. 상세 페이지에서 다른 회사로 전환하거나 전체 현황으로 돌아갈 수 있습니다.
3. **주간 논의자료** 또는 **계열사 논의자료**에서 전체 내용을 읽고 HTML을 다운로드하거나 **인쇄 / PDF**로 저장합니다. 기본은 전체 내용 저장이며, **한 장 요약으로 저장**을 선택하면 일부 내용을 발췌한 요약을 저장합니다. 인쇄 용지는 A4를 사용하고 브라우저 머리글·바닥글을 끄세요. 내용 길이와 인쇄 설정에 따라 페이지 수는 달라질 수 있습니다.

명령줄에서 동일한 갱신을 실행할 수도 있습니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.refresh_trend_feed
# 수집만 점검: LLM 호출 없이 기사와 최근 시도 기록을 저장합니다.
.\.venv\Scripts\python.exe -m scripts.refresh_trend_feed --skip-llm
```

회사별 브리핑 주소는 `#/company/hanwha_life` 형태이며 주간 논의자료는 `#/discussion/all`입니다. 주소를 공유하거나 새로고침·뒤로가기를 해도 해당 화면을 열 수 있습니다. 페이지 이동은 새 분석을 실행하지 않습니다.

## 표시 데이터와 갱신 상태

| 표시 | 의미 |
|---|---|
| LIVE | 생성 시각 기준 24시간 이내의 저장된 트렌드 |
| CACHED | 24시간보다 오래된 저장된 트렌드 |
| DEMO | 사용할 저장 결과가 없어 표시하는 합성 예시 |
| 성공 | 갱신 과정 완료 |
| 부분 완료 | 일부 단계 또는 회사 분석만 완료. 사용 가능한 결과는 표시 |
| 실패 | 갱신 실패. 기존 저장 결과가 있으면 계속 표시 |

헤더의 **표시 데이터 시각**과 **최근 시도 시각**은 서로 다릅니다. LIVE가 모든 회사 분석의 성공을 뜻하지는 않습니다. 회사 분석 실패와 Main Brief가 없는 정상 결과도 구분해서 표시합니다.

새 트렌드의 생성 시각은 응답 검증 완료 시 서버가 UTC로 기록하고 화면에서 한국 시간으로 표시합니다. 모델이 출력한 날짜는 사용하지 않습니다. 기존 저장 결과의 시각은 소급 변경하지 않으며 다음 갱신부터 적용됩니다.

근거 목록의 **동일 사건 보도 추정** 표시는 가까운 발행 시각과 유사한 제목을 가진 기사를 묶어 보여주는 보조 정보입니다. 표시된 묶음 번호는 각 근거 목록 안에서만 유효합니다. 제목 기준의 보수적인 추정이므로 모든 동일 사건을 찾거나 보도의 독립성을 판정하지는 않습니다. 기사·출처 수, 근거 점수와 Main Brief 선정 기준에는 반영하지 않습니다.

Brief 생성은 첫 응답을 항목별로 검증하고 실패한 회사·트렌드만 최대 한 번 재요청합니다. 성공한 Brief와 코드로 생성한 Monitoring은 유지합니다. 길이·필드 오류는 해당 항목에 수정을 요청하고, 응답이 출력 한도로 잘렸을 때만 재시도 예산을 최대 2배(상한 16,000)로 조정합니다. 근거 없는 단정 등 내용 검증은 그대로 적용합니다.

트렌드·관련성 분류도 출력 잘림 시 재시도 예산을 늘립니다. 기본 추론 설정은 `none`이며 설정 파일의 `max_tokens` 값은 OpenAI의 `max_completion_tokens`로 전달됩니다. SDK 내부 재시도는 끄고 앱에서 재시도를 관리합니다. 개별 요청 제한 시간은 45초이며 전체 갱신 시간은 호출 수·재시도에 따라 달라집니다. 인증·권한·잔액 부족처럼 같은 요청으로 해결되지 않는 오류는 재시도하지 않습니다.

조건부 표현 검사는 두 회사 분석 단계에서 같은 기준을 사용하며, `수 있습니다`와 띄어쓰기 차이도 인식합니다. 이 검사는 문장 표현에 대한 보조 규칙입니다. 사실 정확성을 보장하지 않으므로 기사 ID·근거 소속·회사 행동에 대한 기존 검증도 유지합니다.

일부 생성 실패 시 상세 화면에서 생성 시각이 붙은 **이전 결과 보기**를 펼칠 수 있습니다. 이전 자료는 현재 결과의 건수에 합산하지 않습니다. 전체 논의자료에는 이전 자료라는 표시와 함께 포함되며 한 장 요약에서는 제외됩니다. 실패한 후보를 정상적인 ‘관련 이슈 없음’으로 표시하지 않습니다.

`latest_refresh.json`과 `latest_company_briefs.json`의 `brief_calls`에는 회사·트렌드별 시도, 실패 규칙, 응답 종료 사유와 재시도 토큰 예산이 기록됩니다. 원본 응답 전체나 API 키는 기록하지 않습니다. 새 보존 기능 적용 전에 이미 덮어쓴 성공 결과는 복원할 수 없습니다.

## 설정과 저장 위치

| 경로 | 역할 |
|---|---|
| `configs/service.json` | RSS 검색 모드, OpenAI 모델·토큰·재시도 설정 |
| `configs/company_profiles/` | 3개 회사의 검색어·사업 영역·관련성 기준과 검증 스키마 |
| `data/live/latest_articles.json` | 수집 기사 |
| `data/live/latest_trends.json` | 트렌드와 집계 결과 |
| `data/live/latest_company_relevance.json` | 회사별 관련성 분류 |
| `data/live/latest_company_briefs.json` | 현재 시도의 회사별 브리핑·Monitoring·항목별 생성 상태 |
| `data/live/latest_company_briefs_success.json` | 근거를 포함한 회사별 이전 성공 자료(최근 5개 스냅샷) |
| `data/live/latest_refresh.json` | 최근 갱신 상태와 진단 정보 |
| `data/demo_outputs/trend_feed_fallback.json` | 첫 실행 및 저장 결과 부재 시 사용할 합성 예시 |

기본 RSS 검색 모드는 `profiles`입니다. `common`은 공통 금융 검색어, `both`는 두 종류를 사용합니다. 설정 파일은 JSON 형식입니다.

`data/live/`는 실행 중 생성되며 Git에 포함하지 않습니다. 새로 복제한 저장소는 DEMO로 시작하고 첫 갱신 후 실제 결과를 표시합니다. 서버의 해당 경로에는 쓰기 권한이 필요하며, 재배포 후에도 결과를 보존하려면 영속 저장소와 백업을 구성하세요. 갱신 시 파일을 공유하므로 단일 앱 인스턴스를 기준으로 운영하세요.

## 배포

- Python 환경에 `requirements.txt`를 설치합니다.
- 앱 진입점을 `app/trend_feed_app.py`로 지정하고 작업 디렉터리를 저장소 루트로 설정합니다.
- `OPENAI_API_KEY`를 서버 환경변수에 등록합니다.
- 필요하면 실행 옵션으로 `--server.address 0.0.0.0 --server.port <포트>`를 지정합니다.
- 이 앱에는 로그인 기능이 없습니다. 사내 이용 범위는 호스팅 플랫폼이나 접근 제어 계층에서 설정하세요.

GitHub 커밋 자체가 배포를 수행하지는 않습니다. 연결한 호스팅 서비스가 위 진입점과 의존성을 사용하도록 설정되어 있어야 합니다.

## 문제 해결

- **DEMO만 표시됨:** API 키 설정 후 갱신하세요. 첫 실행에는 실제 분석 파일이 없습니다.
- **OpenAI 인증·권한 오류:** `OPENAI_API_KEY` 값과 프로젝트의 모델 접근 권한을 확인하고 앱을 재시작하세요.
- **OpenAI 잔액 부족 또는 요청 한도:** API 결제·사용 한도를 확인하세요. 일시적인 요청 한도 초과와 잔액 부족은 별도로 표시됩니다.
- **RSS 수집 실패:** 서버의 외부 연결과 피드 응답 상태를 확인하세요.
- **부분 완료 또는 특정 회사 결과 없음:** 화면 안내에서 실패한 회사와 구체적인 검증 사유를 확인하세요. `latest_refresh.json`과 `latest_company_relevance.json`의 `relevance_calls`에는 최종 `error_message`와 시도별 `attempt_details`가 기록됩니다. 응답이 출력 한도로 잘린 경우와 빈 응답·필수 항목·근거·태그·조건부 표현 오류 등을 구분합니다. 이전 실행의 상세 사유는 소급 복원되지 않으며 다음 갱신부터 기록됩니다.
- **components 관련 오류:** 현재 실행하는 Python 환경에서 `pip install -r requirements.txt`를 다시 실행하세요.
- **PDF 인쇄 창이 열리지 않음:** 팝업을 허용하거나 HTML을 내려받아 브라우저에서 인쇄하세요.

## 검증과 코드 위치

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
# 브라우저 검증: 로컬 Google Chrome 필요
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/verify_briefing_ui.py
```

자동 테스트는 RSS·LLM 응답을 대체해 실행합니다. 브라우저 검증은 별도 서버와 임시 데이터를 사용하며 결과는 Git에서 제외되는 `data/ui_review/app/`에 저장됩니다.

- `app/`: 실행 진입점, 데이터 로더, 화면용 데이터 변환
- `app/frontend/`: 실제 화면 HTML·CSS·JS, 논의자료 출력 스타일, Pretendard 폰트와 라이선스
- `assets/hanwha_logo.png`: 화면 로고
- `rag_finance/`: RSS 수집, 트렌드 생성, 회사별 관련성·브리핑, 회사 프로필 로더
- `scripts/refresh_trend_feed.py`: 웹 버튼과 CLI가 공유하는 갱신 흐름
- `tests/`: 현재 서비스의 회귀 테스트

분석 대상은 RSS의 제목·출처·발행 시각·URL·짧은 설명입니다. 기사 본문 전체는 수집하지 않습니다. 트렌드 순위는 기사 수 비중 50%·출처 수 비중 30%·최근 48시간 비중 20%로 계산하며, 사업 영향 점수나 투자 추천을 의미하지 않습니다.
