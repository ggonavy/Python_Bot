import time
import requests
import pandas as pd
import ta
from datetime import datetime
from pytz import timezone

# === CONFIG ===
PAIR = "BTC/USDT"
BUY_RSI = 43
SELL_RSI = 73
TIMEFRAME = "4h"
BOT_NAME = "SlateKrakenAuto"
THRESHOLD_DELAY = 60 * 60  # 1 hour between signals
WEBHOOK_URL = "https://api.3commas.io/public/api/v2/webhook/YOUR_WEBHOOK_KEY"  # <-- Replace this

# === STATE TRACKING ===
last_signal_time = 0
position = None

def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": "XBTUSDT", "interval": 240}
    response = requests.get(url, params=params)
    data = response.json()

    ohlcv_data = None
    for key in data['result']:
        if key != 'last':
            ohlcv_data = data['result'][key]
            break

    df = pd.DataFrame(ohlcv_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('timestamp', inplace=True)
    df['close'] = df['close'].astype(float)
    return df

def calculate_rsi(df):
    rsi = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    df['rsi'] = rsi
    return df

def send_signal(action):
    payload = {"action": action}
    try:
        response = requests.post(WEBHOOK_URL, json=payload)
        print(f"[{datetime.now()}] Sent {action.upper()} signal → {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[{datetime.now()}] ERROR sending signal: {e}")

def run_strategy():
    global last_signal_time, position
    try:
        df = fetch_ohlcv()
        df = calculate_rsi(df)
        rsi = df['rsi'].iloc[-1]
        now = time.time()

        print(f"[{datetime.now(timezone('US/Eastern'))}] RSI: {rsi:.2f} | Position: {position}")

        if rsi <= BUY_RSI and position != 'long' and (now - last_signal_time > THRESHOLD_DELAY):
            send_signal("buy")
            position = 'long'
            last_signal_time = now

        elif rsi >= SELL_RSI and position == 'long' and (now - last_signal_time > THRESHOLD_DELAY):
            send_signal("sell")
            position = None
            last_signal_time = now

    except Exception as e:
        print(f"[{datetime.now()}] Strategy error: {e}")

# === RENDER ENTRYPOINT ===
if __name__ == "__main__":
    while True:
        run_strategy()
        time.sleep(300)  # Wait 5 minutes before next check
