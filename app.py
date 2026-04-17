from __future__ import annotations

import os
import random
import socket
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Deque, Dict, List, Optional

from flask import Flask, jsonify, render_template_string, request

# Optional real data support
# pip install yfinance
try:
    import yfinance as yf  # type: ignore
except Exception:
    yf = None

app = Flask(__name__)

# =========================
# 基本設定
# =========================
PORT = int(os.environ.get("PORT", 5000))
REFRESH_SECONDS = 3
DEFAULT_SYMBOLS = [
    "2330.TW",
    "0050.TW",
    "00878.TW",
    "^TWII",
    "BTC-USD",
]

FUTURES_SYMBOLS = [
    "^TWII",  # 台股加權，先當台指觀察基準
    "TXF_PROXY",  # 大台代理顯示
    "MTX_PROXY",  # 小台代理顯示
    "TMF_PROXY",  # 微台代理顯示
]

DISPLAY_NAME_MAP = {
    "2330.TW": "台積電",
    "0050.TW": "元大台灣50",
    "00878.TW": "國泰永續高股息",
    "^TWII": "台股加權指數",
    "BTC-USD": "比特幣",
    "TXF_PROXY": "台指近月（示意）",
    "MTX_PROXY": "小台近月（示意）",
    "TMF_PROXY": "微台近月（示意）",
}

history_map: Dict[str, Deque[float]] = {}
mock_state: Dict[str, Dict[str, float]] = {}


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    updated_at: str
    source: str
    history: List[float]
    category: str = "watchlist"


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def push_history(symbol: str, price: float, max_len: int = 24) -> List[float]:
    if symbol not in history_map:
        history_map[symbol] = deque(maxlen=max_len)
    history_map[symbol].append(float(price))
    return [round(x, 2) for x in history_map[symbol]]


def init_mock(symbol: str) -> None:
    if symbol in mock_state:
        return

    base_map = {
        "2330.TW": 860.0,
        "0050.TW": 180.0,
        "00878.TW": 22.0,
        "^TWII": 21000.0,
        "BTC-USD": 85000.0,
        "TXF_PROXY": 21020.0,
        "MTX_PROXY": 21018.0,
        "TMF_PROXY": 21017.0,
    }
    base = base_map.get(symbol, random.uniform(50, 500))
    mock_state[symbol] = {"prev_close": base, "price": base}


def get_mock_quote(symbol: str, category: str = "watchlist") -> Quote:
    init_mock(symbol)
    prev_close = mock_state[symbol]["prev_close"]
    current = mock_state[symbol]["price"]
    drift = random.uniform(-0.006, 0.006)
    new_price = max(0.01, current * (1 + drift))
    mock_state[symbol]["price"] = new_price
    change = new_price - prev_close
    change_percent = (change / prev_close) * 100 if prev_close else 0.0
    history = push_history(symbol, new_price)

    return Quote(
        symbol=symbol,
        name=DISPLAY_NAME_MAP.get(symbol, symbol),
        price=round(new_price, 2),
        change=round(change, 2),
        change_percent=round(change_percent, 2),
        updated_at=now_str(),
        source="mock",
        history=history,
        category=category,
    )


def get_yfinance_quote(symbol: str, category: str = "watchlist") -> Optional[Quote]:
    if yf is None:
        return None

    if symbol in {"TXF_PROXY", "MTX_PROXY", "TMF_PROXY"}:
        return None

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1m")
        if hist is None or hist.empty:
            return None

        close_series = hist["Close"].dropna()
        if close_series.empty:
            return None

        latest_price = float(close_series.iloc[-1])

        try:
            prev_close = float(ticker.fast_info.get("previous_close") or latest_price)
        except Exception:
            prev_close = latest_price

        change = latest_price - prev_close
        change_percent = (change / prev_close) * 100 if prev_close else 0.0

        name = DISPLAY_NAME_MAP.get(symbol, symbol)
        try:
            meta = ticker.info
            name = meta.get("shortName") or meta.get("longName") or name
        except Exception:
            pass

        history = push_history(symbol, latest_price)

        return Quote(
            symbol=symbol,
            name=name,
            price=round(latest_price, 2),
            change=round(change, 2),
            change_percent=round(change_percent, 2),
            updated_at=now_str(),
            source="yfinance",
            history=history,
            category=category,
        )
    except Exception:
        return None


def make_futures_proxy_quotes(base_quote: Quote) -> List[Quote]:
    base_price = base_quote.price
    base_change = base_quote.change
    base_pct = base_quote.change_percent
    t = time.time()
    wobble1 = round(((t % 7) - 3) * 0.8, 2)
    wobble2 = round(((t % 5) - 2) * 0.5, 2)
    wobble3 = round(((t % 3) - 1) * 0.3, 2)

    mapping = [
        (
            "TXF_PROXY",
            "台指近月（示意）",
            base_price + 18 + wobble1,
            base_change + wobble1,
        ),
        (
            "MTX_PROXY",
            "小台近月（示意）",
            base_price + 16 + wobble2,
            base_change + wobble2,
        ),
        (
            "TMF_PROXY",
            "微台近月（示意）",
            base_price + 15 + wobble3,
            base_change + wobble3,
        ),
    ]

    results: List[Quote] = []
    for symbol, name, price, change in mapping:
        pct = (change / (price - change) * 100) if (price - change) else base_pct
        history = push_history(symbol, price)
        results.append(
            Quote(
                symbol=symbol,
                name=name,
                price=round(price, 2),
                change=round(change, 2),
                change_percent=round(pct, 2),
                updated_at=now_str(),
                source=f"{base_quote.source}-proxy",
                history=history,
                category="futures",
            )
        )
    return results


def get_quote(symbol: str, category: str = "watchlist") -> Quote:
    real_quote = get_yfinance_quote(symbol, category=category)
    if real_quote is not None:
        return real_quote
    return get_mock_quote(symbol, category=category)


@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        default_symbols=DEFAULT_SYMBOLS,
        refresh_seconds=REFRESH_SECONDS,
        local_ip=get_local_ip(),
        port=PORT,
    )


@app.route("/api/quotes")
def api_quotes():
    raw_symbols = request.args.get("symbols", "")
    symbols = [
        s.strip() for s in raw_symbols.split(",") if s.strip()
    ] or DEFAULT_SYMBOLS

    watchlist: List[Dict] = []
    for symbol in symbols:
        quote = get_quote(symbol, category="watchlist")
        watchlist.append(asdict(quote))

    base_index = get_quote("^TWII", category="futures")
    futures_quotes = [asdict(base_index)] + [
        asdict(q) for q in make_futures_proxy_quotes(base_index)
    ]

    return jsonify(
        {
            "ok": True,
            "refresh_seconds": REFRESH_SECONDS,
            "watchlist": watchlist,
            "futures": futures_quotes,
            "server_time": now_str(),
            "using_real_data": yf is not None,
        }
    )


HTML_TEMPLATE = r"""
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>即時看盤面板 v2</title>
  <style>
    :root {
      --bg: #07111f;
      --panel: rgba(16, 24, 39, 0.96);
      --panel-2: #152236;
      --text: #e5edf7;
      --muted: #8ea1b8;
      --up: #ff4d57;
      --up-bg: rgba(255, 77, 87, 0.14);
      --down: #34d399;
      --down-bg: rgba(52, 211, 153, 0.14);
      --flat: #fbbf24;
      --flat-bg: rgba(251, 191, 36, 0.12);
      --border: rgba(255,255,255,0.08);
      --accent: #3b82f6;
      --shadow: 0 14px 34px rgba(0,0,0,.35);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at top, #10213c 0%, #07111f 42%, #050c16 100%);
      color: var(--text);
      font-family: Arial, "Noto Sans TC", sans-serif;
    }
    .wrap {
      width: min(1180px, calc(100% - 20px));
      margin: 14px auto 28px;
    }
    .hero, .section, .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
    }
    .hero {
      padding: 18px;
      margin-bottom: 14px;
    }
    .hero h1 {
      margin: 0 0 8px;
      font-size: 24px;
    }
    .muted {
      color: var(--muted);
      line-height: 1.6;
      font-size: 13px;
    }
    .control-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      margin-top: 14px;
    }
    input {
      width: 100%;
      border: 1px solid var(--border);
      background: #091321;
      color: var(--text);
      border-radius: 14px;
      padding: 13px 14px;
      font-size: 14px;
      outline: none;
    }
    button {
      border: 0;
      border-radius: 14px;
      padding: 13px 18px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 700;
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      color: white;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-top: 14px;
    }
    .mini {
      background: var(--panel-2);
      border-radius: 18px;
      padding: 13px;
      border: 1px solid var(--border);
    }
    .mini .label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .mini .value {
      font-size: 18px;
      font-weight: 800;
      word-break: break-all;
    }
    .section {
      padding: 16px;
      margin-bottom: 14px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    .section-title {
      font-size: 18px;
      font-weight: 800;
    }
    .pill {
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      border: 1px solid var(--border);
      background: #091321;
      color: var(--muted);
    }
    .cards-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    .cards-grid.futures-grid {
      grid-template-columns: repeat(4, 1fr);
    }
    .quote-card {
      padding: 14px;
      position: relative;
      overflow: hidden;
    }
    .quote-card::after {
      content: "";
      position: absolute;
      inset: auto -20% -60% auto;
      width: 120px;
      height: 120px;
      border-radius: 999px;
      background: rgba(255,255,255,0.03);
      filter: blur(2px);
    }
    .card-top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 10px;
    }
    .symbol {
      font-weight: 800;
      font-size: 16px;
      line-height: 1.2;
    }
    .name {
      color: var(--muted);
      font-size: 12px;
      margin-top: 5px;
    }
    .badge {
      font-size: 11px;
      padding: 5px 8px;
      border-radius: 999px;
      border: 1px solid var(--border);
      white-space: nowrap;
    }
    .price {
      font-size: 30px;
      font-weight: 900;
      letter-spacing: .3px;
      margin: 6px 0 10px;
    }
    .change-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .change-chip {
      padding: 7px 10px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 800;
    }
    .up {
      color: var(--up);
      background: var(--up-bg);
      border: 1px solid rgba(255, 77, 87, 0.26);
    }
    .down {
      color: var(--down);
      background: var(--down-bg);
      border: 1px solid rgba(52, 211, 153, 0.26);
    }
    .flat {
      color: var(--flat);
      background: var(--flat-bg);
      border: 1px solid rgba(251, 191, 36, 0.24);
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    .sparkline-wrap {
      margin: 10px 0 8px;
      height: 62px;
      border-radius: 14px;
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border);
      padding: 8px;
    }
    .sparkline {
      width: 100%;
      height: 100%;
      display: block;
    }
    .sparkline path.line-up { stroke: var(--up); }
    .sparkline path.line-down { stroke: var(--down); }
    .sparkline path.line-flat { stroke: var(--flat); }
    .sparkline path {
      fill: none;
      stroke-width: 3;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .sparkline polyline.area-up { fill: rgba(255, 77, 87, 0.10); }
    .sparkline polyline.area-down { fill: rgba(52, 211, 153, 0.10); }
    .sparkline polyline.area-flat { fill: rgba(251, 191, 36, 0.08); }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      display: table;
    }
    th, td {
      padding: 13px 10px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      text-align: left;
      font-size: 14px;
    }
    th { color: var(--muted); }

    .desktop-only { display: block; }
    .mobile-only { display: none; }

    .footer {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.8;
    }

    @media (max-width: 980px) {
      .cards-grid { grid-template-columns: repeat(2, 1fr); }
      .cards-grid.futures-grid { grid-template-columns: repeat(2, 1fr); }
      .stats { grid-template-columns: repeat(2, 1fr); }
    }

    @media (max-width: 700px) {
      .wrap { width: min(100%, calc(100% - 12px)); }
      .hero, .section { border-radius: 18px; padding: 14px; }
      .hero h1 { font-size: 20px; }
      .control-row { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr 1fr; gap: 8px; }
      .mini { border-radius: 14px; }
      .mini .value { font-size: 15px; }
      .desktop-only { display: none; }
      .mobile-only { display: block; }
      .cards-grid,
      .cards-grid.futures-grid { grid-template-columns: 1fr; }
      .price { font-size: 28px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>即時看盤面板 v2</h1>
      <div class="muted">
        已升級成手機卡片式、漲跌強化顏色、台指 / 小台 / 微台專區、簡易走勢小圖。<br>
        手機同 Wi‑Fi 可直接開：<strong>http://{{ local_ip }}:{{ port }}</strong>
      </div>
      <div class="control-row">
        <input id="symbolsInput" value="{{ ','.join(default_symbols) }}" placeholder="輸入代號，用逗號分隔，例如：2330.TW,0050.TW,^TWII,BTC-USD">
        <button id="refreshBtn">立即更新</button>
      </div>
      <div class="stats">
        <div class="mini">
          <div class="label">更新頻率</div>
          <div class="value">每 {{ refresh_seconds }} 秒</div>
        </div>
        <div class="mini">
          <div class="label">本機網址</div>
          <div class="value">{{ local_ip }}:{{ port }}</div>
        </div>
        <div class="mini">
          <div class="label">資料模式</div>
          <div class="value" id="dataMode">讀取中...</div>
        </div>
        <div class="mini">
          <div class="label">更新時間</div>
          <div class="value" id="serverTimeMini">--</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-head">
        <div class="section-title">台指 / 小台 / 微台專區</div>
        <div class="pill" id="futuresCount">--</div>
      </div>
      <div class="cards-grid futures-grid mobile-only" id="futuresCards"></div>
      <div class="desktop-only">
        <table>
          <thead>
            <tr>
              <th>標的</th>
              <th>最新價</th>
              <th>漲跌</th>
              <th>漲跌幅</th>
              <th>來源</th>
              <th>更新時間</th>
            </tr>
          </thead>
          <tbody id="futuresTableBody">
            <tr><td colspan="6" class="muted">資料載入中...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <div class="section-head">
        <div class="section-title">自選標的</div>
        <div>
          <span class="pill" id="watchCount">追蹤標的：--</span>
          <span class="pill" id="serverTime">伺服器時間：--</span>
        </div>
      </div>
      <div class="cards-grid" id="watchCards"></div>
      <div class="footer">
        台指 / 小台 / 微台目前先做示意專區。若你之後接到正式期貨報價源，可以直接把代理資料替換成真實資料。<br>
        走勢小圖目前顯示最近幾次刷新價格，用來快速看方向感。之後可再升級成真正分時圖。
      </div>
    </div>
  </div>

  <script>
    const watchCards = document.getElementById('watchCards');
    const futuresCards = document.getElementById('futuresCards');
    const futuresTableBody = document.getElementById('futuresTableBody');
    const symbolsInput = document.getElementById('symbolsInput');
    const refreshBtn = document.getElementById('refreshBtn');
    const serverTime = document.getElementById('serverTime');
    const serverTimeMini = document.getElementById('serverTimeMini');
    const watchCount = document.getElementById('watchCount');
    const futuresCount = document.getElementById('futuresCount');
    const dataMode = document.getElementById('dataMode');

    function cls(n) {
      if (n > 0) return 'up';
      if (n < 0) return 'down';
      return 'flat';
    }

    function fmtSigned(n) {
      const sign = n > 0 ? '+' : '';
      return sign + Number(n).toFixed(2);
    }

    function sparklineSvg(values, delta) {
      if (!values || values.length < 2) {
        return '';
      }
      const w = 220;
      const h = 54;
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = max - min || 1;
      const points = values.map((v, i) => {
        const x = (i / (values.length - 1)) * w;
        const y = h - ((v - min) / range) * h;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');
      const areaPoints = `0,${h} ${points} ${w},${h}`;
      const lineClass = delta > 0 ? 'line-up' : delta < 0 ? 'line-down' : 'line-flat';
      const areaClass = delta > 0 ? 'area-up' : delta < 0 ? 'area-down' : 'area-flat';

      return `
        <svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
          <polyline class="${areaClass}" points="${areaPoints}"></polyline>
          <path class="${lineClass}" d="M ${points.replace(/ /g, ' L ')}"></path>
        </svg>
      `;
    }

    function renderCard(q) {
      const c = cls(q.change);
      const badgeText = q.category === 'futures' ? '期貨專區' : '自選';
      return `
        <div class="card quote-card">
          <div class="card-top">
            <div>
              <div class="symbol">${q.symbol}</div>
              <div class="name">${q.name || q.symbol}</div>
            </div>
            <div class="badge ${c}">${badgeText}</div>
          </div>
          <div class="price ${c}">${Number(q.price).toFixed(2)}</div>
          <div class="change-row">
            <div class="change-chip ${c}">${fmtSigned(q.change)}</div>
            <div class="change-chip ${c}">${fmtSigned(q.change_percent)}%</div>
          </div>
          <div class="sparkline-wrap">${sparklineSvg(q.history || [], q.change)}</div>
          <div class="meta">
            <span>${q.source}</span>
            <span>${q.updated_at}</span>
          </div>
        </div>
      `;
    }

    function renderFuturesTable(quotes) {
      if (!quotes.length) {
        futuresTableBody.innerHTML = `<tr><td colspan="6" class="muted">沒有資料</td></tr>`;
        return;
      }
      futuresTableBody.innerHTML = quotes.map(q => {
        const c = cls(q.change);
        return `
          <tr>
            <td>
              <div class="symbol">${q.symbol}</div>
              <div class="name">${q.name}</div>
            </td>
            <td class="${c}">${Number(q.price).toFixed(2)}</td>
            <td><span class="change-chip ${c}">${fmtSigned(q.change)}</span></td>
            <td><span class="change-chip ${c}">${fmtSigned(q.change_percent)}%</span></td>
            <td>${q.source}</td>
            <td>${q.updated_at}</td>
          </tr>
        `;
      }).join('');
    }

    async function loadQuotes() {
      const symbols = symbolsInput.value.trim();
      const url = `/api/quotes?symbols=${encodeURIComponent(symbols)}`;

      try {
        const res = await fetch(url, { cache: 'no-store' });
        const data = await res.json();

        dataMode.textContent = data.using_real_data ? 'yfinance / 真實資料優先' : 'mock / 畫面測試模式';
        serverTime.textContent = `伺服器時間：${data.server_time}`;
        serverTimeMini.textContent = data.server_time;
        watchCount.textContent = `追蹤標的：${data.watchlist.length}`;
        futuresCount.textContent = `期貨專區：${data.futures.length}`;

        watchCards.innerHTML = data.watchlist.map(renderCard).join('');
        futuresCards.innerHTML = data.futures.map(renderCard).join('');
        renderFuturesTable(data.futures);
      } catch (err) {
        watchCards.innerHTML = `<div class="card quote-card muted">讀取失敗：${String(err)}</div>`;
        futuresCards.innerHTML = `<div class="card quote-card muted">讀取失敗：${String(err)}</div>`;
        futuresTableBody.innerHTML = `<tr><td colspan="6" class="muted">讀取失敗：${String(err)}</td></tr>`;
      }
    }

    refreshBtn.addEventListener('click', loadQuotes);
    symbolsInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') loadQuotes();
    });

    loadQuotes();
    setInterval(loadQuotes, {{ refresh_seconds * 1000 }});
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    ip = get_local_ip()
    print("=" * 70)
    print("即時看盤面板 v2 啟動中")
    print(f"本機： http://127.0.0.1:{PORT}")
    print(f"手機同 Wi-Fi： http://{ip}:{PORT}")
    print("提示：若要真實資料，先安裝 yfinance -> pip install yfinance")
    print("=" * 70)
    app.run(host="0.0.0.0", port=PORT, debug=True)
