import time
import requests
import pandas as pd
import ta
from datetime import datetime
from pytz import timezone

# === CONFIG ===
PAIR = "XBTUSDT"
TIMEFRAME = 60  # 1h
BASE_TRADE_BALANCE = 500  # Only $500 for trading test
THRESHOLD_DELAY = 60 * 60  # 1 hour between actions

BUY_LEVELS = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LEVELS = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

last_signal_time = None
buy_stack = []
total_bought = 0.0

def log(msg):
    now = datetime.now(timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()
    candles = data['result'][PAIR]
    df = pd.DataFrame(candles, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = df['close'].astype(float)
    return df

def get_rsi(df, length=14):
    rsi = ta.momentum.RSIIndicator(close=df['close'], window=length)
    return rsi.rsi().iloc[-1]

def place_order(side, usd_amount):
    log(f"MOCK ORDER: {side.upper()} ${usd_amount:.2f}")
    # Replace with real Kraken API trade logic

def main():
    global last_signal_time, total_bought, buy_stack

    while True:
        try:
            now = time.time()
            if last_signal_time and now - last_signal_time < THRESHOLD_DELAY:
                log("Waiting due to signal delay window...")
                time.sleep(60)
                continue

            df = fetch_ohlcv()
            rsi = get_rsi(df)
            log(f"RSI: {rsi:.2f}")

            # BUY ladder logic
            for level, pct in BUY_LEVELS:
                if rsi <= level and level not in [b[0] for b in buy_stack]:
                    usd_to_buy = BASE_TRADE_BALANCE * pct
                    place_order("buy", usd_to_buy)
                    buy_stack.append((level, usd_to_buy))
                    total_bought += usd_to_buy
                    last_signal_time = now
                    break

            # SELL ladder logic
            for level, pct in SELL_LEVELS:
                if rsi >= level and total_bought > 0:
                    usd_to_sell = total_bought * pct
                    place_order("sell", usd_to_sell)
                    total_bought -= usd_to_sell
                    last_signal_time = now
                    if total_bought <= 10:
                        buy_stack = []
                        total_bought = 0.0
                    break

            time.sleep(300)

        except Exception as e:
            log(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
