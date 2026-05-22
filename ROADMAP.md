# Roadmap

## MVP

- [x] Lichess puzzle CSV 읽기
- [x] `.csv.zst` 압축 파일 스트리밍 지원
- [x] 테마 필터
- [x] 레이팅 범위 필터
- [x] 인기도 필터
- [x] 랜덤 샘플링
- [x] 문제 페이지와 정답 페이지 HTML 생성
- [x] Chrome headless PDF 출력
- [x] 로컬 웹 UI
- [x] 문제지/정답지 분리 출력
- [x] 인쇄용 미니멀 양식
- [x] Instagram carousel PNG export
- [x] Lichess 스터디 PDF 출력 (수마다 다이어그램)
- [x] Lab 페이지 분리 (랜딩 허브 / `/puzzle` / `/opening`)
- [x] `api/study.py` 스터디 렌더 엔드포인트 (study_core 공유)

## Next

- [ ] Lichess puzzle database 다운로드 명령 추가
- [ ] 테마 목록을 보기 쉽게 출력하는 명령 추가
- [ ] PDF 레이아웃 옵션 추가
- [ ] 자주 쓰는 조건 preset 저장
- [ ] 한국어 제목/설명 옵션
- [ ] 작은 웹 UI 개선
- [ ] Instagram 힌트 카드 양식 추가
- [ ] 생성 이력 저장
- [ ] 서비스용 API 엔드포인트
- [ ] Vercel 이전용 core 모듈 분리

## Product Ideas

- 사용자가 레이팅 구간과 전술 테마를 고르면 맞춤형 PDF 생성
- 매일 10문제 PDF 자동 생성
- 어린이/초보자용 큰 글씨 모드
- 코치가 학생별 숙제를 PDF로 뽑는 기능
- 오프닝별 전술 문제집
- 자주 틀리는 테마 기반 복습 문제집
- Instagram carousel용 이미지 export
