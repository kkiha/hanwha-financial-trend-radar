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
# .env 파일에 GROQ_API_KEY 값을 입력합니다.
.\.venv\Scripts\python.exe -m streamlit run app/trend_feed_app.py
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# .env 파일에 GROQ_API_KEY 값을 입력합니다.
.venv/bin/python -m streamlit run app/trend_feed_app.py
```

브라우저에서 [localhost:8501](http://localhost:8501)을 엽니다. 기존 `.env`가 있다면 복사하지 말고 필요한 설정만 확인하세요.

```dotenv
GROQ_API_KEY=발급받은_Groq_API_키
```

새 분석 생성에는 Groq API 키와 RSS·Groq에 접근할 수 있는 네트워크가 필요합니다. 키 없이도 저장된 결과나 합성 예시 화면은 열 수 있습니다. `.env`와 실제 키는 커밋하지 않습니다. 호스팅 환경에서는 같은 이름의 환경변수로 설정하세요.

## 사용 방법

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

## 설정과 저장 위치

| 경로 | 역할 |
|---|---|
| `configs/service.json` | RSS 검색 모드, Groq 모델·토큰·재시도 설정 |
| `configs/company_profiles/` | 3개 회사의 검색어·사업 영역·관련성 기준과 검증 스키마 |
| `data/live/latest_articles.json` | 수집 기사 |
| `data/live/latest_trends.json` | 트렌드와 집계 결과 |
| `data/live/latest_company_relevance.json` | 회사별 관련성 분류 |
| `data/live/latest_company_briefs.json` | 회사별 브리핑 |
| `data/live/latest_refresh.json` | 최근 갱신 상태와 진단 정보 |
| `data/demo_outputs/trend_feed_fallback.json` | 첫 실행 및 저장 결과 부재 시 사용할 합성 예시 |

기본 RSS 검색 모드는 `profiles`입니다. `common`은 공통 금융 검색어, `both`는 두 종류를 사용합니다. 설정 파일은 JSON 형식입니다.

`data/live/`는 실행 중 생성되며 Git에 포함하지 않습니다. 새로 복제한 저장소는 DEMO로 시작하고 첫 갱신 후 실제 결과를 표시합니다. 서버의 해당 경로에는 쓰기 권한이 필요하며, 재배포 후에도 결과를 보존하려면 영속 저장소와 백업을 구성하세요. 갱신 시 파일을 공유하므로 단일 앱 인스턴스를 기준으로 운영하세요.

## 배포

- Python 환경에 `requirements.txt`를 설치합니다.
- 앱 진입점을 `app/trend_feed_app.py`로 지정하고 작업 디렉터리를 저장소 루트로 설정합니다.
- `GROQ_API_KEY`를 서버 환경변수에 등록합니다.
- 필요하면 실행 옵션으로 `--server.address 0.0.0.0 --server.port <포트>`를 지정합니다.
- 이 앱에는 로그인 기능이 없습니다. 사내 이용 범위는 호스팅 플랫폼이나 접근 제어 계층에서 설정하세요.

GitHub 커밋 자체가 배포를 수행하지는 않습니다. 연결한 호스팅 서비스가 위 진입점과 의존성을 사용하도록 설정되어 있어야 합니다.

## 문제 해결

- **DEMO만 표시됨:** API 키 설정 후 갱신하세요. 첫 실행에는 실제 분석 파일이 없습니다.
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
