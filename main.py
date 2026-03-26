"""
Jason Seller X-Ray — Backend API Server v2
쿠팡 재고 추적 + 브라우저 위장 크롤링
"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi import requests as curl_requests
import json, os, re, random, time, sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

app = FastAPI(title="Jason X-Ray API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = os.environ.get("DB_PATH", "/tmp/xray.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS products (
            pid TEXT PRIMARY KEY, name TEXT, price INTEGER DEFAULT 0,
            rating REAL DEFAULT 0, review_count INTEGER DEFAULT 0, updated_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stock_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT NOT NULL,
            stock INTEGER NOT NULL, price INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0, recorded_at TEXT NOT NULL,
            UNIQUE(pid, recorded_at))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tracking (
            pid TEXT PRIMARY KEY, url TEXT, added_at TEXT, active INTEGER DEFAULT 1)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sh_pid ON stock_history(pid)")
        conn.commit()

# ── 쿠팡 크롤러 (curl_cffi = 브라우저 TLS 위장) ──
def crawl_coupang(pid: str) -> dict:
    """쿠팡 크롤링 — 모바일 페이지 + 쿠키 위장"""
    urls = [
        f"https://m.coupang.com/vm/products/{pid}",
        f"https://www.coupang.com/vp/products/{pid}",
    ]
    
    user_agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36",
    ]
    
    for url in urls:
        try:
            resp = curl_requests.get(url, 
                impersonate="chrome",
                timeout=20,
                headers={
                    "User-Agent": random.choice(user_agents),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Cache-Control": "no-cache",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                    "Referer": "https://www.google.com/",
                },
                cookies={"PCID": f"p{random.randint(10000000,99999999)}", "x-coupang-accept-language": "ko-KR"}
            )
            if resp.status_code != 200:
                continue
            html = resp.text
            if len(html) < 1000 or 'captcha' in html.lower() or 'robot' in html.lower():
                continue
                
            data = {"pid": pid}
            
            # 상품명 (모바일 + 데스크톱)
            for pat in [r'<h1[^>]*>([^<]+)</h1>', r'prod-buy-header__title[^>]*>([^<]+)', r'"itemName"\s*:\s*"([^"]+)"', r'"productName"\s*:\s*"([^"]+)"']:
                m = re.search(pat, html)
                if m: data["name"] = m.group(1).strip(); break
            
            # 가격
            for pat in [r'"salePrice"\s*:\s*(\d+)', r'"price"\s*:\s*(\d+)', r'total-price[^>]*>[\s]*<strong>([\d,]+)', r'<strong[^>]*>([\d,]+)\s*원']:
                m = re.search(pat, html)
                if m: data["price"] = int(m.group(1).replace(",","")); break
            
            # 리뷰 수
            for pat in [r'"ratingTotalCount"\s*:\s*(\d+)', r'"reviewCount"\s*:\s*(\d+)', r'count-num[^>]*>\(?([\d,]+)\)?']:
                m = re.search(pat, html)
                if m: data["review_count"] = int(m.group(1).replace(",","")); break
            
            # 평점
            for pat in [r'"ratingAverage"\s*:\s*([\d.]+)', r'"rating"\s*:\s*([\d.]+)']:
                m = re.search(pat, html)
                if m: data["rating"] = float(m.group(1)); break
            
            # 재고 (핵심!)
            for pat in [r'"maxOrderableCount"\s*:\s*(\d+)', r'"usableInventoryQty"\s*:\s*(\d+)', r'"stockCount"\s*:\s*(\d+)', r'단\s*(\d+)\s*개\s*남']:
                m = re.search(pat, html)
                if m: data["stock"] = int(m.group(1)); break
            
            if data.get("name") or data.get("price"):
                print(f"[Crawl OK] {pid}: {data}")
                return data
        except Exception as e:
            print(f"[Crawl Error] {pid} {url}: {e}")
            continue
    
    print(f"[Crawl FAIL] {pid}: all attempts blocked")
    return None

def save_data(pid, data):
    today = datetime.now().strftime("%Y-%m-%d %H:00")
    with get_db() as conn:
        conn.execute("""INSERT OR REPLACE INTO products (pid,name,price,rating,review_count,updated_at)
            VALUES (?,?,?,?,?,?)""", (pid, data.get("name",""), data.get("price",0),
            data.get("rating",0), data.get("review_count",0), today))
        conn.execute("""INSERT OR REPLACE INTO stock_history (pid,stock,price,review_count,recorded_at)
            VALUES (?,?,?,?,?)""", (pid, data.get("stock",0), data.get("price",0),
            data.get("review_count",0), today))
        conn.execute("""INSERT OR IGNORE INTO tracking (pid,url,added_at,active)
            VALUES (?,?,?,1)""", (pid, f"https://www.coupang.com/vp/products/{pid}", datetime.now().isoformat()))
        conn.commit()

# ── API ──
@app.get("/")
def root():
    return {"service": "Jason X-Ray API", "status": "running", "version": "2.0"}

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

# 확장 프로그램에서 수집한 데이터 수신
@app.post("/api/report")
async def report(request: Request):
    try:
        data = await request.json()
    except:
        return {"ok": False}
    pid = str(data.get("pid",""))
    if not pid: return {"ok": False}
    save_data(pid, data)
    return {"ok": True, "pid": pid}

@app.post("/api/track")
def add_track(pid: str, url: str = ""):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO tracking (pid,url,added_at,active) VALUES (?,?,?,1)",
            (pid, url or f"https://www.coupang.com/vp/products/{pid}", datetime.now().isoformat()))
        conn.commit()
    return {"ok": True, "pid": pid}

@app.get("/api/track")
def list_track():
    with get_db() as conn:
        rows = conn.execute("""SELECT t.pid,t.url,t.added_at,p.name,p.price,p.review_count
            FROM tracking t LEFT JOIN products p ON t.pid=p.pid WHERE t.active=1
            ORDER BY t.added_at DESC""").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/product/{pid}")
def get_product(pid: str):
    with get_db() as conn:
        product = conn.execute("SELECT * FROM products WHERE pid=?", (pid,)).fetchone()
        since = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")
        history = conn.execute("""SELECT stock,price,review_count,recorded_at FROM stock_history
            WHERE pid=? AND recorded_at>=? ORDER BY recorded_at ASC""", (pid, since)).fetchall()
    if not product:
        raise HTTPException(404, "Not found")
    history = [dict(h) for h in history]
    product = dict(product)
    
    # 판매량 계산: 재고 감소량
    sales = 0
    if len(history) >= 2:
        for i in range(1, len(history)):
            diff = history[i-1]["stock"] - history[i]["stock"]
            if diff > 0: sales += diff  # 재고가 줄어든 것만 (입고 제외)
        # 리뷰 증가량 기반 추정도 병행
        review_diff = history[-1]["review_count"] - history[0]["review_count"]
        if review_diff > 0:
            review_sales = int(review_diff / 0.04)
            sales = max(sales, review_sales)
    
    views = int(sales / 0.03) if sales > 0 else 0
    return {**product, "history": history, "estimated_sales_28d": sales,
            "estimated_views_28d": views, "data_points": len(history)}

@app.post("/api/crawl/{pid}")
def crawl_now(pid: str):
    """서버에서 직접 쿠팡 크롤링"""
    data = crawl_coupang(pid)
    if not data:
        raise HTTPException(502, "Crawl failed - bot detected or network error")
    save_data(pid, data)
    return {"ok": True, "data": data}

@app.post("/api/crawl-all")
def crawl_all():
    """추적 중인 모든 상품 크롤링"""
    with get_db() as conn:
        rows = conn.execute("SELECT pid FROM tracking WHERE active=1").fetchall()
    results = []
    for row in rows:
        pid = row["pid"]
        time.sleep(random.uniform(3, 8))  # 차단 방지 딜레이
        data = crawl_coupang(pid)
        if data:
            save_data(pid, data)
            results.append({"pid": pid, "stock": data.get("stock"), "ok": True})
        else:
            results.append({"pid": pid, "ok": False})
    return {"crawled": len(results), "results": results}

@app.get("/api/stats")
def get_stats():
    with get_db() as conn:
        t = conn.execute("SELECT COUNT(*) as c FROM tracking WHERE active=1").fetchone()["c"]
        p = conn.execute("SELECT COUNT(*) as c FROM products").fetchone()["c"]
        r = conn.execute("SELECT COUNT(*) as c FROM stock_history").fetchone()["c"]
        l = conn.execute("SELECT MAX(recorded_at) as l FROM stock_history").fetchone()["l"]
    return {"tracking": t, "products": p, "records": r, "latest": l}

@app.on_event("startup")
def startup():
    init_db()
    print("[Server] Jason X-Ray API v2 started - curl_cffi enabled")
