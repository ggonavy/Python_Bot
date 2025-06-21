import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime, timezone

# === CONFIGURATION ===
PAIR = "XBTUSDT"  # Kraken symbol for BTC/USDT
BUY_RSI = 43
SELL_RSI = 73
TIMEFRAME_MINUTES = 240  # 4h
CHECK_INTERVAL = 300  # 5 minutes between checks
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"

last_action = None

# === FUNCTIONS ===

def fetch_ohlcv():
    try:
        params = {"pair": PAIR, "interval": TIMEFRAME_MINUTES}
        response = requests.get(KRAKEN_URL, params=params)
        data = response.json()
        ohlcv_data = data['result'][list(data['result'].keys())[1]]
        df = pd.DataFrame(ohlcv_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
        ])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Failed to fetch OHLCV: {e}")
        return None

def calculate_rsi(df, period=14):
    try:
        rsi = RSIIndicator(close=df['close'], window=period).rsi()
        return rsi.iloc[-1]
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Failed to calculate RSI: {e}")
        return None

def execute_trade(action):
    global last_action
    now = datetime.now(timezone.utc)
    print(f"[{now}] Executing action: {action.upper()}")
    last_action = action

    # === Kraken trade logic will go here ===
    # For now, this just logs it
    # Later, plug in real Kraken API calls here
    return

def run_bot():
    global last_action
    print(f"[{datetime.now(timezone.utc)}] SlateBot v12 starting with RSI {BUY_RSI}/{SELL_RSI} logic...")

    while True:
        df = fetch_ohlcv()
        if df is None or len(df) < 15:
            print(f"[{datetime.now(timezone.utc)}] Waiting on valid data...")
            time.sleep(CHECK_INTERVAL)
            continue

        current_rsi = calculate_rsi(df)
        current_price = df['close'].iloc[-1]

        print(f"[{datetime.now(timezone.utc)}] RSI: {round(current_rsi, 2)} | BTC: ${round(current_price, 2)}")

        if current_rsi <= BUY_RSI and last_action != "buy":
            execute_trade("buy")

        elif current_rsi >= SELL_RSI and last_action != "sell":
            execute_trade("sell")

        else:
            print(f"[{datetime.now(timezone.utc)}] No trade executed. Waiting...")

        time.sleep(CHECK_INTERVAL)

# === RUN ===
if __name__ == "__main__":
    run_bot()
