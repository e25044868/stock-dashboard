from __future__ import annotations

import os
import random
import socket
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

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
    "2330.TW",  # 台積電
    "0050.TW",  # 元大台灣50
    "00878.TW", # 國泰永續高股息
    "^TWII",    # 台股加權指數
    "BTC-USD",  # 比特幣
]


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    updated_at: str
    source: str


mock_state: Dict[str, Dict[str, float]] = {}


def get_local_ip() -> str:
    """取得本機區網 IP，方便手機同 Wi-Fi 存取。"""
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


def init_mock(symbol: str) -> None:
    if symbol in mock_state:
        return

    base_map = {
        "2330.TW": 860.0,
        "0050.TW": 180.0,
        "00878.TW": 22.0,
        "^TWII": 21000.0,
        "BTC-USD": 85000.0,
    }
    base = base_map.get(symbol, random.uniform(50, 500))
    mock_state[symbol] = {
        "prev_close": base,
        "price": base,
    }


def get_mock_quote(symbol: str) -> Quote:
    init_mock(symbol)
    prev_close = mock_state[symbol]["prev_close"]
    current = mock_state[symbol]["price"]

    drift = random.uniform(-0.006, 0.006)
    new_price = max(0.01, current * (1 + drift))
    mock_state[symbol]["price"] = new_price

    change = new_price - prev_close
    change_percent = (change / prev_close) * 100 if prev_close else 0.0

    return Quote(
        symbol=symbol,
        name=symbol,
        price=round(new_price, 2),
        change=round(change, 2),
        change_percent=round(change_percent, 2),
        updated_at=now_str(),
        source="mock",
    )


def get_yfinance_quote(symbol: str) -> Optional[Quote]:
    if yf is None:
        return None

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info if hasattr(ticker, "fast_info") else {}
        hist = ticker.history(period="2d", interval="1m")

        if hist is None or hist.empty:
            return None

        latest_price = float(hist["Close"].dropna().iloc[-1])

        if len(hist["Close"].dropna()) >= 2:
            prev_close = float(hist["Close"].dropna().iloc[-2])
        else:
            prev_close = float(info.get("previous_close") or latest_price)

        change = latest_price - prev_close
        change_percent = (change / prev_close) * 100 if prev_close else 0.0

        name = symbol
        try:
            meta = ticker.info
            name = meta.get("shortName") or meta.get("longName") or symbol
        except Exception:
            pass

        return Quote(
            symbol=symbol,
            name=name,
            price=round(latest_price, 2),
            change=round(change, 2),
            change_percent=round(change_percent, 2),
            updated_at=now_str(),
            source="yfinance",
        )
    except Exception:
        return None


def get_quote(symbol: str) -> Quote:
    real_quote = get_yfinance_quote(symbol)
    if real_quote is not None:
        return real_quote
    return get_mock_quote(symbol)


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
    symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()] or DEFAULT_SYMBOLS

    results: List[Dict] = []
    for symbol in symbols:
        quote = get_quote(symbol)
        results.append(asdict(quote))

    return jsonify({
        "ok": True,
        "refresh_seconds": REFRESH_SECONDS,
        "quotes": results,
        "server_time": now_str(),
        "using_real_data": yf is not None,
    })


HTML_TEMPLATE = r'''
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>即時看盤面板</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --up: #ef4444;
      --down: #22c55e;
      --flat: #f59e0b;
      --border: #374151;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #0b1220, #111827);
      color: var(--text);
      font-family: Arial, "Noto Sans TC", sans-serif;
    }
    .wrap {
      width: min(1100px, calc(100% - 24px));
      margin: 20px auto 40px;
    }
    .topbar {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }
    .card {
      background: rgba(17, 24, 39, 0.95);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 12px 30px rgba(0,0,0,.25);
    }
    h1 {
      margin: 0 0 6px;
      font-size: 24px;
    }
    .muted {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    .control-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      margin-top: 12px;
    }
    input {
      width: 100%;
      border: 1px solid var(--border);
      background: #0b1220;
      color: var(--text);
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 14px;
    }
    button {
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      cursor: pointer;
      font-size: 14px;
      font-weight: bold;
      background: #2563eb;
      color: white;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 16px;
    }
    .mini {
      background: var(--panel-2);
      border-radius: 14px;
      padding: 12px;
      border: 1px solid var(--border);
    }
    .mini .label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .mini .value {
      font-size: 18px;
      font-weight: 700;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      margin-top: 10px;
    }
    th, td {
      padding: 14px 10px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      text-align: left;
      font-size: 14px;
    }
    th {
      color: var(--muted);
      font-weight: 600;
    }
    .up { color: var(--up); font-weight: 700; }
    .down { color: var(--down); font-weight: 700; }
    .flat { color: var(--flat); font-weight: 700; }
    .symbol { font-weight: 700; }
    .name {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }
    .pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      border: 1px solid var(--border);
      background: #0b1220;
      color: var(--muted);
    }
    .footer {
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.8;
    }
    @media (max-width: 768px) {
      h1 { font-size: 20px; }
      .control-row { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr; }
      th:nth-child(2), td:nth-child(2) { display: none; }
      th, td { padding: 12px 8px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar card">
      <div>
        <h1>即時看盤面板</h1>
        <div class="muted">
          先做第一版：自選股 / 指數清單、最新價、漲跌、漲跌幅、自動更新。<br>
          手機同 Wi‑Fi 可直接開：<strong>http://{{ local_ip }}:{{ port }}</strong>
        </div>
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
          <div class="value" style="font-size:15px;">{{ local_ip }}:{{ port }}</div>
        </div>
        <div class="mini">
          <div class="label">資料模式</div>
          <div class="value" id="dataMode">讀取中...</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;">
        <div class="pill" id="serverTime">伺服器時間：--</div>
        <div class="pill" id="watchCount">追蹤標的：--</div>
      </div>

      <table>
        <thead>
          <tr>
            <th>標的</th>
            <th>名稱</th>
            <th>最新價</th>
            <th>漲跌</th>
            <th>漲跌幅</th>
            <th>更新時間</th>
            <th>來源</th>
          </tr>
        </thead>
        <tbody id="quoteBody">
          <tr><td colspan="7" class="muted">資料載入中...</td></tr>
        </tbody>
      </table>

      <div class="footer">
        1. 如果你有安裝 <code>yfinance</code> 且網路可用，會嘗試抓真實資料。<br>
        2. 若抓不到資料，會自動切換成 mock 模式，方便先測畫面與手機連線。<br>
        3. 下一版可以再加：分時圖、到價提醒、台指期 / 微台、紅綠閃動、手機版卡片視圖。
      </div>
    </div>
  </div>

  <script>
    const quoteBody = document.getElementById('quoteBody');
    const symbolsInput = document.getElementById('symbolsInput');
    const refreshBtn = document.getElementById('refreshBtn');
    const serverTime = document.getElementById('serverTime');
    const watchCount = document.getElementById('watchCount');
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

    async function loadQuotes() {
      const symbols = symbolsInput.value.trim();
      const url = `/api/quotes?symbols=${encodeURIComponent(symbols)}`;

      try {
        const res = await fetch(url, { cache: 'no-store' });
        const data = await res.json();

        dataMode.textContent = data.using_real_data ? 'yfinance / 真實資料優先' : 'mock / 畫面測試模式';
        serverTime.textContent = `伺服器時間：${data.server_time}`;
        watchCount.textContent = `追蹤標的：${data.quotes.length}`;

        if (!data.quotes.length) {
          quoteBody.innerHTML = `<tr><td colspan="7" class="muted">沒有資料</td></tr>`;
          return;
        }

        quoteBody.innerHTML = data.quotes.map(q => `
          <tr>
            <td>
              <div class="symbol">${q.symbol}</div>
            </td>
            <td>
              <div>${q.name || q.symbol}</div>
            </td>
            <td class="${cls(q.change)}">${Number(q.price).toFixed(2)}</td>
            <td class="${cls(q.change)}">${fmtSigned(q.change)}</td>
            <td class="${cls(q.change)}">${fmtSigned(q.change_percent)}%</td>
            <td>${q.updated_at}</td>
            <td>${q.source}</td>
          </tr>
        `).join('');
      } catch (err) {
        quoteBody.innerHTML = `<tr><td colspan="7" class="muted">讀取失敗：${String(err)}</td></tr>`;
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
'''


if __name__ == "__main__":
    ip = get_local_ip()
    print("=" * 70)
    print("即時看盤面板啟動中")
    print(f"本機： http://127.0.0.1:{PORT}")
    print(f"手機同 Wi-Fi： http://{ip}:{PORT}")
    print("提示：若要真實資料，先安裝 yfinance -> pip install yfinance")
    print("=" * 70)
    app.run(host="0.0.0.0", port=PORT, debug=True)
