import time
import json
from urllib.parse import urljoin
from typing import Dict, Optional
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="am-qpi", description="API for scraping data from: https://quotes.toscrape.com", version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_URL = "https://quotes.toscrape.com"
PRESET_SELECTORS = {}
REQUIRED_API_KEY = ""

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"}
CACHE = {}
CACHE_TTL = 300

def verify_key(x_api_key: Optional[str] = Header(None)):
    if REQUIRED_API_KEY and x_api_key != REQUIRED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    return True

def get_soup(path: str = "", bypass_cache: bool = False) -> tuple[BeautifulSoup, str]:
    target = urljoin(BASE_URL, path) if path else BASE_URL
    now = time.time()
    if not bypass_cache and target in CACHE and (now - CACHE[target]["time"]) < CACHE_TTL:
        html_bytes = CACHE[target]["content"]
    else:
        try:
            resp = requests.get(target, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            html_bytes = resp.content
            CACHE[target] = {"content": html_bytes, "time": now}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Source fetch failed: {str(e)}")
    return BeautifulSoup(html_bytes, "html.parser"), target

class CustomScrapeModel(BaseModel):
    path: Optional[str] = ""
    selectors: Dict[str, str]
    attribute: Optional[str] = None

@app.get("/")
def home():
    return {"status": "online", "target": BASE_URL, "endpoints": ["/api/all", "/api/select", "/api/search", "/api/tables", "/docs"]}

@app.get("/api/all", dependencies=[Depends(verify_key)])
def extract_all(path: str = Query(""), limit: int = Query(30)):
    soup, full_url = get_soup(path)
    return {
        "url": full_url,
        "title": soup.title.string.strip() if soup.title else None,
        "headings": [{"tag": h.name, "text": h.get_text(strip=True)} for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)][:limit],
        "paragraphs": [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20][:limit],
        "links": [{"text": a.get_text(strip=True), "url": urljoin(full_url, a["href"])} for a in soup.find_all("a", href=True) if a.get_text(strip=True)][:limit],
        "images": [{"alt": img.get("alt", ""), "src": urljoin(full_url, img["src"])} for img in soup.find_all("img", src=True)][:limit]
    }

@app.get("/api/select", dependencies=[Depends(verify_key)])
def select_elements(selector: str = Query(...), attr: Optional[str] = Query(None), path: str = Query(""), limit: int = Query(50)):
    soup, full_url = get_soup(path)
    matched = soup.select(selector)[:limit]
    results = []
    for el in matched:
        if attr:
            val = el.get(attr)
            if val and attr in ["href", "src"]: val = urljoin(full_url, val)
            if val: results.append(val)
        else:
            results.append({"text": el.get_text(strip=True), "href": urljoin(full_url, el["href"]) if el.get("href") else None})
    return {"url": full_url, "selector": selector, "results": results}

@app.get("/api/search", dependencies=[Depends(verify_key)])
def search_in_page(q: str = Query(...), path: str = Query("")):
    soup, full_url = get_soup(path)
    q_lower = q.lower()
    matches = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "a"]):
        text = tag.get_text(strip=True)
        if q_lower in text.lower() and len(text) < 500:
            item = {"tag": tag.name, "text": text}
            if tag.name == "a" and tag.get("href"): item["url"] = urljoin(full_url, tag["href"])
            if item not in matches: matches.append(item)
    return {"url": full_url, "query": q, "matches": matches[:50]}

@app.get("/api/tables", dependencies=[Depends(verify_key)])
def extract_tables(path: str = Query("")):
    soup, full_url = get_soup(path)
    tables_data = []
    for idx, table in enumerate(soup.find_all("table")):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells and cells != headers:
                rows.append(dict(zip(headers, cells)) if headers and len(headers) == len(cells) else cells)
        if rows: tables_data.append({"index": idx, "rows": rows})
    return {"url": full_url, "tables": tables_data}
