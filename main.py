"""
Jason Seller X-Ray — Backend API Server v2.3 (Ultra Secure)
수정 사항: 
1. 봇 탐지 우회 로직 극대화 (쿠키 세션 흉내)
2. 잘못된 PID(search 등) 유입 시 에러 처리 강화
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi import requests as curl_requests
import json, os, re, random, time, sqlite3
from datetime import datetime
from contextlib import contextmanager

app = FastAPI()

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
    try: yield conn
    finally: conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS products (pid TEXT PRIMARY KEY, name TEXT, price INTEGER, updated_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS stock_history (pid TEXT, stock INTEGER, price INTEGER, recorded_at TEXT)")
        conn.commit()

PROXIES = [
    {"addr":"31.59.20.176","port":"6754"}, {"addr":"23.95.150.145","port":"6114"},
    {"addr":"198.23.239.134","port":"6540"}, {"addr":"45.38.107.97","port":"6014"}
]
PROXY_USER, PROXY_PASS = "rfblprmg", "5x2k0pvne9a0"

def get_proxy():
    p = random.choice(PROXIES)
    return f"http://{PROXY_USER}:{PROXY_PASS}@{p['addr']}:{p['port']}"

def crawl_coupang(pid: str):
    url = f"https://www.coupang.com/vp/products/{pid}"
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ]
    
    for attempt in range(3):
        try:
            proxy = get_proxy()
            # [핵심 수정] 쿠팡의 봇 탐지를 피하기 위해 세션 유지 및 헤더 강화
            resp = curl_requests.get(url, 
                impersonate="chrome110", 
                timeout=30,
                proxies={"http": proxy, "https": proxy},
                headers={
                    "User-Agent": random.choice(user_agents),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                    "Referer": "https://www.google.com/",
                    "Cache-Control": "max-age=0"
                })
            
            html = resp.text
            if resp.status_code == 200 and 'productName' in html:
                data = {"pid": pid}
                # 정규식으로 데이터 추출
                name = re.search(r'"itemName"\s*:\s*"([^"]+)"', html)
                price = re.search(r'"salePrice"\s*:\s*(\d+)', html)
                stock = re.search(r'"usableInventoryQty"\s*:\s*(\d+)', html)
                
                if name: data["name"] = name.group(1)
                if price: data["price"] = int(price.group(1))
                if stock: data["stock"] = int(stock.group(1))
                return data
            
            time.sleep(random.uniform(1, 2))
        except: continue
    return None

@app.post("/api/crawl/{pid}")
def crawl_now(pid: str):
    # [수정] 숫자가 아닌 PID(예: search)가 들어오면 즉시 차단
    if not pid.isdigit():
        raise HTTPException(status_code=400, detail=f"Invalid Product ID: {pid}. 상품 상세 페이지에서 실행해주세요.")
        
    data = crawl_coupang(pid)
    if not data:
        raise HTTPException(status_code=502, detail="Crawl failed - 여전히 쿠팡에서 차단 중입니다. 프록시 확인이 필요합니다.")
    
    # DB 저장 로직 (생략 가능하나 유지를 권장)
    return {"ok": True, "data": data}

@app.on_event("startup")
def startup(): init_db()