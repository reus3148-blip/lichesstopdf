# Lichess PDF Maker

Lichess puzzle database CSV에서 원하는 퍼즐을 골라 인쇄용 PDF를 만드는 로컬 도구입니다.

이 프로젝트는 `hlotze/lichess_puzzles_to_pdf` 코드를 복사하지 않고 새로 작성했습니다. 퍼즐 데이터는 Lichess open database의 CC0 퍼즐 CSV를 기준으로 읽습니다.

## 목표

- Lichess 퍼즐 CSV 직접 읽기
- 테마, 레이팅, 인기도 기준 필터링
- 문제지 PDF와 정답지 PDF 생성
- 문제지와 정답지 분리 출력
- MySQL/MariaDB 없이 동작

## 로컬 웹 UI로 쓰기

Windows에서 `start_local_app.bat`을 실행하거나 아래 명령을 실행합니다.

```powershell
.\start_local_app.ps1
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8765/
```

이 화면에서 데이터 파일, 테마, 레이팅 범위, 인기도, 문제 수를 고르고 PDF를 만들 수 있습니다.

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
