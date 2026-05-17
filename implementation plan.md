# Vercel 이전 구현 계획

이 문서는 지금 만든 로컬용 Lichess PDF Maker를 장기적으로 `blundermate.app`에 붙일 수 있는 웹서비스로 옮기는 계획입니다.

## 1. 지금 상태

현재 프로젝트는 로컬에서 쓰는 PDF 생성기입니다.

```text
브라우저 로컬 UI
  -> local_app.py
  -> make_puzzle_pdf.py
  -> data/lichess_db_puzzle.csv.zst
  -> output/*.html, output/*.pdf
```

현재 잘 되는 것:

- Lichess 공식 퍼즐 CSV를 직접 읽음
- `.csv.zst` 압축 파일을 그대로 읽음
- 테마, 레이팅, 인기도, 문제 수, 랜덤 seed로 필터링
- 문제지 PDF와 정답지 PDF 생성
- 문제지/정답지 분리 출력 가능
- 내 컴퓨터에서는 충분히 잘 돌아감

Vercel로 옮길 때 문제가 되는 것:

- 전체 Lichess 퍼즐 DB가 큼. 현재 압축 파일만 약 296MB
- 요청마다 전체 DB를 읽으면 너무 느리고 낭비가 큼
- 현재 PDF 생성은 로컬 Chrome headless에 의존함
- Vercel 함수의 로컬 파일 저장은 임시 저장소라 오래 유지되지 않음
- `local_app.py`는 로컬 서버용 코드라 Vercel API 구조와 다름

## 2. 장기 목표

장기적으로는 사용자가 `blundermate.app`에서 이런 흐름을 쓰게 하는 것이 목표입니다.

```text
사용자가 blundermate.app 접속
  -> 테마, 레이팅, 문제 수, 출력 방식 선택
  -> 생성 버튼 클릭
  -> 문제지 PDF와 정답지 PDF 링크 받기
```

중요한 원칙:

```text
화면은 빠르게 보여준다.
큰 데이터 처리와 PDF 생성은 백엔드에서 한다.
생성된 파일은 Vercel 함수 안이 아니라 영구 저장소에 둔다.
```

## 3. 추천 구조

Vercel은 프론트와 API를 맡고, 큰 데이터와 생성 파일은 별도 저장소에 둡니다.

```text
Next.js / Vercel 프론트엔드
  -> POST /api/puzzle-pdfs
  -> 문제 생성 작업
  -> 퍼즐 인덱스 저장소
  -> HTML/PDF 렌더러
  -> Vercel Blob 또는 S3/R2/Supabase Storage
  -> 다운로드 URL 반환
```

추천 구성:

- 웹사이트/API: Vercel Next.js
- 생성된 PDF 저장: Vercel Blob, Cloudflare R2, S3, Supabase Storage 중 하나
- 퍼즐 데이터 인덱스: JSONL shard, Postgres, SQLite/DuckDB 파일 중 하나
- 주기적 업데이트: Vercel Cron 또는 관리자용 로컬 스크립트

## 4. 데이터 전략

`lichess_db_puzzle.csv.zst` 전체 파일을 Vercel 배포물에 넣지 않습니다.

대신 이렇게 합니다.

1. Lichess 공식 퍼즐 DB를 주기적으로 다운로드
2. 서비스에서 쓰기 좋게 작은 인덱스 파일들로 변환
3. 인덱스를 저장소나 DB에 업로드
4. 사용자가 PDF를 만들 때 필요한 인덱스만 읽음

### 선택지 A: JSONL 조각 파일

예를 들면 이런 파일들을 미리 만들어둡니다.

```text
puzzle-index/
  fork/1200-1399.jsonl
  fork/1400-1599.jsonl
  mateIn2/1200-1399.jsonl
  endgame/1800-1999.jsonl
```

각 줄에는 PDF 생성에 필요한 정보만 들어갑니다.

```json
{"id":"abc","fen":"...","moves":"...","rating":1800,"popularity":92,"themes":["fork","middlegame"],"gameUrl":"..."}
```

장점:

- 단순함
- 비용이 낮음
- 캐시하기 쉬움
- 초기 제품에 충분함

단점:

- 복잡한 필터를 하려면 파일 설계를 잘 해야 함
- Lichess DB가 업데이트될 때 인덱스를 다시 만들어야 함

### 선택지 B: Postgres

퍼즐을 DB 테이블에 넣는 방식입니다.

기본 컬럼:

```text
id
fen
moves
rating
rating_deviation
popularity
nb_plays
themes
game_url
opening_tags
```

인덱스가 필요한 값:

```text
rating
popularity
themes
```

장점:

- 필터가 유연함
- 나중에 분석/통계/사용자 기록 붙이기 쉬움
- 제품이 커질수록 관리하기 좋음

단점:

- 처음 세팅이 더 복잡함
- 수백만 행 import를 잘 처리해야 함

### 데이터 전략 결론

초기에는 **JSONL 조각 파일 방식**을 추천합니다.

이유:

- 빠르게 만들 수 있음
- Vercel과 잘 맞음
- DB 운영 부담이 적음
- 퍼즐 PDF 생성이라는 기능에는 충분함

나중에 사용자 기록, 추천, 통계, 결제 상품이 중요해지면 Postgres로 넘어가면 됩니다.

## 5. PDF 생성 전략

현재 로컬 방식은 이렇습니다.

```text
HTML 문자열 생성
  -> Chrome headless 실행
  -> PDF 저장
```

로컬에서는 좋지만, Vercel에서는 Chrome headless가 까다로울 수 있습니다.

### 선택지 A: Vercel에서는 HTML만 생성

백엔드는 인쇄 가능한 HTML을 만들고, 사용자가 브라우저에서 인쇄 또는 PDF 저장을 합니다.

장점:

- 가장 쉬움
- 서버에서 Chrome을 실행하지 않아도 됨
- 첫 MVP로 좋음

단점:

- PDF 파일을 바로 다운로드하는 경험은 아님
- 사용자가 직접 PDF 저장을 해야 함

### 선택지 B: 서버리스용 PDF 렌더러 사용

Node/Chromium 패키지나 외부 PDF API를 사용합니다.

장점:

- 사용자가 바로 PDF 링크를 받음
- 지금 로컬 경험과 비슷함

단점:

- 배포 난이도가 올라감
- 함수 번들이 커질 수 있음
- 렌더링 시간이 길어질 수 있음

### 선택지 C: 브라우저 없이 PDF 직접 생성

PDF 라이브러리로 직접 문서를 만듭니다.

예:

- Python: ReportLab
- Node: pdf-lib, PDFKit

장점:

- Chrome 의존성이 없음
- 서버에서 더 예측 가능함

단점:

- 지금 HTML/CSS 레이아웃을 다시 구현해야 함
- 체스판 SVG나 이미지 처리를 따로 신경써야 함

### PDF 전략 결론

추천 순서:

1. Vercel 첫 버전은 **인쇄 가능한 HTML 생성**
2. 사용 흐름이 괜찮으면 PDF 다운로드 기능 추가
3. PDF가 핵심 유료 기능이 되면 전용 worker나 안정적인 PDF 렌더러로 분리

## 6. API 설계

초기 API는 이런 형태가 좋습니다.

```http
POST /api/puzzle-pdfs
```

요청 예시:

```json
{
  "themes": ["veryLong", "fork"],
  "match": "any",
  "minRating": 1800,
  "maxRating": 2200,
  "minPopularity": 80,
  "count": 10,
  "seed": 42,
  "splitOutput": true
}
```

HTML 우선 MVP 응답:

```json
{
  "jobId": "job_123",
  "questionsHtmlUrl": "/generated/job_123/questions",
  "answersHtmlUrl": "/generated/job_123/answers"
}
```

PDF 버전 응답:

```json
{
  "jobId": "job_123",
  "questionsPdfUrl": "https://storage.example/questions.pdf",
  "answersPdfUrl": "https://storage.example/answers.pdf"
}
```

## 7. Vercel 이전 전에 필요한 코드 정리

지금은 `make_puzzle_pdf.py` 안에 여러 역할이 섞여 있습니다.

현재:

```text
make_puzzle_pdf.py
  - CLI 옵션 처리
  - CSV 읽기
  - 퍼즐 필터링
  - HTML 렌더링
  - PDF 출력
```

Vercel로 가려면 공통 로직을 분리하는 게 좋습니다.

목표 구조:

```text
src/
  puzzle_types.py
  puzzle_loader.py
  puzzle_selector.py
  puzzle_renderer.py
  pdf_renderer.py
  local_server.py
```

각 파일 역할:

- `puzzle_types.py`: 퍼즐 데이터 타입
- `puzzle_loader.py`: CSV, JSONL, DB에서 퍼즐 읽기
- `puzzle_selector.py`: 조건 필터링과 랜덤 샘플링
- `puzzle_renderer.py`: 퍼즐을 HTML로 렌더링
- `pdf_renderer.py`: HTML을 PDF로 변환
- `local_server.py`: 로컬 UI 전용 서버

이렇게 하면 CLI, 로컬 UI, Vercel API가 같은 핵심 코드를 공유할 수 있습니다.

## 8. 단계별 이전 계획

### 1단계: 로컬 도구 완성도 올리기

목표:

- 개인용으로 충분히 편하게 쓰는 상태 만들기

할 일:

- README 인코딩과 문서 정리
- Lichess DB 다운로드/업데이트 명령 추가
- 자주 쓰는 조건 preset 저장
- 문제지/정답지 분리 출력을 기본값으로 유지
- 테마 목록 화면 추가

완료 기준:

- 로컬 UI에서 1분 안에 인쇄용 문제지를 만들 수 있음

### 2단계: 핵심 로직 분리

목표:

- 로컬 UI와 Vercel API가 같은 생성 로직을 쓰게 만들기

할 일:

- `make_puzzle_pdf.py`에서 공통 로직을 `src/`로 분리
- CLI는 얇은 wrapper로 유지
- 로컬 UI도 얇은 wrapper로 유지
- 퍼즐 선택과 렌더링 테스트 추가

완료 기준:

- CLI와 로컬 UI가 같은 core 함수를 호출함

### 3단계: Next.js/Vercel 프로토타입 만들기

목표:

- `blundermate.app`에서 퍼즐 조건을 선택하고 HTML 문제지를 생성

할 일:

- Next.js 페이지에 퍼즐 조건 폼 추가
- `POST /api/puzzle-sets` 추가
- 작은 샘플 인덱스 파일로 먼저 테스트
- 문제 HTML / 정답 HTML 페이지 반환

완료 기준:

- Vercel에서 샘플 데이터로 문제지 HTML을 생성할 수 있음

### 4단계: 실제 Lichess 인덱스 붙이기

목표:

- 샘플 데이터가 아니라 실제 Lichess DB 기반으로 문제 생성

할 일:

- `lichess_db_puzzle.csv.zst`에서 JSONL 인덱스를 만드는 스크립트 작성
- 테마와 레이팅 구간별 파일 생성
- 인덱스를 저장소에 업로드
- API가 필요한 인덱스만 읽도록 변경

완료 기준:

- Vercel에서 전체 DB 스캔 없이 실제 퍼즐 문제지를 생성함

### 5단계: 생성 결과 영구 저장

목표:

- 생성된 파일 링크가 새로고침/재배포 이후에도 유지

할 일:

- Vercel Blob, R2, S3, Supabase Storage 중 하나 선택
- 생성된 HTML/PDF 업로드
- 다운로드 URL 반환
- 오래된 무료 생성물 정리 정책 추가

완료 기준:

- 생성된 링크가 일정 기간 안정적으로 유지됨

### 6단계: 서버 측 PDF 다운로드 추가

목표:

- 사용자가 직접 PDF 파일을 받을 수 있게 만들기

할 일:

- PDF 렌더러 선택
- 생성 시간과 배포 크기 측정
- 실패 처리와 timeout 처리 추가
- 문제 수 제한 추가

완료 기준:

- Vercel에서 10문제 문제지 PDF와 정답지 PDF를 안정적으로 생성

### 7단계: 제품화 기능

목표:

- 단순 생성기가 아니라 BlunderMate의 유입/수익 기능으로 만들기

할 일:

- 사용자별 preset
- 오늘의 문제 세트
- 공유 가능한 문제 세트 페이지
- Instagram carousel export
- 주간 PDF 이메일 구독
- 유료 문제팩 또는 구독

완료 기준:

- 재방문, 이메일 가입, 공유, 결제 중 하나가 발생하기 시작함

## 9. 주요 리스크

### 리스크 1: 요청마다 전체 DB 읽기

나쁜 방식:

```text
사용자 요청마다 296MB 압축 파일과 수백만 행을 읽음
```

좋은 방식:

```text
미리 작게 나눈 인덱스 또는 DB를 사용
```

### 리스크 2: Vercel에서 PDF 렌더링 실패

나쁜 방식:

```text
로컬 Chrome처럼 Vercel에도 Chrome이 당연히 있다고 가정
```

좋은 방식:

```text
처음에는 인쇄 가능한 HTML로 시작하고, PDF는 안정화 후 추가
```

### 리스크 3: 생성 파일이 사라짐

나쁜 방식:

```text
Vercel 함수 안의 로컬 파일 시스템에 output/ 저장
```

좋은 방식:

```text
Blob/S3/R2/Supabase Storage 같은 영구 저장소에 업로드
```

### 리스크 4: 비용과 남용

나쁜 방식:

```text
아무나 200문제 PDF를 계속 생성 가능
```

좋은 방식:

```text
문제 수 제한, rate limit, 캐시, 로그인, 유료 제한 추가
```

## 10. 가장 먼저 만들 Vercel MVP

처음부터 완벽한 PDF 다운로드까지 만들지 않습니다.

첫 Vercel MVP 범위:

- Next.js 페이지
- 로컬 UI와 비슷한 조건 선택 폼
- 작은 샘플 인덱스
- 문제 HTML / 정답 HTML 생성
- 서버 측 PDF 생성은 아직 없음
- 버튼 이름은 "인쇄용 페이지 열기" 정도

이렇게 시작하는 이유:

- 사용자 흐름을 빨리 검증할 수 있음
- 큰 DB/스토리지/PDF 렌더러 문제를 뒤로 미룰 수 있음
- 배포가 쉽고 실패 지점이 적음

그 다음 순서:

```text
샘플 HTML 생성
  -> 실제 Lichess 인덱스
  -> 생성 결과 저장
  -> PDF 다운로드
  -> 계정/구독/Instagram export
```

## 11. 아주 쉽게 비유하면

로컬 버전:

```text
네 컴퓨터가 공장이다.
네 컴퓨터에 큰 퍼즐 창고가 있다.
네 컴퓨터가 PDF를 만들고 네 디스크에 저장한다.
```

Vercel 버전:

```text
blundermate.app은 매장이다.
퍼즐 인덱스는 창고다.
PDF 생성기는 공장 기계다.
Blob Storage는 완성된 PDF를 올려두는 선반이다.
```

그래서 이전의 핵심은 이것입니다.

```text
내 컴퓨터 하나가 전부 하던 일을
화면, 데이터, 생성기, 저장소로 나누는 것
```

이렇게 나눠야 실제 사용자들이 써도 버틸 수 있습니다.
