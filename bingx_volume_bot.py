import ccxt
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime, requests

# ---- CONFIG ----
EXCHANGE_ID = "bingx"
TIMEFRAME = "15m"
LIMIT = 50
LOOKBACK = 20
MULTIPLIER = 3.0
ZSCORE_THRESHOLD = 3.0
MIN_VOLUME = 1e6
MAX_WORKERS = 5
PAIR_SUFFIX = "USDT"
RATE_LIMIT_SLEEP = 0.3
CHECK_INTERVAL = 15 * 60  # 15 phút
# -----------------

# ---- TELEGRAM ----
BOT_TOKEN = "7715404094:AAG3rXoUODxNXJLFlecyQjDDtBK6lcNgtMw"
CHAT_ID = "7361205114"
# ------------------

def send_telegram(msg: str):
    """Gửi thông báo qua Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"[Telegram Error] {e}")

def get_futures_symbols(exchange, suffix=PAIR_SUFFIX):
    """Lấy danh sách hợp đồng USDT (standard contract)."""
    markets = exchange.load_markets()
    syms = []
    for sym, info in markets.items():
        if info.get("contract") and info.get("type") == "swap":
            if info.get("settle") == suffix and info.get("active", True):
                syms.append(sym)
    return sorted(set(syms))

def analyze_symbol(exchange, symbol):
    """Phân tích xem symbol có volume spike không."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
        if not ohlcv or len(ohlcv) < LOOKBACK + 2:
            return None

        volumes = [row[5] for row in ohlcv]
        volume_now = volumes[-1]
        prev_vols = volumes[-1 - LOOKBACK:-1]
        if len(prev_vols) < 3:
            return None

        mean = statistics.mean(prev_vols)
        stdev = statistics.pstdev(prev_vols)
        zscore = None
        reasons = []

        if mean > 0 and volume_now > MULTIPLIER * mean and volume_now >= MIN_VOLUME:
            reasons.append(f"multiplier: {volume_now:.0f} > {MULTIPLIER}*{mean:.0f}")
        if stdev > 0:
            zscore = (volume_now - mean) / stdev
            if zscore > ZSCORE_THRESHOLD:
                reasons.append(f"zscore: {zscore:.2f} > {ZSCORE_THRESHOLD}")

        if reasons:
            return {
                "symbol": symbol,
                "volume_now": volume_now,
                "mean_prev": mean,
                "stdev_prev": stdev,
                "zscore": zscore,
                "reasons": reasons,
                "timestamp": ohlcv[-1][0],
            }
        return None

    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
        return None


def run_scan():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    exchange.load_markets()
    symbols = get_futures_symbols(exchange)
    print(f"Tìm thấy {len(symbols)} hợp đồng (USDT-settled).")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(analyze_symbol, exchange, s): s for s in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                res = future.result()
                if res:
                    results.append(res)
            except Exception as e:
                print(f"[EXC] {sym}: {e}")
            time.sleep(RATE_LIMIT_SLEEP)

    results_sorted = sorted(
        results,
        key=lambda r: r["zscore"] if r["zscore"] else (r["volume_now"] / (r["mean_prev"] + 1e-9)),
        reverse=True,
    )

    return results_sorted


def main():
    print("🚀 Volume Spike Bot (BingX Futures) đang chạy...")
    while True:
        try:
            found = run_scan()
            if found:
                ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                msg_lines = [f"🔥 Volume Spike {len(found)} coin (BingX Futures, {TIMEFRAME})", f"Thời gian: {ts}", ""]
                for r in found[:10]:  # chỉ gửi top 10
                    z = r.get("zscore")
                    if z is None:
                        continue  
                    if z > 5.0:
                        msg_lines.append(
                            f"{r['symbol']}: vol={r['volume_now']:.0f} mean={r['mean_prev']:.0f} z={z}"
                        )
                send_telegram("\n".join(msg_lines))
                print("📤 Đã gửi cảnh báo Telegram.")
            else:
                print(f"{datetime.datetime.now()} - Không có spike nào.")

        except Exception as e:
            print("[Loop Error]", e)

        print(f"⏳ Chờ {CHECK_INTERVAL/60:.0f} phút để quét lại...\n")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()


