# Lichess PDF Maker

Lichess puzzle database CSV에서 원하는 퍼즐을 골라 인쇄용 PDF를 만드는 도구입니다. 로컬 CLI/웹 UI와 Vercel에 배포되는 공개 Lab page를 함께 제공합니다.

아이디어는 `hlotze/lichess_puzzles_to_pdf`에서 얻었으며, 코드는 새로 작성했습니다. 퍼즐 데이터는 Lichess open database의 CC0 퍼즐 CSV를 기준으로 읽습니다.

## 퍼즐 데이터셋 컨셉

공개 Lab(`lab.blundermate.app`)은 Lichess **인기도 100/100** 퍼즐만 담은 큐레이션 DB를 사용합니다.

- 전체 Lichess 퍼즐 약 5.94M개 중 popularity=100인 퍼즐 **407,387개** (상위 6.86%)
- popularity=100 = "받은 모든 평가가 좋아요" → 만장일치로 호평받은 퍼즐
- 샘플링 없이 통째로 적재되므로 결정적(deterministic). "이 조건엔 N개 있다"가 정확함
- Neon Postgres 무료 티어(0.5GB)에 여유 있게 들어감

`import_puzzles.py`의 기본값(`--min-popularity 100`, `--limit 0`)이 이 데이터셋을 만듭니다.

## BlunderMate Lab 배포 구조

- `blundermate.app`: 기존 BlunderMate 모바일 체스 앱입니다. 이 repo에서는 수정하지 않습니다.
- `lab.blundermate.app`: 별도 Vercel project로 운영하는 BlunderMate Lab입니다.
- Vercel project: `lichesstopdf`
- 프런트엔드: `web/`의 정적 페이지
  - `/` → `web/index.html` (랜딩 허브)
  - `/puzzle` → `web/puzzle.html` (퍼즐 인쇄 Lab)
  - `/opening` → `web/opening.html` (오프닝 스터디 인쇄)
- 백엔드: `api/`의 Vercel Serverless Function
  - `api/puzzles.py` → Neon Postgres에서 popularity=100 퍼즐을 조회
  - `api/study.py` → Lichess 스터디 PGN을 받아 인쇄용 HTML을 렌더 (`study_core.py` 공유)

`/puzzle`, `/opening` 같은 경로는 `vercel.json`의 `cleanUrls`가 `web/*.html` 파일에 자동 매핑합니다.

### Vercel 설정

이 repo의 루트에 있는 `vercel.json`은 정적 산출물 디렉터리를 `web/`으로 지정하고, `api/study.py`가 루트의 `study_core.py`를 함께 번들하도록 지정합니다.

```json
{
  "outputDirectory": "web",
  "cleanUrls": true,
  "functions": {
    "api/study.py": { "includeFiles": "study_core.py" }
  }
}
```

배포 시 아래 파일과 폴더는 업로드/커밋 대상에서 제외합니다.

- `output/`
- `.venv/`
- `data/lichess_db_puzzle.csv.zst`
- `data/*.csv.zst`
- `data/lichess_db_puzzle.csv`

도메인은 BlunderMate 본체와 분리해서 `lab.blundermate.app`만 이 Vercel project에 연결합니다.

### Neon DB 임포트

Lichess CSV를 받아 popularity=100 퍼즐을 Neon Postgres에 적재합니다.

```powershell
.\.venv\Scripts\python.exe .\import_puzzles.py
```

기본값은 `--min-popularity 100`, `--limit 0`(전부), `--min-nb-plays 0`입니다. 데이터셋 컨셉을 조정하려면 옵션을 바꿔 다시 실행하면 됩니다 (테이블을 drop 후 재생성).

연결 문자열은 `DATABASE_URL` 환경변수 또는 repo 루트의 `.env`에서 읽습니다.

## 목표

- Lichess 퍼즐 CSV 직접 읽기
- 테마, 레이팅, 인기도 기준 필터링
- 문제지 PDF와 정답지 PDF 생성
- 문제지와 정답지 분리 출력
- MySQL/MariaDB 없이 동작 (Neon Postgres / 로컬 CSV)

## 로컬 Lab UI 미리 보기

Windows에서 `start_local_app.bat`을 실행하거나 아래 명령을 실행합니다.

```powershell
.\start_local_app.ps1
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8765/
```

이 주소는 로컬 전용 백엔드 UI입니다. `data/lichess_db_puzzle.csv.zst`를 직접 고르고, 조건에 맞는 퍼즐을 editable CSV workspace로 저장한 뒤 HTML/PDF를 만들 수 있습니다.

로컬 전용 UI 파일은 `local_web/local.html`에 있고, Vercel 정적 배포물에는 포함하지 않습니다. 공개 Lab page는 `web/index.html`입니다.

## 설치

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 샘플 PDF 만들기

```powershell
.\.venv\Scripts\python.exe .\make_puzzle_pdf.py `
  --input .\data\sample_puzzles.csv `
  --theme fork `
  --count 2 `
  --output .\output\fork_sample.pdf
```

문제지만 만들기:

```powershell
.\.venv\Scripts\python.exe .\make_puzzle_pdf.py `
  --input .\data\sample_puzzles.csv `
  --theme fork `
  --count 2 `
  --layout print-minimal `
  --questions-only `
  --output .\output\fork_questions.pdf
```

정답지만 만들기:

```powershell
.\.venv\Scripts\python.exe .\make_puzzle_pdf.py `
  --input .\data\sample_puzzles.csv `
  --theme fork `
  --count 2 `
  --answers-only `
  --output .\output\fork_answers.pdf
```

## 실제 Lichess 데이터 쓰기

Lichess puzzle database에서 `lichess_db_puzzle.csv.zst`를 받은 뒤 `data/` 폴더에 넣고 실행합니다.

데이터 다운로드 페이지: https://database.lichess.org/#puzzles

```powershell
.\.venv\Scripts\python.exe .\make_puzzle_pdf.py `
  --input .\data\lichess_db_puzzle.csv.zst `
  --theme mateIn2 `
  --min-rating 1200 `
  --max-rating 1800 `
  --min-popularity 80 `
  --count 20 `
  --seed 7 `
  --output .\output\mate_in_2_1200_1800.pdf
```

## 주요 옵션

- `--theme`: Lichess theme. 여러 번 지정할 수 있습니다.
- `--match any|all`: 여러 테마 지정 시 하나만 맞아도 되는지, 전부 맞아야 하는지 선택합니다.
- `--min-rating`, `--max-rating`: 퍼즐 레이팅 범위입니다.
- `--min-popularity`: 낮은 품질의 퍼즐을 거르기 좋습니다.
- `--count`: 출력할 퍼즐 수입니다.
- `--seed`: 랜덤 샘플링을 재현 가능하게 만듭니다.
- `--questions-only`: 문제 페이지만 만듭니다.
- `--answers-only`: 정답 페이지만 만듭니다.
- `--solutions-at-end`: 문제를 먼저 모으고 정답을 뒤에 모읍니다.
- `--layout standard|print-minimal|instagram`: PDF/HTML 양식을 고릅니다.
- `--html-only`: PDF 생성 없이 HTML까지만 만듭니다.

## Instagram 카드 만들기

정사각형 1080x1080 PNG 카드를 만들 수 있습니다.

```powershell
.\.venv\Scripts\python.exe .\export_instagram_carousel.py `
  --input .\data\lichess_db_puzzle.csv.zst `
  --theme veryLong `
  --min-rating 2200 `
  --max-rating 2600 `
  --min-popularity 85 `
  --count 3 `
  --answers `
  --output-dir .\output\instagram
```

## Lichess 스터디 인쇄하기

오프닝 연구처럼 변화수와 코멘트가 담긴 Lichess 스터디를 인쇄용 PDF로 만들 수 있습니다. `make_study_pdf.py`는 수마다 보드 다이어그램을 격자로 깔아 줍니다.

공개 스터디 URL이나 ID로 바로 가져오기:

```powershell
.\.venv\Scripts\python.exe .\make_study_pdf.py `
  --study https://lichess.org/study/xxxxxxxx `
  --output .\output\opening_study.pdf
```

스터디에서 export한 로컬 PGN 파일 쓰기:

```powershell
.\.venv\Scripts\python.exe .\make_study_pdf.py `
  --input .\data\sample_study.pgn `
  --output .\output\opening_study.pdf
```

URL에 챕터 ID까지 넣으면(`/study/xxxxxxxx/yyyyyyyy`) 해당 챕터만 가져옵니다.

### 스터디 옵션

- `--study`: Lichess 스터디 URL 또는 ID. 챕터 ID를 함께 넣을 수 있습니다.
- `--input`: 스터디에서 내려받은 `.pgn` 파일.
- `--columns`: 한 줄에 놓을 다이어그램 수 (기본 3).
- `--orientation white|black`: 모든 보드의 방향.
- `--mainline-only`: 변화수를 빼고 메인라인만 출력합니다.
- `--max-variation-depth`: 변화수 중첩 깊이 한계 (기본 4).
- `--page-break-per-chapter` / `--no-page-break-per-chapter`: 챕터마다 새 페이지에서 시작할지 (기본 켜짐).
- `--html-only`: PDF 없이 HTML까지만 만듭니다.

메인라인 카드는 진한 테두리, 변화수는 깊이에 따라 색이 다른 왼쪽 테두리로 구분됩니다. PGN 코멘트는 다이어그램 아래에 붙고, `[%cal]`/`[%csl]` 주석은 보드 위 화살표로 그려집니다.

## 필요한 외부 프로그램

PDF 생성에는 Chrome 또는 Edge의 headless print 기능을 사용합니다. 브라우저가 자동 탐지되지 않으면 `--chrome-path`로 직접 지정할 수 있습니다.

```powershell
--chrome-path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```
