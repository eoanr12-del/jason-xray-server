"""
쿠팡 엑스레이 v4.0.1 - 백엔드 서버 (Python/Flask)
Render.com 배포용
"""

import os
import time
import math
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ─── 인메모리 저장소 ───
store = {
    "products": {},       # productId -> 상품 정보
    "inventory": {},      # vendorItemId -> 재고 히스토리 리스트
    "reports": {},        # productId -> 페이지뷰 리스트
    "sales_estimates": {} # productId -> 판매량 추정
}

START_TIME = time.time()


# ─── 유틸 ───
def estimate_daily_sales(review_count, rating, is_rocket):
    """리뷰 기반 판매량 추정"""
    if not review_count or review_count <= 0:
        return 0

    review_to_sales_ratio = 20

    total_estimated = review_count * review_to_sales_ratio

    if review_count > 1000:
        estimated_days = 365
    elif review_count > 500:
        estimated_days = 270
    elif review_count > 100:
        estimated_days = 180
    elif review_count > 30:
        estimated_days = 90
    else:
        estimated_days = 60

    daily = round(total_estimated / estimated_days)

    if rating and rating >= 4.5:
        daily = round(daily * 1.2)
    elif rating and rating >= 4.0:
        daily = round(daily * 1.1)
    elif rating and rating < 3.5:
        daily = round(daily * 0.8)

    if is_rocket:
        daily = round(daily * 1.15)

    return max(0, daily)


def generate_mock_sales(avg_daily, price):
    """데이터 없을 때 목업 판매 데이터 생성"""
    data = []
    now = datetime.now()
    for i in range(29, -1, -1):
        date = now - timedelta(days=i)
        import random
        variation = 0.7 + random.random() * 0.6
        sales = round(avg_daily * variation)
        data.append({
            "date": date.strftime("%Y-%m-%d"),
            "stock": None,
            "sales": sales,
            "revenue": sales * (price or 0)
        })
    return data


# ─── API 엔드포인트 ───

@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "name": "쿠팡 엑스레이 서버",
        "version": "4.0.1",
        "status": "running"
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": "4.0.1",
        "uptime": round(time.time() - START_TIME, 1),
        "timestamp": int(time.time() * 1000),
        "productsTracked": len(store["products"]),
        "inventoryTracked": len(store["inventory"])
    })


@app.route("/api/product/<product_id>", methods=["GET"])
def get_product(product_id):
    """상품 데이터 조회"""
    cached = store["products"].get(product_id)

    if cached and (time.time() - cached.get("updated_at", 0)) < 300:
        return jsonify(cached["data"])

    reports = store["reports"].get(product_id, [])
    estimate = store["sales_estimates"].get(product_id)

    response = {
        "productId": product_id,
        "estimatedDailySales": estimate["daily"] if estimate else None,
        "estimatedMonthlySales": estimate["daily"] * 30 if estimate else None,
        "rank": estimate.get("rank") if estimate else None,
        "category": estimate.get("category") if estimate else None,
        "pageViews": len(reports),
        "lastUpdated": int(time.time() * 1000)
    }

    return jsonify(response)


@app.route("/api/report", methods=["POST"])
def report():
    """페이지뷰 리포트"""
    data = request.get_json(silent=True) or {}
    product_id = data.get("productId")

    if not product_id:
        return jsonify({"error": "productId required"}), 400

    if product_id not in store["reports"]:
        store["reports"][product_id] = []

    store["reports"][product_id].append({
        "title": data.get("title"),
        "price": data.get("price"),
        "timestamp": data.get("timestamp", int(time.time() * 1000))
    })

    # 최근 1000개만 유지
    if len(store["reports"][product_id]) > 1000:
        store["reports"][product_id] = store["reports"][product_id][-1000:]

    # 상품 정보 업데이트
    store["products"][product_id] = {
        "data": {
            "productId": product_id,
            "title": data.get("title"),
            "price": data.get("price"),
            "estimatedDailySales": None,
            "lastUpdated": int(time.time() * 1000)
        },
        "updated_at": time.time()
    }

    return jsonify({"success": True})


@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    """재고 조회"""
    product_id = request.args.get("productId")
    vendor_item_id = request.args.get("vendorItemId")

    if not vendor_item_id:
        return jsonify({"error": "vendorItemId required"})

    history = store["inventory"].get(vendor_item_id, [])
    latest = history[-1] if history else None
    yesterday = history[-2] if len(history) > 1 else None

    return jsonify({
        "productId": product_id,
        "vendorItemId": vendor_item_id,
        "currentStock": latest["stock"] if latest else None,
        "yesterdayStock": yesterday["stock"] if yesterday else None,
        "trackingDays": len(history),
        "history": history[-30:]
    })


@app.route("/api/inventory/check", methods=["POST"])
def inventory_check():
    """재고 체크 (백그라운드용)"""
    vendor_item_id = request.args.get("vendorItemId")

    if not vendor_item_id:
        return jsonify({"error": "vendorItemId required"}), 400

    if vendor_item_id not in store["inventory"]:
        store["inventory"][vendor_item_id] = []

    today = datetime.now().strftime("%Y-%m-%d")
    history = store["inventory"][vendor_item_id]

    already = any(h["date"] == today for h in history)
    if not already:
        history.append({
            "date": today,
            "stock": None,
            "timestamp": int(time.time() * 1000)
        })

    return jsonify({"success": True, "date": today})


@app.route("/api/inventory/update", methods=["POST"])
def inventory_update():
    """재고 업데이트 (확장프로그램에서 호출)"""
    data = request.get_json(silent=True) or {}
    vendor_item_id = data.get("vendorItemId")
    stock = data.get("stock")
    product_id = data.get("productId")

    if not vendor_item_id or stock is None:
        return jsonify({"error": "vendorItemId and stock required"}), 400

    if vendor_item_id not in store["inventory"]:
        store["inventory"][vendor_item_id] = []

    today = datetime.now().strftime("%Y-%m-%d")
    history = store["inventory"][vendor_item_id]

    # 오늘 기록 업데이트 또는 추가
    today_idx = next((i for i, h in enumerate(history) if h["date"] == today), -1)
    if today_idx >= 0:
        history[today_idx]["stock"] = stock
        history[today_idx]["timestamp"] = int(time.time() * 1000)
    else:
        history.append({
            "date": today,
            "stock": stock,
            "timestamp": int(time.time() * 1000)
        })

    # 판매량 추정 업데이트
    if len(history) >= 2:
        recent = history[-7:]
        total_sales = 0
        days = 0
        for i in range(1, len(recent)):
            if recent[i]["stock"] is not None and recent[i-1]["stock"] is not None:
                diff = recent[i-1]["stock"] - recent[i]["stock"]
                if diff > 0:
                    total_sales += diff
                    days += 1

        avg_daily = round(total_sales / days) if days > 0 else 0
        key = product_id or vendor_item_id
        store["sales_estimates"][key] = {
            "daily": avg_daily,
            "method": "inventory_tracking",
            "updated_at": time.time()
        }

    return jsonify({"success": True, "recordCount": len(history)})


@app.route("/api/estimate", methods=["POST"])
def estimate():
    """판매량 추정 (리뷰 기반)"""
    data = request.get_json(silent=True) or {}
    product_id = data.get("productId")

    if not product_id:
        return jsonify({"error": "productId required"}), 400

    daily = estimate_daily_sales(
        data.get("reviewCount", 0),
        data.get("rating"),
        data.get("isRocket", False)
    )

    store["sales_estimates"][product_id] = {
        "daily": daily,
        "method": "review_based",
        "reviewCount": data.get("reviewCount"),
        "rating": data.get("rating"),
        "isRocket": data.get("isRocket"),
        "price": data.get("price"),
        "category": data.get("category"),
        "updated_at": time.time()
    }

    store["products"][product_id] = {
        "data": {
            "productId": product_id,
            "estimatedDailySales": daily,
            "estimatedMonthlySales": daily * 30,
            "rank": None,
            "category": data.get("category"),
            "lastUpdated": int(time.time() * 1000)
        },
        "updated_at": time.time()
    }

    return jsonify({
        "productId": product_id,
        "estimatedDailySales": daily,
        "estimatedMonthlySales": daily * 30,
        "method": "review_based"
    })


@app.route("/api/analysis/<product_id>", methods=["GET"])
def analysis(product_id):
    """판매 분석 리포트"""
    estimate = store["sales_estimates"].get(product_id)
    product_data = store["products"].get(product_id)
    price = product_data["data"].get("price", 0) if product_data else 0

    sales_history = []

    # 재고 히스토리에서 판매량 계산
    for vid, history in store["inventory"].items():
        if len(history) > 1:
            for i in range(1, len(history)):
                if history[i]["stock"] is not None and history[i-1]["stock"] is not None:
                    sales = max(0, history[i-1]["stock"] - history[i]["stock"])
                    sales_history.append({
                        "date": history[i]["date"],
                        "stock": history[i]["stock"],
                        "sales": sales,
                        "revenue": sales * (price or 0)
                    })

    last7 = sales_history[-7:] if sales_history else []
    last30 = sales_history[-30:] if sales_history else []

    avg7d = round(sum(d["sales"] for d in last7) / len(last7)) if last7 else (estimate["daily"] if estimate else 0)
    avg30d = round(sum(d["sales"] for d in last30) / len(last30)) if last30 else (estimate["daily"] if estimate else 0)

    trend = 0
    if avg30d > 0 and last7 and last30:
        trend = ((avg7d - avg30d) / avg30d) * 100

    return jsonify({
        "productId": product_id,
        "summary": {
            "avg7d": avg7d,
            "avg30d": avg30d,
            "trend": round(trend, 1),
            "estimatedMonthlyRevenue": avg30d * 30 * (price or 0)
        },
        "dailySales": sales_history if sales_history else generate_mock_sales(
            estimate["daily"] if estimate else 0,
            price
        )
    })


@app.route("/api/rank", methods=["GET"])
def rank():
    """카테고리 순위"""
    product_id = request.args.get("productId")
    category_id = request.args.get("categoryId")

    estimate = store["sales_estimates"].get(product_id)

    return jsonify({
        "productId": product_id,
        "categoryId": category_id,
        "rank": estimate.get("rank") if estimate else None,
        "totalProducts": None,
        "lastUpdated": int(time.time() * 1000)
    })


# ─── 404 처리 ───
@app.errorhandler(404)
def not_found(e):
    return jsonify({
        "error": "Not Found",
        "path": request.path,
        "message": f"엔드포인트 {request.method} {request.path}를 찾을 수 없습니다."
    }), 404


# ─── 500 처리 ───
@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal Server Error"}), 500


# ─── 서버 시작 ───
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🔍 쿠팡 엑스레이 서버 v4.0.1 시작")
    print(f"   포트: {port}")
    print(f"   시간: {datetime.now().isoformat()}")
    app.run(host="0.0.0.0", port=port, debug=False)
