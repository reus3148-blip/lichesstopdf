# Lichess PDF Maker

Lichess puzzle database CSV에서 원하는 퍼즐을 골라 인쇄용 PDF를 만드는 로컬 도구입니다.

이 프로젝트는 `hlotze/lichess_puzzles_to_pdf` 코드를 복사하지 않고 새로 작성했습니다. 퍼즐 데이터는 Lichess open database의 CC0 퍼즐 CSV를 기준으로 읽습니다.

## BlunderMate Lab 배포 구조

- `blundermate.app`: 기존 BlunderMate 모바일 체스 앱입니다. 이 repo에서는 수정하지 않습니다.
- `lab.blundermate.app`: 별도 Vercel project로 운영하는 BlunderMate Lab입니다.
- Vercel project: `lichesstopdf`
- Vercel 1차 배포물은 `web/` 안의 정적 Lab MVP입니다.
- 현재 Vercel MVP는 `sample_puzzles.csv`에 해당하는 샘플 퍼즐만 사용해 printable HTML을 만듭니다.
- 무거운 PDF 생성 백엔드와 전체 Lichess DB 스캔은 Vercel 1차 배포에 포함하지 않습니다.

### Vercel 설정

이 repo의 루트에 있는 `vercel.json`은 정적 산출물 디렉터리를 `web/`으로 지정합니다.

```json
{
  "outputDirectory": "web"
}
```

배포 시 아래 파일과 폴더는 업로드/커밋 대상에서 제외합니다.

- `output/`
- `.venv/`
- `data/lichess_db_puzzle.csv.zst`
- `data/*.csv.zst`
- `data/lichess_db_puzzle.csv`

도메인은 BlunderMate 본체와 분리해서 `lab.blundermate.app`만 이 Vercel project에 연결합니다.

### 단계별 방향

1. Vercel에는 정적 Lab page와 샘플 기반 printable HTML 생성만 올립니다.
2. 다음 MVP는 서버 PDF 다운로드보다 printable HTML 생성을 먼저 강화합니다.
3. 전체 Lichess DB는 직접 스캔하지 않고 JSONL shard/index 전략으로 분리합니다.

## 목표

- Lichess 퍼즐 CSV 직접 읽기
- 테마, 레이팅, 인기도 기준 필터링
- 문제지 PDF와 정답지 PDF 생성
- 문제지와 정답지 분리 출력
- MySQL/MariaDB 없이 동작

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

## 필요한 외부 프로그램

PDF 생성에는 Chrome 또는 Edge의 headless print 기능을 사용합니다. 브라우저가 자동 탐지되지 않으면 `--chrome-path`로 직접 지정할 수 있습니다.

```powershell
--chrome-path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```
