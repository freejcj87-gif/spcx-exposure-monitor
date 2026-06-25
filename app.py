# -*- coding: utf-8 -*-
"""
SpaceX (SPCX) 익스포저 모니터 — 미래에셋생명 PI운용팀
Streamlit + yfinance 라이브 대시보드. 접속할 때마다 시세 자동 갱신.

갱신/수정 포인트
  - 포지션 고정값: CONSTANTS
  - 추적 티커:     TICKERS
  - 락업/촉매:     LOCKUP, CATALYSTS
비밀번호: .streamlit/secrets.toml 의 APP_PASSWORD (미설정 시 게이트 생략)
"""
import datetime as dt
import json
import math
import pathlib
import re
import urllib.request
import urllib.parse
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh
try:
    import tomllib                 # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib        # 폴백 (구버전)

KST = dt.timezone(dt.timedelta(hours=9))   # 서버가 UTC여도 항상 KST로 표기

# ============================================================
# 0. 페이지 설정 + 비밀번호 게이트
# ============================================================
st.set_page_config(page_title="SPCX 익스포저 모니터", page_icon="🚀", layout="wide")

def check_password() -> bool:
    try:
        pw = st.secrets.get("APP_PASSWORD", None)
    except Exception:                # secrets.toml 자체가 없으면 예외 → 게이트 생략
        pw = None
    if not pw:                       # 비밀번호 미설정(로컬 등) → 게이트 생략
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.markdown("### 🔒 SPCX 익스포저 모니터")
    entered = st.text_input("접근 비밀번호", type="password")
    if entered == pw:
        st.session_state["auth_ok"] = True
        return True
    if entered:
        st.error("비밀번호가 올바르지 않습니다.")
    return False

if not check_password():
    st.stop()

# 열린 탭도 주기적으로 자동 재실행 → 시세 항상 최신 (접속 시에도 매번 재실행됨)
st_autorefresh(interval=300000, key="auto_refresh")   # 5분

# ============================================================
# 1. 포지션 고정값 (CONSTANTS) — 갱신 시 여기만
# ============================================================
# 당사 데이터는 config.toml 한 파일에서 로드 (수정·확장은 그 파일만 편집)
CFG_PATH = pathlib.Path(__file__).parent / "config.toml"
try:
    with open(CFG_PATH, "rb") as _f:
        CFG = tomllib.load(_f)
except FileNotFoundError:
    st.error("⚠ config.toml 을 찾을 수 없습니다. repo 루트에 config.toml 이 있어야 합니다.")
    st.stop()

_pos, _firm, _sx = CFG["position"], CFG["firm"], CFG["spacex"]
CONSTANTS = dict(
    shares=int(_pos["shares"]),
    costUSD=float(_pos["cost_usd"]),
    costKRW=float(_pos["cost_krw"]),
    bep=float(_pos["bep"]),
    buyFX=float(_pos["buy_fx"]),
    ipoPrice=float(_sx["ipo_price"]),
    trigger=float(_sx["trigger"]),
    equityKRW=float(_firm["equity_krw"]),
    sharesOut=int(_sx["shares_out"]),
)

# 추적 티커
TICKERS = dict(
    spcx="SPCX",
    fx="KRW=X",
    sp500="^GSPC",
    nasdaq="^IXIC",
    etf=[("ARKX", "ARK Space & Defense"),
         ("UFO", "Procure Space"),
         ("ROKT", "SPDR Kensho Final Frontiers")],
    peers=[("RKLB", "Rocket Lab", "재사용 발사체 · 소형위성"),
           ("ASTS", "AST SpaceMobile", "위성-스마트폰 직접통신"),
           ("LUNR", "Intuitive Machines", "달 착륙선 · NASA 계약")],
)

# 락업/Release 일정 (정적)
LOCKUP = [
    ("IPO 첫날", "6/12", "공모+그린슈+DSP+secondary", 5.7, False),
    ("a · 2Q 후", "~8월", "Eligible 20% 첫 release", 13.3, True),
    ("b · 조건부", "조건부", "종가 $175.50 5거래일↑ 충족 시", 17.1, True),
    ("c-1~c-5", "8/21~10/25", "정기 release 5회", 30.4, False),
    ("d · 3Q 후", "~11월", "Eligible 28% 일괄 (단일 최대)", 41.0, True),
    ("e · 180일", "12/9", "180일 트랙 종료", 43.7, False),
    ("f · 366일", "2027/6/12", "Musk + 주요투자자 해제", 100, True),
]

# 촉매 캘린더 (정적)
CATALYSTS = [
    ("6/17", False, "ASTS BlueBird 8/9/10 위성 발사", "피어 — 위성통신 캐파 확대"),
    ("~7월", False, "Starship Flight 13 (V3 2호기) 발사", "발사 성패 = 테마 모멘텀"),
    ("~8월", True, "SpaceX 2Q 실적 → Lock-up a (20% 해제)", "첫 대규모 release"),
    ("조건부", True, "종가 $175.50 ≥5거래일 충족 시 Lock-up b (+10%)", "트리거 충족 카운트 진행"),
    ("8~10월", False, "정기 release c-1~c-5 (누적 30.4%)", "8/21·9/10·9/25·10/10·10/25"),
    ("~11월", True, "SpaceX 3Q 실적 → Lock-up d (28% 일괄)", "단일 최대 오버행 ⚠"),
    ("11~12월", False, "Starship Mars 발사 윈도우", "장기 모멘텀 이벤트"),
    ("12/9", False, "180일 트랙 종료 (e, 누적 43.7%)", ""),
    ("'27 6/12", True, "Musk + 주요투자자 해제 (f, 100%)", "최종 오버행 해소"),
]

ANALYST = {**dict(avg=164, high=227, low=63, rating="Buy"), **CFG.get("analyst", {})}  # config.toml

# ============================================================
# 2. 라이브 데이터 (yfinance) — 15분 캐시
# ============================================================
def _num(x):
    """NaN/None/비정상 → None, 정상 → float. (신규 상장주 NaN 방어)"""
    try:
        x = float(x)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None

@st.cache_data(ttl=300, show_spinner=False)
def fetch_quote(ticker: str) -> dict:
    """price / prevClose / dayChg% / ytd% 반환. fast_info 결측·NaN 시 None (→ 폴백)."""
    out = dict(price=None, prev=None, day=None, ytd=None)
    try:
        t = yf.Ticker(ticker)
        fi = getattr(t, "fast_info", {}) or {}
        # 가격은 fast_info 우선, 결측 시 공식 일봉(dropna) 최신/직전 종가로 보완 → 항상 최신 라이브
        out["price"] = _num(fi.get("last_price") or fi.get("lastPrice"))
        out["prev"] = _num(fi.get("previous_close") or fi.get("previousClose"))
        if out["price"] is None or out["prev"] is None:
            d = t.history(period="1mo", interval="1d").dropna(subset=["Close"])
            if not d.empty:
                if out["price"] is None:
                    out["price"] = _num(d["Close"].iloc[-1])
                if out["prev"] is None and len(d) > 1:
                    out["prev"] = _num(d["Close"].iloc[-2])
        if out["price"] and out["prev"]:
            out["day"] = (out["price"] - out["prev"]) / out["prev"] * 100
        ytd = t.history(period="ytd").dropna(subset=["Close"])
        if not ytd.empty and out["price"]:
            base = _num(ytd["Close"].iloc[0])
            if base:
                out["ytd"] = (out["price"] - base) / base * 100
    except Exception:
        pass
    return out

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_news(ticker: str, n: int = 5) -> list:
    items = []
    try:
        for a in (yf.Ticker(ticker).news or [])[:n]:
            c = a.get("content", a)
            title = c.get("title") or a.get("title")
            pub = (c.get("provider", {}) or {}).get("displayName") or a.get("publisher") or ""
            link = (c.get("canonicalUrl", {}) or {}).get("url") or a.get("link") or "#"
            if title:
                items.append(dict(t=title, s=pub, u=link))
    except Exception:
        pass
    return items

# 폴백 (yfinance 실패 시 마지막 확인치 · 2026-06-15)
FALLBACK = {
    "SPCX": dict(price=154.60, prev=185.00, day=-16.43, ytd=None),
    "KRW=X": dict(price=1543.86, prev=1535.25, day=None, ytd=None),
    "^GSPC": dict(price=7555.26, prev=7431.46, day=1.67, ytd=None),
    "^IXIC": dict(price=26683.94, prev=25888.84, day=3.07, ytd=None),
    "ARKX": dict(price=33.78, prev=34.45, day=-1.9, ytd=11.0),
    "UFO": dict(price=52.92, prev=None, day=None, ytd=31.0),
    "ROKT": dict(price=120.01, prev=None, day=None, ytd=58.0),
    "RKLB": dict(price=102.39, prev=None, day=None, ytd=None),
    "ASTS": dict(price=82.41, prev=None, day=None, ytd=None),
    "LUNR": dict(price=26.62, prev=None, day=None, ytd=None),
    "CMTG": dict(price=2.67, prev=None, day=None, ytd=None),
}
FALLBACK_NEWS = [
    dict(t="SpaceX, 첫 정규거래일 +20% 급등 — SPCX $192.50 마감, 시총 ≈$2.5조",
         s="CNBC", u="https://www.cnbc.com/2026/06/15/spacex-stock-record-ipo-debut.html"),
    dict(t="왜 오르나 — 낮은 유통물량·목표가 상향 기대가 SPCX 랠리 견인",
         s="IndMoney", u="https://www.indmoney.com/blog/us-stocks/why-is-spacex-spcx-stock-rising-today"),
    dict(t="Lock-up 구조: 2Q 실적 후 ~20% 해제, 조건부 +10%, Musk는 366일",
         s="TradingView", u="https://www.tradingview.com/symbols/NASDAQ-SPCX/"),
]

@st.cache_data(ttl=300, show_spinner=False)
def fetch_history(ticker: str, period: str = "3mo") -> dict:
    """일봉 OHLCV. 신규 상장주의 daily 결측일(NaN)은 1시간봉을 일봉으로 합쳐 보완."""
    try:
        t = yf.Ticker(ticker)
        rows = {}   # 'YYYY-MM-DD' -> (O, H, L, C, V)
        daily = t.history(period=period, interval="1d").dropna(subset=["Open", "High", "Low", "Close"])
        for ts, r in daily.iterrows():
            rows[str(ts)[:10]] = (r["Open"], r["High"], r["Low"], r["Close"], r["Volume"])
        # daily 에 없는 최근 거래일은 1시간봉 → 일봉 리샘플로 보완
        intr = t.history(period="5d", interval="1h")
        if not intr.empty:
            agg = intr.resample("1D").agg({"Open": "first", "High": "max", "Low": "min",
                                           "Close": "last", "Volume": "sum"}).dropna()
            for ts, r in agg.iterrows():
                rows.setdefault(str(ts)[:10], (r["Open"], r["High"], r["Low"], r["Close"], r["Volume"]))
        if not rows:
            return None
        dates = sorted(rows)
        return {
            "Date": dates,
            "Open": [float(rows[d][0]) for d in dates],
            "High": [float(rows[d][1]) for d in dates],
            "Low": [float(rows[d][2]) for d in dates],
            "Close": [float(rows[d][3]) for d in dates],
            "Volume": [float(rows[d][4]) for d in dates],
        }
    except Exception:
        return None

@st.cache_data(ttl=21600, show_spinner=False)   # 6시간 캐시 (API rate limit 보호)
def fetch_launches(n: int = 7) -> list:
    """SpaceX 예정 발사 (Launch Library 2, lsp__id=121=SpaceX). 실패 시 None."""
    url = ("https://ll.thespacedevs.com/2.2.0/launch/upcoming/"
           "?lsp__id=121&limit=%d" % n)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spcx-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.load(r)
        out = []
        for L in data.get("results", []):
            name = L.get("name", "") or ""
            rocket = (((L.get("rocket") or {}).get("configuration") or {}).get("name")
                      or (name.split("|")[0].strip() if "|" in name else ""))
            mission_name = name.split("|")[1].strip() if "|" in name else name
            mission = L.get("mission") or {}
            mtype = mission.get("type") or ""
            orbit = ((mission.get("orbit") or {}) or {}).get("abbrev") or ""
            sig = " · ".join([s for s in [mtype, orbit] if s])
            out.append(dict(net=(L.get("net") or "")[:10], rocket=rocket,
                            name=mission_name, sig=sig))
        return out or None
    except Exception:
        return None

FALLBACK_LAUNCHES = [
    dict(net="2026-06-17", rocket="Falcon 9", name="Starlink Group (위성 인터넷 증설)", sig="LEO · 통신"),
    dict(net="~2026-07", rocket="Starship V3", name="Flight 13 (2호기 시험비행)", sig="차세대 초대형 발사체"),
    dict(net="2026-11~12", rocket="Starship", name="Mars 발사 윈도우", sig="화성 무인 탐사"),
]

@st.cache_data(ttl=86400, show_spinner=False)
def translate_ko(text: str) -> str:
    """영문 제목을 국문으로 번역 (한글이거나 실패하면 원문 유지)."""
    if not text or not re.search(r"[A-Za-z]", text):
        return text
    if len(re.findall(r"[가-힣]", text)) > 3:        # 이미 한글 제목
        return text
    try:
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=en&tl=ko&dt=t&q=" + urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        return "".join(seg[0] for seg in data[0] if seg and seg[0]) or text
    except Exception:
        return text

def q(ticker: str) -> dict:
    d = fetch_quote(ticker)
    if d.get("price") is None:                 # 라이브 실패 → 폴백
        return dict(FALLBACK.get(ticker, d), _stale=True)
    fb = FALLBACK.get(ticker, {})
    for k in ("ytd", "day"):                    # 부분 결측은 폴백으로 보완
        if d.get(k) is None and fb.get(k) is not None:
            d[k] = fb[k]
    d["_stale"] = False
    return d

# ============================================================
# 3. 데이터 취합 + 파생 계산
# ============================================================
C = CONSTANTS
spcx = q(TICKERS["spcx"]); fx = q(TICKERS["fx"])
sp = q(TICKERS["sp500"]); nq = q(TICKERS["nasdaq"])
etf_q = [(tk, nm, q(tk)) for tk, nm in TICKERS["etf"]]
peer_q = [(tk, nm, note, q(tk)) for tk, nm, note in TICKERS["peers"]]
news = fetch_news(TICKERS["spcx"]) or FALLBACK_NEWS
news = [dict(n, t=translate_ko(n.get("t", ""))) for n in news]   # 영문 제목 → 국문
domestic = CFG.get("domestic_fund", [])
cmtg = q("CMTG")                                  # 환오픈 모니터용 (100% 환헷지)
hist = fetch_history(TICKERS["spcx"])
launches = fetch_launches() or FALLBACK_LAUNCHES
_recent = (hist["Close"] if hist else [])[-10:]                  # 최근 10영업일 종가
trig_window = len(_recent)
trig_met = sum(1 for c in _recent if c >= CONSTANTS["trigger"])  # 트리거 충족 일수

px = spcx["price"]; fxr = fx["price"]
# SPCX 가격·전일종가는 공식 일봉(hist) 기준으로 통일 → 야후 일봉 종가와 일치
# (hist는 공식 daily 우선, 아직 일봉이 안 뜬 최근 1일만 분봉으로 보완)
if hist and hist.get("Close"):
    px = hist["Close"][-1]
    if len(hist["Close"]) > 1:
        spcx["prev"] = hist["Close"][-2]
valUSD = C["shares"] * px
plUSD = valUSD - C["costUSD"]; retUSD = plUSD / C["costUSD"] * 100
valKRW = valUSD * fxr
plKRW = valKRW - C["costKRW"]; retKRW = plKRW / C["costKRW"] * 100
upside = (px - C["ipoPrice"]) / C["ipoPrice"] * 100
dayChg = ((px - spcx["prev"]) / spcx["prev"] * 100) if spcx.get("prev") else (spcx.get("day") or 0)
aboveTrig = (px - C["trigger"]) / C["trigger"] * 100
expoRatio = valKRW / C["equityKRW"] * 100
fxChg = (fxr - C["buyFX"]) / C["buyFX"] * 100
fxPL = valUSD * (fxr - C["buyFX"])      # 환차손익 = 현재 외화평가액 × (현재환율 − 매입환율)
mktcap = px * C["sharesOut"]
gMin, gMax = C["bep"], ANALYST["high"]
def gpos(p): return max(0.0, min(100.0, (p - gMin) / (gMax - gMin) * 100))

stale = spcx.get("_stale") or fx.get("_stale")
now = dt.datetime.now(KST)
asof = now.strftime("%Y-%m-%d %H:%M KST") + (" · ⚠ 라이브 실패, 폴백값" if stale else " · 라이브")

# 기간별 평가손익 기준가
#  - 취득이 해당 기간(올해/이번달) 내면 기준 = 취득단가(=BEP) → 누적=YTD=당월
#  - 취득이 이전 기간이면 기준 = 그 기간초 종가
#  - 당일 = 전일 종가
cost_ps = C["costUSD"] / C["shares"]               # 취득 단가 (= BEP $140.77)
base_day = spcx.get("prev") or cost_ps
_acq = CFG["position"].get("acquired", "")
_ay = int(_acq[:4]) if len(_acq) >= 4 else None
_am = int(_acq[5:7]) if len(_acq) >= 7 else None
def _pbase(kind):
    if not hist:
        return None
    for d, c in zip(hist["Date"], hist["Close"]):
        if kind == "ytd" and int(d[:4]) == now.year:
            return c
        if kind == "mtd" and int(d[:4]) == now.year and int(d[5:7]) == now.month:
            return c
    return None
base_ytd = cost_ps if _ay == now.year else (_pbase("ytd") or cost_ps)
base_mtd = cost_ps if (_ay == now.year and _am == now.month) else (_pbase("mtd") or cost_ps)

# ============================================================
# 4. 포맷 헬퍼
# ============================================================
def usd(n):  return "$" + f"{round(n):,}"
def usd2(n): return "$" + f"{n:,.2f}"
def krw(n):  return "₩" + f"{round(n):,}"
def eok(n):  return f"{n/1e8:,.0f}억"
def pct(n):  return ("+" if n >= 0 else "") + f"{n:.1f}%"
def sgn(n):  return "pos" if n >= 0 else "neg"
def tcap(n): return f"≈ ${n/1e12:.1f}T"

# ---- 평가손익 구분 (누적/YTD/당월/당일) ----
def pnl_grid() -> str:
    def cell(label, base, note):
        if not base:
            return f'<div class="pnl-i"><span>{label}</span><b>—</b><u>{note}</u></div>'
        p = C["shares"] * (px - base); r = (px - base) / base * 100
        return (f'<div class="pnl-i"><span>{label}</span>'
                f'<b class="{sgn(p)}">{pct(r)}</b>'
                f'<i class="{sgn(p)}">{("+" if p >= 0 else "")+usd(p)}</i>'
                f'<u>{note}</u></div>')
    cum_base = C["costUSD"] / C["shares"]   # = BEP $140.77 (평가손익은 BEP 기준)
    return ('<div class="pnl">'
            + cell("누적", cum_base, f"BEP ${cum_base:.2f}")
            + cell("YTD", base_ytd, (f"vs ${base_ytd:,.2f}" if base_ytd else ""))
            + cell("당월", base_mtd, (f"vs ${base_mtd:,.2f}" if base_mtd else ""))
            + cell("당일", base_day, (f"vs ${base_day:,.2f}" if base_day else ""))
            + '</div>'
            + '<div style="font-size:9.5px;color:var(--muted);margin-top:5px;line-height:1.5">'
              "YTD·당월은 6월 취득분이라 누적과 동일 (기간 경과 시 분화) · 당일=전일 종가 대비</div>")

# ---- SPCX 일봉 캔들 + 거래량 (인라인 SVG) ----
def chart_svg(h) -> str:
    if not h or not h.get("Close"):
        return '<div style="color:var(--muted);font-size:12.5px;padding:24px 0">차트 데이터 없음</div>'
    O, H, L, Cl, V, D = h["Open"], h["High"], h["Low"], h["Close"], h["Volume"], h["Date"]
    n = len(Cl)
    W, Ht, padL, padR, padT = 760, 300, 50, 14, 14
    priceH, gap, volH = 188, 14, 56
    pBot = padT + priceH; vTop = pBot + gap; vBot = vTop + volH
    plotW = W - padL - padR
    slot = plotW / n
    bw = max(2.0, min(26.0, slot * 0.55))
    pmin, pmax = min(L), max(H)
    if pmax == pmin: pmax = pmin + 1
    rng = pmax - pmin; pmin -= rng * 0.06; pmax += rng * 0.06; rng = pmax - pmin
    vmax = max(V) or 1.0
    yP = lambda p: padT + (pmax - p) / rng * priceH
    xC = lambda i: padL + slot * i + slot / 2
    s = []
    for gp in (pmax, (pmax + pmin) / 2, pmin):
        y = yP(gp)
        s.append(f'<line x1="{padL}" y1="{y:.1f}" x2="{W-padR}" y2="{y:.1f}" stroke="var(--line)" stroke-width="1"/>')
        s.append(f'<text x="{padL-6}" y="{y+3:.1f}" text-anchor="end" font-size="9" fill="var(--muted)">{gp:.0f}</text>')
    s.append(f'<text x="{padL-6}" y="{vTop+8:.1f}" text-anchor="end" font-size="8" fill="var(--muted)">Vol</text>')
    for i in range(n):
        col = "var(--green)" if Cl[i] >= O[i] else "var(--red)"
        x = xC(i)
        s.append(f'<line x1="{x:.1f}" y1="{yP(H[i]):.1f}" x2="{x:.1f}" y2="{yP(L[i]):.1f}" stroke="{col}" stroke-width="1"/>')
        yo, yc = yP(O[i]), yP(Cl[i]); ytop = min(yo, yc); bh = max(1.5, abs(yc - yo))
        s.append(f'<rect x="{x-bw/2:.1f}" y="{ytop:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{col}"/>')
        vh = V[i] / vmax * volH
        s.append(f'<rect x="{x-bw/2:.1f}" y="{vBot-vh:.1f}" width="{bw:.1f}" height="{vh:.1f}" fill="{col}" opacity="0.45"/>')
    for i in sorted(set([0, n // 2, n - 1])):
        s.append(f'<text x="{xC(i):.1f}" y="{vBot+16:.1f}" text-anchor="middle" font-size="9" fill="var(--muted)">{D[i][5:]}</text>')
    note = "" if n >= 5 else f'<text x="{W-padR}" y="{padT+8}" text-anchor="end" font-size="9" fill="var(--muted)">상장 직후 — {n}거래일</text>'
    return f'<svg viewBox="0 0 {W} {Ht}" width="100%" preserveAspectRatio="xMidYMid meet" style="display:block">{"".join(s)}{note}</svg>'

# ---- 국내펀드 구성 표 ----
def domestic_table_html() -> str:
    if not domestic:
        return ""
    rows = ""; tsh = 0; tcu = 0.0
    for m in domestic:
        sh = int(m["shares"]); cu = float(m["cost_usd"]); tsh += sh; tcu += cu
        nm = m.get("short") or m["name"]
        hi = ' class="hi"' if m.get("self") else ''
        rows += (f'<tr{hi}><td style="white-space:nowrap">{nm}</td>'
                 f'<td style="text-align:right;white-space:nowrap">{sh:,}</td>'
                 f'<td style="text-align:right;white-space:nowrap">{usd(cu)}</td>'
                 f'<td style="text-align:right;white-space:nowrap">{usd(sh*px)}</td></tr>')
    rows += (f'<tr style="font-weight:800"><td style="white-space:nowrap">합계</td>'
             f'<td style="text-align:right;white-space:nowrap">{tsh:,}</td>'
             f'<td style="text-align:right;white-space:nowrap">{usd(tcu)}</td>'
             f'<td style="text-align:right;white-space:nowrap">{usd(tsh*px)}</td></tr>')
    return (f'<div style="margin-top:16px;border-top:1px solid var(--line);padding-top:14px">'
            f'<div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:8px">'
            f'국내펀드 구성 (미래에셋 에이펙스펀드) · 배정 기준 · 음영=당사</div>'
            f'<div style="overflow-x:auto"><table><thead><tr><th>주체</th><th>주식수</th><th>약정($)</th><th>평가($)</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>')

# ---- 로켓 발사 스케줄 ----
def launch_html() -> str:
    src = "Launch Library 라이브" if launches is not FALLBACK_LAUNCHES else "예정(폴백)"
    rows = "".join(
        f'<div class="cat"><div class="dt">{l.get("net","")}</div>'
        f'<div class="dd"><b>{l.get("rocket","")}</b>{" · "+l["name"] if l.get("name") else ""}'
        f'{" <small>· "+l["sig"]+"</small>" if l.get("sig") else ""}</div></div>'
        for l in launches)
    return f'<div class="ctitle">로켓 발사 스케줄 <span class="note">{src}</span></div>{rows}'

# ---- 환율 민감도 (환 평가손익, 억원) ----
def fx_sens_html() -> str:
    S0 = fxr; V = valUSD
    Cc = C["shares"] * C["ipoPrice"]              # 취득액 C = 주식수 × 취득단가($135) [엑셀 C6]
    fs = CFG.get("fx_sens", {})
    av = float(fs.get("annual_vol", 0.0858)); H = float(fs.get("horizon_years", 1.0))
    sig = S0 * av * (H ** 0.5)                     # 1σ = S0 × 연율σ × √H [엑셀 C13]
    cols = [("−2σ", -2 * sig), ("−1σ", -sig), ("−100", -100.0), ("−50", -50.0),
            ("현재", 0.0), ("+50", 50.0), ("+100", 100.0), ("+1σ", sig), ("+2σ", 2 * sig)]
    def cell(x):
        v = x / 1e8
        if abs(v) < 0.05:
            return "<td>0.0</td>"
        if v < 0:
            return f'<td style="color:var(--red)">({abs(v):,.1f})</td>'
        return f"<td>{v:,.1f}</td>"
    c1 = lambda d: V * d
    c2 = lambda d: (V - Cc) * d
    c3 = lambda d: (V - Cc) * d + (Cc / 3) * min(d, sig) + (Cc / 3) * min(d, 2 * sig)
    ratio = lambda d: "100%" if d >= 2 * sig else ("67%" if d >= sig else "33%")
    hdr = "".join(f"<th>{lab}</th>" for lab, _ in cols)
    rate = "".join(f"<td>{S0 + d:,.0f}</td>" for _, d in cols)
    row1 = "".join(cell(c1(d)) for _, d in cols)
    row2 = "".join(cell(c2(d)) for _, d in cols)
    row3 = "".join(cell(c3(d)) for _, d in cols)
    rowr = "".join(f"<td>{ratio(d)}</td>" for _, d in cols)
    return (
        '<div class="ctitle">민감도 — 환 평가손익<span class="note">단위 억원 · 현재환율 대비</span></div>'
        f'<div class="senstbl" style="overflow-x:auto"><table>'
        f"<thead><tr><th>구분 / 환율</th>{hdr}</tr></thead><tbody>"
        f'<tr class="rate"><td>환율(원)</td>{rate}</tr>'
        f"<tr><td>case1 (100% 환오픈)</td>{row1}</tr>"
        f"<tr><td>case2 (취득액 헷지·이익분 오픈)</td>{row2}</tr>"
        f'<tr class="c3"><td>case3 (취득액 1/3 분할 헷지)</td>{row3}</tr>'
        f'<tr class="ratio"><td>case3 헷지비율 (vs 취득액)</td>{rowr}</tr>'
        "</tbody></table></div>"
        f'<div style="font-size:10px;color:var(--muted);margin-top:10px;line-height:1.6">'
        f"※ 익스포저 V=주가×주식수(현재 시가), 취득액 C={usd(Cc)}(=주식수×취득단가 ${C['ipoPrice']:.0f}). 취득가 초과 이익(V−C)은 USD 자산이라 case2·case3도 환오픈.<br>"
        f"※ case1=전액 V 오픈 · case2=C 헷지·이익분 오픈 · case3=C를 1/3 즉시 + 1σ·2σ서 1/3씩 추가 헷지(이익 단계 락인), 이익분 항상 오픈 → 하락 시 C/3만 보호.<br>"
        f"※ 기준 S0=현재환율 {S0:,.1f} · 1σ={sig:,.0f}원(=S0×연율σ {av*100:.2f}%×√{H:g}, 10년 변동성). 표값은 현재환율 대비 환손익 변화.</div>"
    )

# ---- 환오픈 포지션 모니터 (펀드 외화 NAV/헷지/오픈) ----
def fx_book_html() -> str:
    def fm(v): return "-" if round(v) == 0 else f"{v:,.0f}"
    def pcf(p): return "-" if not p else f"{round(p)}%"
    static = CFG.get("fx_book", [])
    def mk(r, slf=False):
        return dict(name=r["name"], nav=float(r["nav_m"]), hedge=float(r["hedge_m"]),
                    opn=float(r["open_m"]), pct=float(r.get("hedge_pct", 0)),
                    krw=float(r["krw_eok"]), self=slf)
    usd = [mk(r) for r in static if r.get("group") == "USD"]
    usd.append(dict(name="Space X", nav=valUSD/1e6, hedge=0.0, opn=valUSD/1e6,
                    pct=0.0, krw=valKRW/1e8, self=True))          # 100% 환오픈
    cm = CFG.get("fx_cmtg", {})
    _cm_val = float(cm.get("shares", 0)) * (cmtg.get("price") or 0)   # USD NAV
    cm_nav = _cm_val / 1e6
    usd.append(dict(name="CMTG", nav=cm_nav, hedge=0.0, opn=cm_nav,
                    pct=0.0, krw=_cm_val * fxr / 1e8, self=False))     # 100% 환오픈
    aud = [mk(r) for r in static if r.get("group") == "AUD"]

    def row(r, ccy):
        bg = ' style="background:var(--beige2)"' if r["self"] else ''
        return (f'<tr{bg}><td style="white-space:nowrap">{r["name"]}</td><td>{ccy}</td>'
                f'<td style="text-align:right">{fm(r["nav"])}</td>'
                f'<td style="text-align:right">{fm(r["hedge"])}</td>'
                f'<td style="text-align:right">{fm(r["opn"])}</td>'
                f'<td style="text-align:right">{pcf(r["pct"])}</td>'
                f'<td style="text-align:right">{fm(r["krw"])}</td></tr>')

    su = {k: sum(r[k] for r in usd) for k in ("nav", "hedge", "opn", "krw")}
    su_pct = (su["hedge"] / su["nav"] * 100) if su["nav"] else 0
    total_krw = su["krw"] + sum(r["krw"] for r in aud)

    body = "".join(row(r, "USD") for r in usd)
    body += (f'<tr style="font-weight:800;background:#eceff3"><td>USD 소계</td><td></td>'
             f'<td style="text-align:right">{fm(su["nav"])}</td><td style="text-align:right">{fm(su["hedge"])}</td>'
             f'<td style="text-align:right">{fm(su["opn"])}</td><td style="text-align:right">{pcf(su_pct)}</td>'
             f'<td style="text-align:right">{fm(su["krw"])}</td></tr>')
    body += "".join(row(r, "AUD") for r in aud)
    body += (f'<tr style="font-weight:800;background:var(--beige2)"><td>합계</td><td colspan="5"></td>'
             f'<td style="text-align:right">{fm(total_krw)}</td></tr>')

    cm_sh = int(cm.get("shares", 0))
    return (f'<div class="ctitle">환오픈 포지션 모니터<span class="note">단위: 외화M, 원화(억원)</span></div>'
            f'<div style="overflow-x:auto"><table>'
            f'<thead><tr><th>종목</th><th>통화</th><th>외화NAV</th><th>환헷지</th><th>환오픈</th><th>헷지%</th><th>환오픈(억원)</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>'
            f'<div style="font-size:9.5px;color:var(--muted);margin-top:7px;line-height:1.5">'
            f'SpaceX·CMTG 라이브 시세 기준, 그 외 입력값 · CMTG(티커 CMTG, {cm_sh:,}주)·SpaceX 모두 '
            f'100% 환오픈(미헤지) · 음영=당사 SpaceX</div>')

# ============================================================
# 5. HTML 렌더 (정적 HTML 디자인 그대로)
# ============================================================
CSS = """
<style>
:root{--bg:#eef0f4;--card:#fff;--navy:#16233f;--navy2:#1f3a5f;--orange:#e8743b;
--orange-soft:#fcefe7;--beige2:#f7ede2;--green:#1f9d5b;--red:#d64545;--ink:#1c2330;
--muted:#6b7480;--line:#e7e9ee;--line2:#eef1f5;--shadow:0 1px 3px rgba(20,30,55,.06);}
#root,.block-container{padding:0!important;max-width:1340px!important;}
header[data-testid="stHeader"],#MainMenu,footer{display:none!important;}
.stApp{background:var(--bg);}
.dash *{box-sizing:border-box;margin:0;padding:0;font-family:"Segoe UI","Malgun Gothic",sans-serif;}
.dash{color:var(--ink);padding:22px 20px 50px;}
.dash .pos{color:var(--green);}.dash .neg{color:var(--red);}
.dash a{text-decoration:none;color:inherit;}
.top{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:14px;
border-bottom:3px solid var(--navy);padding-bottom:16px;margin-bottom:20px;}
.h-title{font-size:29px;font-weight:800;letter-spacing:-.5px;}.h-title .tk{color:var(--orange);}
.h-sub{font-size:13px;color:var(--muted);margin-top:5px;}
.h-right{text-align:right;font-size:12px;color:var(--muted);}.h-right b{color:var(--ink);}
.badge{display:inline-block;background:var(--orange-soft);color:var(--orange);font-weight:700;
font-size:11.5px;padding:5px 11px;border-radius:7px;margin-top:7px;}
.hero{display:grid;grid-template-columns:1.15fr 1fr 1fr .85fr;gap:13px;margin-bottom:16px;}
.hcard{background:var(--card);border-radius:13px;padding:17px 19px;box-shadow:var(--shadow);}
.hcard.dark{background:linear-gradient(160deg,#16233f,#22375c);color:#fff;}
.hl{font-size:12px;color:var(--muted);font-weight:600;}.hcard.dark .hl{color:#aebbd2;}
.hv{font-size:29px;font-weight:800;margin-top:6px;letter-spacing:-.5px;}.hv.sm{font-size:24px;}
.hsub{font-size:12px;margin-top:5px;color:var(--muted);}.hcard.dark .hsub{color:#9fb0cc;}
.grid2{display:grid;grid-template-columns:1.45fr 1fr;gap:15px;align-items:start;}
.grid-half{display:grid;grid-template-columns:1fr 1fr;gap:15px;align-items:start;margin-top:15px;}
.col{display:flex;flex-direction:column;gap:15px;}
.card{background:var(--card);border-radius:13px;padding:19px 21px;box-shadow:var(--shadow);}
.ctitle{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;margin-bottom:15px;}
.ctitle::before{content:"";width:9px;height:9px;border-radius:50%;background:var(--orange);}
.ctitle .note{margin-left:auto;font-size:11px;font-weight:600;color:var(--muted);}
.kv{display:flex;justify-content:space-between;align-items:baseline;padding:10px 0;
border-bottom:1px solid var(--line2);font-size:13.5px;}.kv:last-child{border-bottom:none;}
.kv .k{color:var(--muted);}.kv .v{font-weight:700;text-align:right;}
.gauge-wrap{margin-top:13px;}
.gauge-lab{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:6px;}
.gauge{position:relative;height:9px;border-radius:6px;background:linear-gradient(90deg,#e6f4ec,#fbf1e8 55%,#fae0db);}
.gmark{position:absolute;top:-3px;width:3px;height:15px;border-radius:2px;transform:translateX(-50%);}
.gfill{position:absolute;top:0;left:0;height:100%;background:rgba(31,58,95,.20);border-radius:6px 0 0 6px;}
.gtrig{position:absolute;top:-4px;width:3px;height:17px;background:var(--red);transform:translateX(-50%);border-radius:2px;}
.pnl{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0 2px;}
.pnl-i{background:var(--beige2);border-radius:9px;padding:8px 6px;text-align:center;}
.pnl-i span{display:block;font-size:10.5px;color:var(--muted);font-weight:700;}
.pnl-i b{display:block;font-size:13.5px;font-weight:800;margin-top:3px;}
.pnl-i i{display:block;font-style:normal;font-size:9.5px;font-weight:700;margin-top:1px;}
.pnl-i u{display:block;text-decoration:none;font-size:8.5px;color:var(--muted);margin-top:3px;}
.senstbl table{font-size:11.5px;}
.senstbl th,.senstbl td{padding:6px 9px;white-space:nowrap;text-align:right;}
.senstbl th:first-child,.senstbl td:first-child{text-align:left;}
.senstbl tr.rate td{background:var(--beige2);font-weight:700;}
.senstbl tr.c3 td{font-weight:800;color:var(--navy2);}
.senstbl tr.c3 td:first-child{color:var(--red);}
.senstbl tr.ratio td{color:var(--muted);font-style:italic;font-size:10.5px;}
.gcap{font-size:11.5px;color:var(--muted);margin-top:9px;line-height:1.5;}.gcap b{color:var(--ink);}
.expo-track{height:11px;background:var(--line);border-radius:7px;overflow:hidden;margin-top:6px;}
.expo-fill{height:100%;background:linear-gradient(90deg,var(--orange),#f0925f);border-radius:7px;}
table{width:100%;border-collapse:collapse;font-size:12.5px;}
th{background:var(--navy);color:#fff;font-weight:700;font-size:11.5px;padding:9px 10px;text-align:left;}
th:last-child,td:last-child{text-align:right;}
td{padding:8px 10px;border-bottom:1px solid var(--line2);}
tr.hi td{background:var(--beige2);}tr.hi td:first-child{font-weight:800;color:var(--navy2);}
.stage{font-weight:700;}.stage small{display:block;font-weight:500;color:var(--muted);font-size:10.5px;}
.pct{font-weight:800;}
.mini-grid,.idx-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px;}
.mini,.idx{border:1px solid var(--line);border-radius:11px;padding:12px 13px;}
.mini .nm,.idx .nm{font-size:11.5px;color:var(--muted);font-weight:700;}.mini .nm span{color:var(--ink);}
.mini .pr{font-size:19px;font-weight:800;margin-top:6px;}.mini .ch{font-size:11.5px;font-weight:700;margin-top:3px;}
.idx .vv{font-size:20px;font-weight:800;margin-top:6px;}.idx .ss{font-size:11px;color:var(--muted);margin-top:3px;}
.news a{display:block;padding:10px 0;border-bottom:1px solid var(--line2);}.news a:last-child{border-bottom:none;}
.news .ht{font-size:13px;font-weight:700;line-height:1.4;}.news a:hover .ht{color:var(--orange);}
.news .hm{font-size:11px;color:var(--muted);margin-top:4px;}
.ph{border:1.5px dashed #cdd4df;background:#fafbfc;}.ph .ctitle::before{background:#b9c1cd;}
.ph-note{font-size:12px;color:var(--muted);background:#fff;border:1px solid var(--line);
border-radius:9px;padding:10px 13px;margin-bottom:13px;}.ph .kv .v{color:#aeb6c2;}
.peer{display:flex;justify-content:space-between;align-items:center;padding:11px 0;border-bottom:1px solid var(--line2);}
.peer:last-child{border-bottom:none;}.peer .pl{font-weight:700;font-size:13px;}
.peer .pl small{display:block;color:var(--muted);font-weight:500;font-size:11px;margin-top:2px;}
.peer .pp{font-weight:800;font-size:14.5px;text-align:right;}.peer .pc{font-size:11px;font-weight:700;text-align:right;}
.cat{display:flex;gap:11px;padding:10px 0;border-bottom:1px solid var(--line2);}.cat:last-child{border-bottom:none;}
.cat .dt{flex:0 0 72px;font-size:11px;font-weight:800;color:var(--navy2);}
.cat.key .dt{color:var(--orange);}.cat .dd{font-size:12.5px;line-height:1.45;}.cat .dd small{color:var(--muted);}
.foot{margin-top:24px;font-size:11px;color:var(--muted);line-height:1.7;border-top:1px solid var(--line);padding-top:15px;}
.foot b{color:var(--ink);}
@media(max-width:920px){.hero,.grid2,.grid-half,.mini-grid,.idx-grid{grid-template-columns:1fr;}}
</style>
"""

def render() -> str:
    hero = f"""
    <div class="hcard dark"><div class="hl">SPCX 현재가</div><div class="hv">{usd2(px)}</div>
      <div class="hsub">공모가 {usd2(C['ipoPrice'])} 대비 <b class="pos">{pct(upside)}</b> · 전일 <b class="{sgn(dayChg)}">{pct(dayChg)}</b></div></div>
    <div class="hcard"><div class="hl">평가손익 (USD)</div><div class="hv {sgn(plUSD)}">{('+' if plUSD>=0 else '')+usd(plUSD)}</div>
      <div class="hsub">평가금액 {usd(valUSD)}</div></div>
    <div class="hcard"><div class="hl">평가손익 (KRW)</div><div class="hv sm {sgn(plKRW)}">{('+' if plKRW>=0 else '')+krw(plKRW)}</div>
      <div class="hsub {sgn(fxPL)}" style="font-weight:700">환평가손익 {('+' if fxPL>=0 else '−')}{krw(abs(fxPL))}</div>
      <div class="hsub">평가금액 {krw(valKRW)}</div></div>
    <div class="hcard"><div class="hl">수익률</div><div class="hv {sgn(retUSD)}">{pct(retUSD)}</div>
      <div class="hsub">USD 기준 · KRW {pct(retKRW)}</div></div>"""

    position = f"""<div class="ctitle">당사 포지션 평가</div>
      <div class="kv"><span class="k">보유 주식수</span><span class="v">{C['shares']:,} 주</span></div>
      <div class="kv"><span class="k">매입원가 (제반비용 포함)</span><span class="v">{usd(C['costUSD'])} · {krw(C['costKRW'])}</span></div>
      <div class="kv"><span class="k">현재 평가금액</span><span class="v">{usd(valUSD)} · {krw(valKRW)}</span></div>
      <div class="kv"><span class="k">평가손익 (누적·BEP ${C['bep']:.2f} 기준)</span><span class="v {sgn(plUSD)}">+{usd(plUSD)} · +{krw(plKRW)}</span></div>
      {pnl_grid()}
      <div class="kv"><span class="k">BEP 주가 / 현재가</span><span class="v">{usd2(C['bep'])} → {usd2(px)}</span></div>
      <div class="gauge-wrap">
        <div class="gauge-lab"><span>BEP {usd2(C['bep'])}</span><span>애널 목표(고) {usd2(ANALYST['high'])}</span></div>
        <div class="gauge">
          <div class="gfill" style="width:{gpos(px):.1f}%"></div>
          <div class="gtrig" style="left:{gpos(C['trigger']):.1f}%"></div>
          <div class="gmark" style="left:{gpos(px):.1f}%;background:var(--navy)"></div>
        </div>
        <div class="gcap"><b style="color:var(--ink)">조건부 트리거</b>: 첫 실적발표 이전 <b style="color:var(--ink)">10영업일 중 5영업일 이상 종가 {usd2(C['trigger'])} 상회</b> 시 +10% 추가 해제<br>
          현재가 <b>{usd2(px)}</b> · 트리거 <b style="color:var(--orange)">{'상회 ('+pct(aboveTrig)+')' if aboveTrig>=0 else '까지 '+pct(-aboveTrig)}</b> · 최근 {trig_window}영업일 중 <b style="color:var(--orange)">{trig_met}일</b> 충족 (목표 5일)</div>
      </div>
      <div class="kv" style="margin-top:15px;border-top:1px solid var(--line);padding-top:13px">
        <span class="k">익스포저 / 자기자본 비중<br><small style="font-size:10.5px">자기자본 {eok(C['equityKRW'])} ('25.12)</small></span>
        <span class="v" style="font-size:18px">{expoRatio:.1f}%</span></div>
      <div class="expo-track"><div class="expo-fill" style="width:{min(100,expoRatio):.1f}%"></div></div>"""

    lockrows = "".join(
        f'<tr class="{"hi" if hi else ""}"><td class="stage">{st_}<small>{sub}</small></td>'
        f'<td>{desc}</td><td class="pct">{p}%</td></tr>'
        for st_, sub, desc, p, hi in LOCKUP)
    lockup = f"""<div class="ctitle">Lock-up / Release · 핵심 촉매<span class="note">발행주식 누적 비중</span></div>
      <table><thead><tr><th>단계</th><th>내용</th><th>누적</th></tr></thead><tbody>{lockrows}</tbody></table>
      <div style="margin-top:12px;font-size:11.5px;color:var(--muted);line-height:1.65">
        <b style="color:var(--ink)">핵심 촉매</b> · 2Q 실적(~8월)→a 해제 · 3Q 실적(~11월)→d 해제(단일 최대) · 조건부 트리거 {usd2(C['trigger'])} · Musk 366일 해제(2027-06-12)</div>"""

    etf_cards = "".join(
        f'<div class="mini"><div class="nm"><span>{tk}</span> · {nm}</div>'
        f'<div class="pr">{usd2(d["price"]) if d["price"] else "—"}</div>'
        f'<div class="ch {sgn(d["day"]) if d["day"] is not None else "pos"}">'
        f'{pct(d["day"]) if d["day"] is not None else "&nbsp;"} '
        f'<span style="color:var(--muted);font-weight:600">{pct(d["ytd"])+" YTD" if d["ytd"] is not None else ""}</span></div></div>'
        for tk, nm, d in etf_q)
    etf = f'<div class="ctitle">관련 ETF (우주·위성 테마)</div><div class="mini-grid">{etf_cards}</div>'

    market = f"""<div class="ctitle">시장지수 · 환율</div><div class="idx-grid">
      <div class="idx"><div class="nm">S&P 500</div><div class="vv">{sp['price']:,.0f}</div><div class="ss {sgn(sp['day']) if sp['day'] is not None else ''}">{pct(sp['day']) if sp['day'] is not None else ''}</div></div>
      <div class="idx"><div class="nm">나스닥 종합</div><div class="vv">{nq['price']:,.0f}</div><div class="ss {sgn(nq['day']) if nq['day'] is not None else ''}">{pct(nq['day']) if nq['day'] is not None else ''}</div></div>
      <div class="idx"><div class="nm">USD/KRW</div><div class="vv">{fxr:,.2f}</div><div class="ss">매입 {C['buyFX']:,.2f} 대비 {pct(fxChg)}</div></div>
      <div class="idx"><div class="nm">SpaceX 시총</div><div class="vv">{tcap(mktcap)}</div><div class="ss">공모가 ${C['ipoPrice']:.0f} → {pct(upside)}</div></div></div>"""

    news_html = "".join(
        f'<a href="{n["u"]}" target="_blank" rel="noopener"><div class="ht">{n["t"]}</div>'
        f'<div class="hm">{n.get("s","")}</div></a>' for n in news[:5])
    news_card = f'<div class="ctitle">뉴스 플로우 <span class="note">SPCX 라이브</span></div>{news_html}'

    fx_card = fx_book_html()

    peer_first = f"""<div class="peer"><div class="pl">SPCX <small>SpaceX · 본 포지션</small></div>
      <div><div class="pp">{usd2(px)}</div><div class="pc pos">{pct(upside)} vs 공모</div></div></div>"""
    peer_rows = "".join(
        f'<div class="peer"><div class="pl">{tk} <small>{nm} · {note}</small></div>'
        f'<div><div class="pp">{usd2(d["price"]) if d["price"] else "—"}</div>'
        f'<div class="pc {sgn(d["ytd"]) if d["ytd"] is not None else ""}">{pct(d["ytd"])+" YTD" if d["ytd"] is not None else ""}</div></div></div>'
        for tk, nm, note, d in peer_q)
    peer = f'<div class="ctitle">피어 비교 (상장 우주株)</div>{peer_first}{peer_rows}'

    cat_rows = "".join(
        f'<div class="cat {"key" if key else ""}"><div class="dt">{"★ " if key else ""}{d}</div>'
        f'<div class="dd">{t}{" · <small>"+sub+"</small>" if sub else ""}</div></div>'
        for d, key, t, sub in CATALYSTS)
    catalyst = f'<div class="ctitle">촉매 캘린더<span class="note">★ = 락업/실적 핵심</span></div>{cat_rows}'

    foot = (f'※ 본 대시보드는 공개 시세를 yfinance로 받은 <b>스냅샷</b>이며 실시간(틱)이 아닙니다(5분 캐시·자동갱신).'
            f'<b>참고용</b>이며 투자자문이 아닙니다. 평가손익 = 보유 {C["shares"]:,}주 × 현재가, '
            f'매입원가는 제반비용 포함 약정액(575,111주 × BEP ${C["bep"]:.2f}). 환율 가정 매입 {C["buyFX"]:,.2f} / 자기자본 {eok(C["equityKRW"])} (\'25.12 기준). '
            f'기준 {asof}.')

    return f"""{CSS}
    <div class="dash">
      <div class="top">
        <div><div class="h-title">SpaceX <span class="tk">(SPCX)</span> 익스포저 모니터</div>
          <div class="h-sub">미래에셋생명 PI운용팀</div></div>
        <div class="h-right">기준: <b>{asof}</b><br><span class="badge">접속 시 + 5분마다 자동 갱신 (yfinance)</span></div>
      </div>
      <div class="hero">{hero}</div>
      <div class="grid2">
        <div class="col"><div class="card">{position}{domestic_table_html()}</div><div class="card">{lockup}</div></div>
        <div class="col">
          <div class="card"><div class="ctitle">SPCX 주가 추이 <span class="note">일봉·거래량</span></div>{chart_svg(hist)}</div>
          <div class="card">{etf}</div><div class="card">{market}</div><div class="card news">{news_card}</div></div>
      </div>
      <div style="margin-top:15px"><div class="card">{fx_card}</div></div>
      <div style="margin-top:15px"><div class="card">{fx_sens_html()}</div></div>
      <div class="grid-half"><div class="card">{peer}</div><div class="card">{launch_html()}</div></div>
      <div class="foot">{foot}</div>
    </div>"""

# 각 줄 앞 들여쓰기를 제거해야 함 — Markdown이 들여쓴 HTML을 코드블록으로 처리하는 것 방지
_html = "\n".join(line.lstrip() for line in render().splitlines())
st.markdown(_html, unsafe_allow_html=True)

# 수동 새로고침 버튼 (캐시 비우고 재fetch)
if st.button("🔄 지금 새로고침"):
    st.cache_data.clear()
    st.rerun()
