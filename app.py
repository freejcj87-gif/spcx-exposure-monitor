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
import streamlit as st
import yfinance as yf

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

# ============================================================
# 1. 포지션 고정값 (CONSTANTS) — 갱신 시 여기만
# ============================================================
def _secret(key, default):
    """민감 포지션 값은 Secrets에서 읽음 (공개 repo에 수치를 남기지 않기 위함)."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

# 민감값(보유주수·매입원가·BEP·환율·자기자본)은 Secrets, 공개정보(공모가·트리거·발행주식)는 소스
CONSTANTS = dict(
    shares=int(_secret("POS_SHARES", 0)),
    costUSD=float(_secret("POS_COST_USD", 0)),
    costKRW=float(_secret("POS_COST_KRW", 0)),
    bep=float(_secret("POS_BEP", 0)),
    buyFX=float(_secret("POS_BUY_FX", 1)),
    ipoPrice=135.00,
    trigger=175.50,
    equityKRW=float(_secret("POS_EQUITY_KRW", 1)),
    sharesOut=13_164_000_000,       # SpaceX 총 발행주식 (락업 f 100% 기준, 공개정보)
)

# 포지션 Secrets 미설정 시 친절 안내 후 중단 (0 나눗셈/오표시 방지)
if CONSTANTS["shares"] <= 0 or CONSTANTS["costUSD"] <= 0:
    st.error("⚠ 포지션 Secrets가 설정되지 않았습니다.\n\n"
             "App settings → Secrets 에 POS_SHARES / POS_COST_USD / POS_COST_KRW / "
             "POS_BEP / POS_BUY_FX / POS_EQUITY_KRW 값을 입력하세요. "
             "(로컬은 .streamlit/secrets.toml)")
    st.stop()

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

ANALYST = dict(avg=164, high=227, low=63, rating="Buy")  # 목표가(최근 웹 기준, 수동 갱신)

# ============================================================
# 2. 라이브 데이터 (yfinance) — 15분 캐시
# ============================================================
@st.cache_data(ttl=900, show_spinner=False)
def fetch_quote(ticker: str) -> dict:
    """price / prevClose / dayChg% / ytd% 반환. 실패 시 None 값."""
    out = dict(price=None, prev=None, day=None, ytd=None)
    try:
        t = yf.Ticker(ticker)
        fi = getattr(t, "fast_info", {}) or {}
        price = fi.get("last_price") or fi.get("lastPrice")
        prev = fi.get("previous_close") or fi.get("previousClose")
        if price is None:
            hist = t.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                if len(hist) > 1:
                    prev = float(hist["Close"].iloc[-2])
        out["price"] = float(price) if price else None
        out["prev"] = float(prev) if prev else None
        if out["price"] and out["prev"]:
            out["day"] = (out["price"] - out["prev"]) / out["prev"] * 100
        ytd = t.history(period="ytd")
        if not ytd.empty and out["price"]:
            base = float(ytd["Close"].iloc[0])
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
    "SPCX": dict(price=192.50, prev=160.95, day=19.6, ytd=None),
    "KRW=X": dict(price=1513.65, prev=1520.02, day=None, ytd=None),
    "^GSPC": dict(price=7555.26, prev=7431.46, day=1.67, ytd=None),
    "^IXIC": dict(price=26683.94, prev=25888.84, day=3.07, ytd=None),
    "ARKX": dict(price=33.78, prev=34.45, day=-1.9, ytd=11.0),
    "UFO": dict(price=52.92, prev=None, day=None, ytd=31.0),
    "ROKT": dict(price=120.01, prev=None, day=None, ytd=58.0),
    "RKLB": dict(price=102.39, prev=None, day=None, ytd=None),
    "ASTS": dict(price=82.41, prev=None, day=None, ytd=None),
    "LUNR": dict(price=26.62, prev=None, day=None, ytd=None),
}
FALLBACK_NEWS = [
    dict(t="SpaceX, 첫 정규거래일 +20% 급등 — SPCX $192.50 마감, 시총 ≈$2.5조",
         s="CNBC", u="https://www.cnbc.com/2026/06/15/spacex-stock-record-ipo-debut.html"),
    dict(t="왜 오르나 — 낮은 유통물량·목표가 상향 기대가 SPCX 랠리 견인",
         s="IndMoney", u="https://www.indmoney.com/blog/us-stocks/why-is-spacex-spcx-stock-rising-today"),
    dict(t="Lock-up 구조: 2Q 실적 후 ~20% 해제, 조건부 +10%, Musk는 366일",
         s="TradingView", u="https://www.tradingview.com/symbols/NASDAQ-SPCX/"),
]

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

px = spcx["price"]; fxr = fx["price"]
valUSD = C["shares"] * px
plUSD = valUSD - C["costUSD"]; retUSD = plUSD / C["costUSD"] * 100
valKRW = valUSD * fxr
plKRW = valKRW - C["costKRW"]; retKRW = plKRW / C["costKRW"] * 100
upside = (px - C["ipoPrice"]) / C["ipoPrice"] * 100
dayChg = spcx["day"] if spcx["day"] is not None else (px - spcx["prev"]) / spcx["prev"] * 100 if spcx["prev"] else 0
aboveTrig = (px - C["trigger"]) / C["trigger"] * 100
expoRatio = valKRW / C["equityKRW"] * 100
fxChg = (fxr - C["buyFX"]) / C["buyFX"] * 100
mktcap = px * C["sharesOut"]
gMin, gMax = C["bep"], ANALYST["high"]
def gpos(p): return max(0.0, min(100.0, (p - gMin) / (gMax - gMin) * 100))

stale = spcx.get("_stale") or fx.get("_stale")
now = dt.datetime.now()
asof = now.strftime("%Y-%m-%d %H:%M KST") + (" · ⚠ 라이브 실패, 폴백값" if stale else " · 라이브")

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
      <div class="hsub">평가금액 {krw(valKRW)}</div></div>
    <div class="hcard"><div class="hl">수익률</div><div class="hv {sgn(retUSD)}">{pct(retUSD)}</div>
      <div class="hsub">USD 기준 · KRW {pct(retKRW)}</div></div>"""

    position = f"""<div class="ctitle">당사 포지션 평가</div>
      <div class="kv"><span class="k">보유 주식수</span><span class="v">{C['shares']:,} 주</span></div>
      <div class="kv"><span class="k">매입원가 (제반비용 포함)</span><span class="v">{usd(C['costUSD'])} · {krw(C['costKRW'])}</span></div>
      <div class="kv"><span class="k">현재 평가금액</span><span class="v">{usd(valUSD)} · {krw(valKRW)}</span></div>
      <div class="kv"><span class="k">평가손익</span><span class="v {sgn(plUSD)}">+{usd(plUSD)} · +{krw(plKRW)}</span></div>
      <div class="kv"><span class="k">BEP 주가 / 현재가</span><span class="v">{usd2(C['bep'])} → {usd2(px)}</span></div>
      <div class="gauge-wrap">
        <div class="gauge-lab"><span>BEP {usd2(C['bep'])}</span><span>애널 목표(고) {usd2(ANALYST['high'])}</span></div>
        <div class="gauge">
          <div class="gmark" style="left:{gpos(C['bep']):.1f}%;background:#9aa3b0"></div>
          <div class="gmark" style="left:{gpos(C['trigger']):.1f}%;background:var(--red)"></div>
          <div class="gmark" style="left:{gpos(px):.1f}%;background:var(--navy)"></div>
        </div>
        <div class="gcap">현재가 <b>{usd2(px)}</b> · 조건부 트리거 {usd2(C['trigger'])} <b style="color:var(--orange)">{'상회 ('+pct(aboveTrig)+')' if aboveTrig>=0 else '까지 '+pct(-aboveTrig)}</b> · 애널 평균 {usd2(ANALYST['avg'])}</div>
      </div>
      <div class="kv" style="margin-top:15px;border-top:1px solid var(--line);padding-top:13px">
        <span class="k">익스포저 / 자기자본 비중<br><small style="font-size:10.5px">자기자본 {eok(C['equityKRW'])} 가정</small></span>
        <span class="v" style="font-size:18px">{expoRatio:.1f}%</span></div>
      <div class="expo-track"><div class="expo-fill" style="width:{min(100,expoRatio):.1f}%"></div></div>"""

    lockrows = "".join(
        f'<tr class="{"hi" if hi else ""}"><td class="stage">{st_}<small>{sub}</small></td>'
        f'<td>{desc}</td><td class="pct">{p}%</td></tr>'
        for st_, sub, desc, p, hi in LOCKUP)
    lockup = f"""<div class="ctitle">Lock-up / Release 일정<span class="note">발행주식 누적 비중</span></div>
      <table><thead><tr><th>단계</th><th>내용</th><th>누적</th></tr></thead><tbody>{lockrows}</tbody></table>"""

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

    fx_card = f"""<div class="ctitle">환오픈 포지션 모니터<span class="note">데이터 입력 예정</span></div>
      <div class="ph-note">📌 당사 환오픈(USD 미헤지) 포지션 데이터 입력 예정 구역입니다. 입력 시 자동 산출됩니다 —
      참고로 본 SpaceX 포지션 단독 기준 매입환율 {C['buyFX']:,.2f} → 현재 {fxr:,.2f}
      (<b class="{sgn(fxChg)}">{pct(fxChg)}</b>), USD 수익률 {pct(retUSD)} 대비 KRW 수익률 {pct(retKRW)}로
      환에서 약 {retUSD-retKRW:.1f}%p 차이가 발생했습니다.</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 28px">
      {''.join(f'<div class="kv"><span class="k">{k}</span><span class="v">—</span></div>' for k in
        ["환노출 금액 (USD)","헤지율","매입환율 → 현재환율","환손익 (KRW)","환율 민감도 (±10원당)","수익률 분해 (주가/환)"])}</div>"""

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

    foot = (f'※ 본 대시보드는 공개 시세를 yfinance로 받은 <b>스냅샷</b>이며 실시간(틱)이 아닙니다(15분 캐시). '
            f'<b>참고용</b>이며 투자자문이 아닙니다. 평가손익 = 보유 {C["shares"]:,}주 × 현재가, '
            f'매입원가는 제반비용 포함 약정액. 환율 가정 매입 {C["buyFX"]:,.2f} / 자기자본 {eok(C["equityKRW"])} 가정. '
            f'기준 {asof}.')

    return f"""{CSS}
    <div class="dash">
      <div class="top">
        <div><div class="h-title">SpaceX <span class="tk">(SPCX)</span> 익스포저 모니터</div>
          <div class="h-sub">미래에셋생명 PI운용팀 · 미래에셋 에이펙스펀드 경유 비상장(상장전환)주 포지션</div></div>
        <div class="h-right">기준: <b>{asof}</b><br><span class="badge">접속 시 자동 갱신 (yfinance 라이브)</span></div>
      </div>
      <div class="hero">{hero}</div>
      <div class="grid2">
        <div class="col"><div class="card">{position}</div><div class="card">{lockup}</div></div>
        <div class="col"><div class="card">{etf}</div><div class="card">{market}</div><div class="card news">{news_card}</div></div>
      </div>
      <div style="margin-top:15px"><div class="card ph">{fx_card}</div></div>
      <div class="grid-half"><div class="card">{peer}</div><div class="card">{catalyst}</div></div>
      <div class="foot">{foot}</div>
    </div>"""

st.markdown(render(), unsafe_allow_html=True)

# 수동 새로고침 버튼 (캐시 비우고 재fetch)
if st.button("🔄 지금 새로고침"):
    st.cache_data.clear()
    st.rerun()
