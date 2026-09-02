# rag-finance

이 저장소는 “RAG 기반 증권 리포트 자동화”를 위해 구축한 코드베이스입니다. 목표는 최신 금융 뉴스·애널리스트 리포트를 검색·활용해 **주식 리포트를 생성**하는 End-to-End 파이프라인을 구현하고 운영 효율성과 리서치 품질을 동시에 향상시키는 것입니다.

핵심 아이디어는 Retrieval-Augmented Generation(RAG)을 중심으로, (1) 원문 데이터 정제와 임베딩 인덱스 구축, (2) 기업 메타데이터와 키워드에 기반한 하이브리드 검색, (3) Groq LLM과 Few-shot 프롬프트(필요시)를 이용한 한국어 리포트 생성으로 이어지는 전체 자동화 흐름을 제공하는 것입니다. 아래 설명에는 프로젝트에서 채택한 아키텍처와 사용 방법을 정리해 두었습니다.

## Trend Radar Prototype (Snapshot Mode)

Trend Radar Prototype은 실시간 수집 대신 저장소에 포함된 명시적
`demo_snapshot` 입력을 사용합니다. 기존 기업 검색용 `indexes/all`과
`retrieve_with_keywords()`는 유지되며, Trend 검색은 별도
`indexes/demo_trends/index.json`에서 회사 필터 없이 실행됩니다.

```powershell
python -m scripts.build_demo_index --config configs/trend_demo.yaml
$env:DEMO_MODE="true"
python -m scripts.run_trend_sample --signal data/sample_signals/us10y_drop.json
streamlit run app/streamlit_app.py
```

`DEMO_MODE=true`는 실제로 Snapshot corpus를 검색하고 검증된 cached LLM JSON을
사용하므로 API key나 네트워크가 필요하지 않습니다. `DEMO_MODE=false`에서는
같은 Retrieval 결과와 Profile을 Groq structured-analysis prompt에 전달하며
`GROQ_API_KEY`가 필요합니다. 현재 자료는 시연용 합성 Snapshot이고 투자정보나
실시간 시장 데이터가 아닙니다.

Day 3 Demo catalog에는 `US10Y_SAMPLE`, `VIX_SPIKE`, `USDKRW_MOVE`가 포함됩니다.
시연 전 전체 artifact와 Profile grounding을 한 번에 검증할 수 있습니다.

```powershell
python -m scripts.validate_demo_artifacts
```

> 참고: 용량 이슈로 인해 `data/` 원문 텍스트는 Git 저장소에 포함되지 않습니다. 레포지토리를 클론한 뒤 직접 데이터를 배치해야 하며, 아래 “데이터 배치” 절차를 따르세요.

-------------------------------------------------------------------------------
핵심 워크플로
-------------------------------------------------------------------------------

1. **파일 로드 및 정제** (`rag_finance.ingestion`)  
   `data/raw/**`에 배치된 `.txt/.html`을 읽어 HTML 태그 제거, URL/불필요 구절 필터링을 수행합니다. 경로에 `Report/News` 등이 포함된 경우 `source_type`으로 기록합니다.

2. **기업 메타데이터 부착 + 청킹** (`rag_finance.chunking.splitter`)  
   `RecursiveCharacterTextSplitter`로 텍스트를 800자(+100 overlap)로 청킹합니다. 리포트 문서는 본문 전체에서 기업명·종목코드를 추정해 각 청크 메타데이터(`company`, `company_code`, `chunk_id`)에 저장합니다.

3. **임베딩 & 인덱싱** (`rag_finance.indexing.faiss_index`)  
   `jhgan/ko-sroberta-nli` 임베딩으로 모든 청크를 벡터화하고 `indexes/all/`에 FAISS 인덱스를 저장합니다.

4. **질의 처리 및 검색** (`rag_finance.retrieval.pipeline`)  
   - 질의에서 기업명/코드를 추출하고, 해당 회사의 키워드를 `keyword_json/{회사명}_keyword.json`에서 로드합니다.  
   - BM25(하드 확장) + FAISS(소프트 확장)을 각각 `pool_k_*` 만큼 검색 후 RRF로 합칩니다.  
   - 하이브리드 점수(임베딩 유사도 + 기업 매칭 보너스 + 키워드 보조점수)를 계산합니다.  
   - `retrieval.ce.enable: true`일 때만 Cross-Encoder(`BAAI/bge-reranker-v2-m3`)로 상위 후보를 재점수화하고 가중합합니다.  
   - `apply_mmr_after`가 `true`이면 MMR로 유사 후보를 제거하고 최종 상위 `k`개 문서를 반환합니다.

5. **LLM 리포트 생성 & 리포트 후처리** (`rag_finance.llm.report_generator`)  
   - Retrieval로 얻은 `Document` 리스트를 요약/정리해 Groq LLM에 전달할 컨텍스트로 직렬화합니다.  
   - 모델 호출 시 메시지 구조는 아래와 같습니다.
     ```text
     [System]
     너는 한국어를 사용하는 증권사 애널리스트야.

     반드시 다음 순서와 태그를 그대로 사용해서 리포트를 작성해: [Title] → [Summary] → [Analysis] → [Opinion] → [Table].

     각 섹션별 지침은 아래와 같아.

     1) [Title]: 기업명과 핵심 이슈를 반영한 한 문장 헤드라인.
     2) [Summary]: 최소 3문장으로 최근 실적, 수요/공급 변화, 전망을 요약하고 구체적인 목표주가 또는 기대 주가 범위를 포함해.
     3) [Analysis]: 최소 4문장 이상 작성하고, 참고 문서와 정형 데이터에서 도출한 핵심 수치·증감률을 연결해 사업부 동향, 수요 요인, 리스크를 서술해.
     4) [Opinion]: 최소 2문장으로 투자 판단(매수/보유/중립 등)과 근거, 모니터링 포인트를 제시해.
     5) [Table]: 마지막에 Markdown 표 한 개만 제공하되, 표 위에는 간단한 제목 한 줄을 먼저 작성해. 표는 2025년 1분기부터 2026년 4분기까지의 분기별 매출액·영업이익·영업이익률 전망을 3열(또는 이상)로 정리하고, 정형 데이터와 문서 흐름을 근거로 합리적인 수치를 추론해 제시해.
        원본 숫자를 그대로 반복하지 말고 파생 지표(전년 대비 성장률 등)를 포함해.
        정형 데이터 값은 참고용이므로 본문이나 표에서 그대로 나열하지 말고, 꼭 추세와 의미를 해석해서 전달해.
        출처 표시는 하지 마.
        숫자(실적, 성장률, 가이던스 등)는 가능하면 정량적으로 제시하고, 존재하지 않는 값은 만들지 마.
        
     [User]
     [정형 데이터]
     {tabular data (optional)}
    
     [참고 문서]
     아래는 최신 수집 문서에서 발췌한 내용이야. 리포트 작성 시 이 정보를 우선적으로 활용해 줘.
     {문서 발췌(최대 설정된 문자 수)}

     [질문]
     {사용자 질의(e.g. {기업명}의 최근 동향에 대한 한국어 리포트를 작성해 줘.)}
     ```
   - (선택사항) 필요 시 few-shot 예시(JSONL)를 순차적으로 `[User] → [Assistant]` 메시지로 삽입한 뒤 위 템플릿을 붙입니다.  
   - Groq SDK(`groq 패키지`)로 `llama-3.3-70b-versatile` 모델을 호출하며, 출력은 `[Title]/[Summary]/[Table]/[Analysis]/[Opinion]` 포맷으로 반환됩니다.
   - `tabular_db/`에 저장된 재무(`finance_*.json`)·주가(`stock_*.json`) 요약을 찾아 LLM 메시지에 함께 주입해 분석 정확도를 높입니다.
   - 생성된 리포트는 기본 텍스트와 더불어 `reportlab` 기반 PDF로도 저장할 수 있습니다.

-------------------------------------------------------------------------------
빠른 시작
-------------------------------------------------------------------------------

1) **환경 구성**
- (권장) 가상환경 생성
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- 의존성 설치
  ```powershell
  pip install -r requirements.txt
  ```
- GPU가 없다면 `configs/default.yaml`의 `embedding.device`, `retrieval.ce.device`를 `cpu`로 바꿉니다.
- Groq LLM 연동에 필요한 `groq`, `python-dotenv` 패키지도 `requirements.txt`에 포함되어 있습니다.

2) **데이터 배치**
- 레포 클론 직후에는 `data/` 폴더가 비어 있습니다. 아래 예시처럼 기본 디렉터리를 만든 뒤 원문을 복사하세요.
   ```powershell
   mkdir data
   mkdir data\raw
   mkdir data\raw\News
   mkdir data\raw\Report
   ```
- 노트북에서 사용한 원본 텍스트(`.txt/.html/.json` 등)를 `data/raw/News`, `data/raw/Report` 등으로 분류해 넣습니다. 하위 폴더명은 자동 타입 판별에 활용됩니다.
- 회사별 키워드는 `keyword_json/{회사명}_keyword.json` 형식으로 저장합니다.

3) **인덱스 생성**
```powershell
python -m scripts.build_index --config configs/default.yaml
```
예상 로그: raw 파일 개수 → 정제된 문서 수 → 생성된 청크 수 → 저장된 인덱스 경로.

4) **검색 실행**
```powershell
python -m rag_finance.cli.main retrieve --config configs/default.yaml --q "삼성전자의 최근 동향에 대한 한국어 리포트를 작성해 줘." --topk 10
```
출력에는 디버그 정보(기업/종목코드, 선택 키워드, 풀 크기 등)와 상위 근거 스니펫이 포함됩니다. CE가 활성화되어 있으면 `[rerank] CE scoring` 진행률이 표시됩니다.

5) **Groq API로 리포트 생성 & PDF 저장**
- Groq API Key(`GROQ_API_KEY`)를 환경변수로 설정하거나 `.env` 파일에 저장합니다.
- (선택) few-shot 예시(JSONL)가 있는 경우 `--examples-dir` 인자를 통해 전달할 수 있습니다.
- CLI 실행
   ```powershell
   python -m scripts.generate_report `
         --config configs/default.yaml `
         --q "삼성전자의 최근 동향에 대한 한국어 리포트를 작성해 줘." `
         --topk 10 `
         --model llama-3.3-70b-versatile `
      --output reports/samsung_latest.txt `
      --tabular-dir tabular_db `
      --pdf-output reports/samsung_latest.pdf
   ```
- 실행 후 `reports/` 폴더에 `[Title]/[Summary]/[Table]/[Analysis]/[Opinion]` 형식의 리포트가 생성됩니다.
- Retrieval 근거를 파일로 남기려면 `--context-out logs/context.json --docs-out logs/retrieved_docs.json` 등을 추가하세요.
- PDF 저장 옵션을 사용하면 텍스트 본문과 `tabular_db` 데이터를 조합한 서식화된 리포트가 함께 생성됩니다.

-------------------------------------------------------------------------------
구성 요약
-------------------------------------------------------------------------------

```
rag-finance/
├─ configs/
│   └─ default.yaml                # Retrieval시 사용하는 하이퍼파라미터 설정
├─ data/ (gitignored)
│   └─ raw/                        # 원본 텍스트 (News/Report 등 하위 폴더 권장)
├─ tabular_db/                     # 재무/주가 요약 JSON (finance_*.json, stock_*.json)
├─ indexes/
│   └─ all/                        # build_index 실행 시 생성되는 FAISS 인덱스
├─ keyword_json/                   # 회사별 키워드 JSON
├─ llm/                            # Groq few-shot 예시, 프롬프트 템플릿, 출력 저장소 (선택)
├─ rag_finance/
│   ├─ ingestion/                  # 파일 로딩·정제 로직
│   ├─ chunking/                   # 청킹 + 기업 메타데이터 주입
│   ├─ indexing/                   # 임베딩/FAISS 저장
│   ├─ entities/                   # 기업·키워드 유틸
│   └─ retrieval/                  # BM25+FAISS+RRF+CE+MMR 파이프라인
└─ scripts/
   ├─ build_index.py              # 인덱스 구축
   └─ generate_report.py          # Retrieval+LLM 생성 CLI
```

-------------------------------------------------------------------------------
환경 설정 포인트
-------------------------------------------------------------------------------

- `retrieval.ce.enable: false`로 두면 CE 없이 하이브리드 점수만으로 랭킹합니다. CPU 환경에서 유용합니다.
- 새로운 데이터를 넣거나 설정을 바꾸면 반드시 `build_index`를 다시 실행해 인덱스를 최신화하세요.
- 정형 데이터 활용 시 `--tabular-dir`에 디렉터리를 지정해 자동으로 JSON을 찾게 할 수 있습니다.
- PDF 출력 기능을 쓰려면 `reportlab` 설치가 필요하며, 윈도우에서는 CJK 폰트가 설치되어 있어야 합니다.
- `requirements.txt`에는 리포트 생성을 위한 여러 핵심 라이브러리들이 포함됩니다.
- Groq API를 활용한 리포트 생성 기능을 사용하려면 `groq` Python SDK와 API Key가 필요합니다. `.env`에 `GROQ_API_KEY`를 저장하면 CLI에서 자동으로 불러옵니다.

- 변경 로그

- 0.3.3: `tabular_db` 기반 재무/주가 JSON 주입, PDF 리포트 옵션, README 다국어 업데이트
- 0.3.2: `data/` 디렉터리 Git 제외 안내 및 데이터 배치 절차 업데이트
- 0.3.1: Groq 관련 의존성을 기본 `requirements.txt`로 통합
- 0.3.0: Groq LLM을 이용한 리포트 생성 CLI/유틸 추가
- 0.2.0: 기업 메타데이터(기업명/종목코드) 자동 추출, CE 비활성화 옵션, README 워크플로 정리
- 0.1.0: 노트북 기반 초기 파이프라인(ingestion → chunk → FAISS → BM25/FAISS → CE → MMR)

-------------------------------------------------------------------------------

## Project Overview

This repository is for a capstone project. We build an end-to-end Retrieval-Augmented Generation (RAG) pipeline that retrieves recent Korean finance texts (news and analyst reports) and generates structured Korean stock reports using Groq LLM.

### Key Components
- Ingestion & Cleaning: Load `.txt/.html` under `data/raw/**`, remove HTML tags and unwanted phrases, and assign `source_type` using folder names (e.g., `News/Report`).
- Chunking with Company Metadata: Split texts into ~800 chars (+100 overlap) and attach metadata (`company`, `company_code`, `chunk_id`).
- Embedding & Indexing: Encode with `jhgan/ko-sroberta-nli` and store FAISS index under `indexes/all/`.
- Hybrid Retrieval: Combine BM25 (hard expansion) and FAISS (soft expansion), optionally rerank with Cross-Encoder (`BAAI/bge-reranker-v2-m3`) and apply MMR also optionally.
- LLM Report Generation: Serialize retrieved documents into context and call Groq LLM to produce a standardized report: `[Title] / [Summary] / [Table] / [Analysis] / [Opinion]`.

### Note on Data
- Since the size of text data is large, raw texts under `data/` is NOT included in the repository. Please place your own data locally following the instructions below.

### Quick Start

1) Environment
- Create a virtual environment and install dependencies.
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
- If you don’t have a GPU, set `embedding.device` and `retrieval.ce.device` to `cpu` in `configs/default.yaml`.

2) Data Placement
- Create directories and copy your raw texts and optional tabular summaries.
   ```powershell
   mkdir data
   mkdir data\raw
   mkdir data\raw\News
   mkdir data\raw\Report
   mkdir tabular_db
   ```
- Put `.txt/.html/.json` files into `data/raw/News` and `data/raw/Report` (folder names help auto-typing).
- Company keyword files go to `keyword_json/{CompanyName}_keyword.json`.

3) Build Index
```powershell
python -m scripts.build_index --config configs/default.yaml
```

4) Retrieval (optional debug run)
```powershell
python -m rag_finance.cli.main retrieve --config configs/default.yaml --q "삼성전자의 최근 동향에 대한 한국어 리포트를 작성해 줘." --topk 10
```

5) Generate Report with Groq LLM & Export PDF
- Set `GROQ_API_KEY` via environment or `.env`.
- Run CLI:
   ```powershell
   python -m scripts.generate_report `
            --config configs/default.yaml `
            --q "삼성전자의 최근 동향에 대한 한국어 리포트를 작성해 줘." `
            --topk 10 `
            --model llama-3.3-70b-versatile `
            --output reports/samsung_latest.txt `
            --tabular-dir tabular_db `
            --pdf-output reports/samsung_latest.pdf
   ```
- To persist retrieval artifacts, add:
   ```powershell
   --context-out logs/context.json --docs-out logs/retrieved_docs.json
   ```
- PDF export combines the generated text with tabular JSON data to produce a formatted report.

### Project Structure
```
rag-finance/
├─ configs/
│   └─ default.yaml                # Hyperparameter settings of context retrieval
├─ data/ (gitignored)
│   └─ raw/                        # Raw texts (Making subdocuments such as News/Report is recommended)
├─ tabular_db/                     # Summerized financial/stock JSON (finance_*.json, stock_*.json)
├─ indexes/
│   └─ all/                        # build_index 실행 시 생성되는 FAISS 인덱스
├─ keyword_json/                   # 회사별 키워드 JSON
├─ llm/                            # Groq few-shot 예시, 프롬프트 템플릿, 출력 저장소 (선택)
├─ rag_finance/
│   ├─ ingestion/                  # 파일 로딩·정제 로직 File loading & cleansing
│   ├─ chunking/                   # 청킹 + 기업 메타데이터 주입 Perform chuncking + Inject corporation metadata
│   ├─ indexing/                   # 임베딩/FAISS 저장 Save embeddings/FAISS
│   ├─ entities/                   # 기업·키워드 유틸 Util for companies & keywords
│   └─ retrieval/                  # BM25+FAISS+RRF+CE+MMR pipeline
└─ scripts/
   ├─ build_index.py              # Building indexes
   └─ generate_report.py          # Retrieval+LLM generation CLI
```

### Configuration Tips
- Set `retrieval.ce.enable: false` to disable Cross-Encoder reranking on CPU-limited setups.
- Rebuild the FAISS index after changing data or parameters.
- Use `--tabular-dir` to point at a folder containing `finance_*.json` and `stock_*.json` files; the CLI will match them with the detected company.
- Install `reportlab` (already listed in `requirements.txt`) and ensure appropriate Korean fonts are available for PDF rendering.
- `requirements.txt` includes Groq SDK (`groq`) and `python-dotenv`. Store `GROQ_API_KEY` in `.env` for convenience.

### Changelog (Summary)
- 0.3.3: Add tabular data ingestion (`tabular_db`) and PDF export option.
- 0.3.2: Document data exclusion (`data/` gitignored) and data placement steps.
- 0.3.1: Consolidate dependencies into a single `requirements.txt`.
- 0.3.0: Add Groq LLM report generation CLI.
