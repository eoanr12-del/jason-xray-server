# Jason Seller X-Ray — API Server

쿠팡 상품 재고 추적 및 판매량 추정 API 서버

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 서버 상태 |
| GET | `/api/health` | 헬스체크 |
| POST | `/api/track?pid=123` | 상품 추적 추가 |
| DELETE | `/api/track/123` | 추적 제거 |
| GET | `/api/track` | 추적 목록 |
| POST | `/api/crawl/123` | 즉시 크롤링 |
| POST | `/api/crawl-all` | 전체 크롤링 |
| GET | `/api/product/123` | 상품 정보 + 판매량 |
| GET | `/api/product/123/history?days=28` | 재고 히스토리 |
| GET | `/api/stats` | 통계 |

## 판매량 추정 방식

1. **재고 변동**: 어제 재고 - 오늘 재고 = 하루 판매량
2. **리뷰 증가**: 리뷰 증가량 ÷ 0.04 (리뷰 작성률 약 4%)
3. 두 값 중 큰 값을 사용

## 배포 (Render)

1. GitHub에 push
2. Render에서 Web Service 생성
3. 자동 배포
