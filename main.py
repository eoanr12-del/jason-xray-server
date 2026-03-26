"""
Jason Seller X-Ray — Backend API Server v2.2 (Final Fix)
파일명: main.py
수정사항: CORS 허용, 쿠팡 봇 탐지 우회, 502/404 에러 방지 로직 적용
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi import requests as curl_requests
import json, os, re, random, time, sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

app = FastAPI(title="Jason X-Ray API", version="2.2")

# [수정] 브라우저 콘솔에서 호출 시 발생하는 CORS 차단 방지
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# ── 쿠팡 크롤러 (curl_cffi TLS 위장 강화) ──
PROXIES = [
    {"addr":"31.59.20.176","port":"6754"}, {"addr":"23.95.150.145","port":"6114"},
    {"addr":"198.23.239.134","port":"6540"}, {"addr":"45.38.107.97","port":"6014"},
    {"addr":"107.172.163.27","port":"6543"}, {"addr":"198.105.121.200","port":"6462"},
    {"addr":"216.10.27.159","port":"6837"}, {"addr":"142.111.67.146","port":"5611"},
    {"addr":"191.96.254.138","port":"6185"}, {"addr":"31.58.9.4","port":"6077"},
]
PROXY_USER, PROXY_PASS = "rfblprmg", "5x2k0pvne9a0"

def get_proxy():
    p = random.choice(PROXIES)
    return f"http://{PROXY_USER}:{PROXY_PASS}@{p['addr']}:{p['port']}"

def crawl_coupang(pid: str) -> dict:
    """쿠팡 크롤링 — TLS 핑거프린팅 + 헤더 정교화"""
    urls = [
        f"https://www.coupang.com/vp/products/{pid}",
        f"https://m.coupang.com/vm/products/{pid}",
    ]
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ]
    for attempt in range(3):
        proxy, url = get_proxy(), random.choice(urls)
        try:
            resp = curl_requests.get(url, 
                impersonate="chrome110", 
                timeout=30,
                proxies={"http": proxy, "https": proxy},
                headers={
                    "User-Agent": random.choice(user_agents),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Referer": "https://www.google.com/",
                    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                })
            if resp.status_code != 200 or 'captcha' in resp.text.lower():
                continue
            html, data = resp.text, {"pid": pid}
            # 데이터 추출 로직
            for pat in [r'"itemName"\s*:\s*"([^"]+)"', r'"productName"\s*:\s*"([^"]+)"', r'<h1[^>]*>([^<]+)</h1>']:
                m = re.search(pat, html)
                if m: data["name"] = m.group(1).strip(); break
            for pat in [r'"salePrice"\s*:\s*(\d+)', r'"price"\s*:\s*(\d+)', r'total-price[^>]*>[\s]*<strong>([\d,]+)']:
                m = re.search(pat, html)
                if m: data["price"] = int(m.group(1).replace(",","")); break
            for pat in [r'"maxOrderableCount"\s*:\s*(\d+)', r'"usableInventoryQty"\s*:\s*(\d+)', r'단\s*(\d+)\s*개\s*남']:
                m = re.search(pat, html)
                if m: data["stock"] = int(m.group(1)); break
            if data.get("name") or data.get("price"):
                return data
        except:
            time.sleep(1)
            continue
    return None

def save_data(pid, data):
    today = datetime.now().strftime("%Y-%m-%d %H:00")
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO products (pid,name,price,updated_at) VALUES (?,?,?,?)",
            (pid, data.get("name",""), data.get("price",0), today))
        conn.execute("INSERT OR REPLACE INTO stock_history (pid,stock,price,recorded_at) VALUES (?,?,?,?)",
            (pid, data.get("stock",0), data.get("price",0), today))
        conn.commit()

@app.get("/")
def root():
    return {"status": "online", "version": "2.2"}

@app.post("/api/crawl/{pid}")
def crawl_now(pid: str):
    clean_pid = "".join(filter(str.isdigit, pid))
    if not clean_pid:
        raise HTTPException(status_code=400, detail="Invalid PID")
    data = crawl_coupang(clean_pid)
    if not data:
        raise HTTPException(status_code=502, detail="Crawl failed - bot detected")
    save_data(clean_pid, data)
    return {"ok": True, "data": data}

@app.on_event("startup")
def startup():
    init_db()