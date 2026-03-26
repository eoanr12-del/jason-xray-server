/**
 * 쿠팡 엑스레이 v4.0.1 - 백엔드 서버
 * Render.com 배포용
 */

const express = require("express");
const cors = require("cors");
const fetch = require("node-fetch");

const app = express();
const PORT = process.env.PORT || 3000;

// ─── 미들웨어 ───
app.use(cors({ origin: "*" }));
app.use(express.json({ limit: "1mb" }));

// 요청 로깅
app.use((req, res, next) => {
  console.log(`[${new Date().toISOString()}] ${req.method} ${req.path}`);
  next();
});

// ─── 인메모리 데이터 저장소 ───
// 프로덕션에서는 Redis나 DB 사용 권장
const store = {
  products: new Map(),      // productId -> 상품 정보
  inventory: new Map(),     // vendorItemId -> 재고 히스토리
  reports: new Map(),       // productId -> 페이지뷰 기록
  salesEstimates: new Map() // productId -> 판매량 추정
};

// ─── 유틸 ───
function estimateDailySales(reviewCount, rating, isRocket) {
  // 리뷰 기반 판매량 추정 알고리즘
  if (!reviewCount) return 0;
  
  // 기본 추정: 리뷰 1개 = 약 15~30개 판매 (카테고리마다 다름)
  const reviewToSalesRatio = 20;
  const totalEstimatedSales = reviewCount * reviewToSalesRatio;
  
  // 리뷰 생성 기간 추정 (오래된 상품일수록 일 판매량 낮음)
  // 간단히 리뷰수 기반으로 기간 추정
  let estimatedDays = 90; // 기본 3개월
  if (reviewCount > 1000) estimatedDays = 365;
  else if (reviewCount > 500) estimatedDays = 270;
  else if (reviewCount > 100) estimatedDays = 180;
  else if (reviewCount > 30) estimatedDays = 90;
  else estimatedDays = 60;
  
  let dailySales = Math.round(totalEstimatedSales / estimatedDays);
  
  // 보정: 높은 별점은 전환율 높음
  if (rating >= 4.5) dailySales = Math.round(dailySales * 1.2);
  else if (rating >= 4.0) dailySales = Math.round(dailySales * 1.1);
  else if (rating < 3.5) dailySales = Math.round(dailySales * 0.8);
  
  // 로켓배송 보정
  if (isRocket) dailySales = Math.round(dailySales * 1.15);
  
  return Math.max(0, dailySales);
}

// ─── API 엔드포인트 ───

// 헬스 체크
app.get("/api/health", (req, res) => {
  res.json({
    status: "ok",
    version: "4.0.1",
    uptime: process.uptime(),
    timestamp: Date.now(),
    productsTracked: store.products.size,
    inventoryTracked: store.inventory.size,
  });
});

// 상품 데이터 조회
app.get("/api/product/:productId", (req, res) => {
  const { productId } = req.params;

  // 캐시된 데이터 확인
  const cached = store.products.get(productId);

  if (cached && Date.now() - cached.updatedAt < 5 * 60 * 1000) {
    return res.json(cached.data);
  }

  // 캐시 없으면 기본 응답 (클라이언트에서 보낸 리포트 기반)
  const reports = store.reports.get(productId) || [];
  const salesEstimate = store.salesEstimates.get(productId);

  const response = {
    productId,
    estimatedDailySales: salesEstimate ? salesEstimate.daily : null,
    estimatedMonthlySales: salesEstimate ? salesEstimate.daily * 30 : null,
    rank: salesEstimate ? salesEstimate.rank : null,
    category: salesEstimate ? salesEstimate.category : null,
    pageViews: reports.length,
    lastUpdated: Date.now(),
  };

  res.json(response);
});

// 페이지뷰 리포트
app.post("/api/report", (req, res) => {
  const { productId, title, price, timestamp } = req.body;

  if (!productId) {
    return res.status(400).json({ error: "productId required" });
  }

  // 리포트 저장
  const reports = store.reports.get(productId) || [];
  reports.push({ title, price, timestamp: timestamp || Date.now() });

  // 최근 1000개만 유지
  if (reports.length > 1000) {
    reports.splice(0, reports.length - 1000);
  }
  store.reports.set(productId, reports);

  // 상품 정보 업데이트
  store.products.set(productId, {
    data: {
      productId,
      title,
      price,
      estimatedDailySales: null,
      lastUpdated: Date.now(),
    },
    updatedAt: Date.now(),
  });

  res.json({ success: true });
});

// 재고 추적
app.get("/api/inventory", (req, res) => {
  const { productId, vendorItemId } = req.query;

  if (!vendorItemId) {
    return res.json({ error: "vendorItemId required" });
  }

  const history = store.inventory.get(vendorItemId) || [];
  const latest = history.length > 0 ? history[history.length - 1] : null;
  const yesterday =
    history.length > 1 ? history[history.length - 2] : null;

  res.json({
    productId,
    vendorItemId,
    currentStock: latest ? latest.stock : null,
    yesterdayStock: yesterday ? yesterday.stock : null,
    trackingDays: history.length,
    history: history.slice(-30), // 최근 30일
  });
});

// 재고 체크 (백그라운드에서 호출)
app.post("/api/inventory/check", async (req, res) => {
  const { productId, vendorItemId } = req.query;

  if (!vendorItemId) {
    return res.status(400).json({ error: "vendorItemId required" });
  }

  try {
    // 쿠팡 상품 페이지에서 재고 정보 추출 시도
    // 실제로는 쿠팡 API 또는 페이지 크롤링 필요
    // 여기서는 확장프로그램에서 보내는 데이터 기반으로 저장

    const history = store.inventory.get(vendorItemId) || [];
    const today = new Date().toISOString().split("T")[0];

    // 오늘 이미 기록 있으면 스킵
    const todayRecord = history.find((h) => h.date === today);
    if (!todayRecord) {
      // stock은 확장프로그램에서 보내야 함
      // 여기서는 placeholder
      history.push({
        date: today,
        stock: null,
        timestamp: Date.now(),
      });
      store.inventory.set(vendorItemId, history);
    }

    res.json({ success: true, date: today });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 재고 업데이트 (확장프로그램에서 직접 호출)
app.post("/api/inventory/update", (req, res) => {
  const { vendorItemId, stock, productId } = req.body;

  if (!vendorItemId || stock === undefined) {
    return res.status(400).json({ error: "vendorItemId and stock required" });
  }

  const history = store.inventory.get(vendorItemId) || [];
  const today = new Date().toISOString().split("T")[0];

  // 오늘 기록 업데이트 또는 추가
  const todayIdx = history.findIndex((h) => h.date === today);
  if (todayIdx >= 0) {
    history[todayIdx].stock = stock;
    history[todayIdx].timestamp = Date.now();
  } else {
    history.push({ date: today, stock, timestamp: Date.now() });
  }

  store.inventory.set(vendorItemId, history);

  // 판매량 추정 업데이트
  if (history.length >= 2) {
    const recent = history.slice(-7);
    let totalSales = 0;
    let days = 0;

    for (let i = 1; i < recent.length; i++) {
      if (recent[i].stock !== null && recent[i - 1].stock !== null) {
        const diff = recent[i - 1].stock - recent[i].stock;
        if (diff > 0) {
          totalSales += diff;
          days++;
        }
      }
    }

    const avgDailySales = days > 0 ? Math.round(totalSales / days) : 0;

    store.salesEstimates.set(productId || vendorItemId, {
      daily: avgDailySales,
      method: "inventory_tracking",
      updatedAt: Date.now(),
    });
  }

  res.json({ success: true, recordCount: history.length });
});

// 판매량 추정 업데이트 (리뷰 기반)
app.post("/api/estimate", (req, res) => {
  const { productId, reviewCount, rating, isRocket, price, category } = req.body;

  if (!productId) {
    return res.status(400).json({ error: "productId required" });
  }

  const dailySales = estimateDailySales(reviewCount, rating, isRocket);

  store.salesEstimates.set(productId, {
    daily: dailySales,
    method: "review_based",
    reviewCount,
    rating,
    isRocket,
    price,
    category,
    updatedAt: Date.now(),
  });

  // 상품 캐시 업데이트
  store.products.set(productId, {
    data: {
      productId,
      estimatedDailySales: dailySales,
      estimatedMonthlySales: dailySales * 30,
      rank: null,
      category,
      lastUpdated: Date.now(),
    },
    updatedAt: Date.now(),
  });

  res.json({
    productId,
    estimatedDailySales: dailySales,
    estimatedMonthlySales: dailySales * 30,
    method: "review_based",
  });
});

// 판매 분석 리포트
app.get("/api/analysis/:productId", (req, res) => {
  const { productId } = req.params;

  // 재고 히스토리에서 판매량 분석
  // productId로 연결된 vendorItemId 찾기
  let salesHistory = [];
  const estimate = store.salesEstimates.get(productId);
  const productData = store.products.get(productId);
  const price = productData?.data?.price || 0;

  // 모든 재고 히스토리에서 해당 상품 찾기
  for (const [vid, history] of store.inventory.entries()) {
    if (history.length > 0) {
      // 판매량 계산
      for (let i = 1; i < history.length; i++) {
        if (history[i].stock !== null && history[i - 1].stock !== null) {
          const sales = Math.max(0, history[i - 1].stock - history[i].stock);
          salesHistory.push({
            date: history[i].date,
            stock: history[i].stock,
            sales,
            revenue: sales * price,
          });
        }
      }
    }
  }

  // 판매량 통계
  const last7 = salesHistory.slice(-7);
  const last30 = salesHistory.slice(-30);

  const avg7d =
    last7.length > 0
      ? Math.round(last7.reduce((s, d) => s + d.sales, 0) / last7.length)
      : estimate
        ? estimate.daily
        : 0;

  const avg30d =
    last30.length > 0
      ? Math.round(last30.reduce((s, d) => s + d.sales, 0) / last30.length)
      : estimate
        ? estimate.daily
        : 0;

  // 추세 계산
  let trend = 0;
  if (last7.length > 0 && last30.length > 0) {
    trend = avg30d > 0 ? ((avg7d - avg30d) / avg30d) * 100 : 0;
  }

  res.json({
    productId,
    summary: {
      avg7d,
      avg30d,
      trend,
      estimatedMonthlyRevenue: avg30d * 30 * price,
    },
    dailySales:
      salesHistory.length > 0
        ? salesHistory
        : generateMockSalesData(estimate?.daily || 0, price),
  });
});

// 카테고리 순위
app.get("/api/rank", (req, res) => {
  const { productId, categoryId } = req.query;

  // 실제로는 쿠팡 검색 결과 크롤링 필요
  // 여기서는 저장된 데이터 반환
  const estimate = store.salesEstimates.get(productId);

  res.json({
    productId,
    categoryId,
    rank: estimate?.rank || null,
    totalProducts: null,
    lastUpdated: Date.now(),
  });
});

// ─── 목 데이터 생성 (데이터 없을 때) ───
function generateMockSalesData(avgDaily, price) {
  const data = [];
  const now = new Date();

  for (let i = 29; i >= 0; i--) {
    const date = new Date(now);
    date.setDate(date.getDate() - i);

    // 약간의 랜덤 변동
    const variation = 0.7 + Math.random() * 0.6;
    const sales = Math.round(avgDaily * variation);

    data.push({
      date: date.toISOString().split("T")[0],
      stock: null,
      sales,
      revenue: sales * price,
    });
  }

  return data;
}

// ─── 404 처리 ───
app.use((req, res) => {
  res.status(404).json({
    error: "Not Found",
    path: req.path,
    message: `엔드포인트 ${req.method} ${req.path}를 찾을 수 없습니다.`,
  });
});

// ─── 에러 핸들러 ───
app.use((err, req, res, next) => {
  console.error(`[ERROR] ${err.message}`, err.stack);
  res.status(500).json({ error: "Internal Server Error" });
});

// ─── 서버 시작 ───
app.listen(PORT, () => {
  console.log(`🔍 쿠팡 엑스레이 서버 v4.0.1 시작`);
  console.log(`   포트: ${PORT}`);
  console.log(`   환경: ${process.env.NODE_ENV || "development"}`);
  console.log(`   시간: ${new Date().toISOString()}`);
});
