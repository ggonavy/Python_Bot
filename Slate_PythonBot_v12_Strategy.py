import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime

# === CONFIGURATION ===
PAIR = "XBTUSDT"
TIMEFRAME = 60  # 1h = 60 min
API_URL = "https://api.kraken.com/0/public/OHLC"

# RSI Buy Ladder: RSI → % of funds to deploy
BUY_LADDER = [
    (47, 0.10),
    (42, 0.20),
    (37, 0.30),
    (32, 0.40)
]

# RSI Sell Ladder: RSI → % of position to sell
SELL_LADDER = [
    (73, 0.40),
    (77, 0.30),
    (81, 0.20),
    (85, 0.10)
]

# Cycle Rule State
last_action = None  # Track last bot action: 'buy' or 'sell'

def fetch_ohlcv():
    params = {"pair": PAIR, "interval": TIMEFRAME}
    res = requests.get(API_URL, params=params)
    ohlc = res.json()['result']
    key = list(ohlc.keys())[0]
    df = pd.DataFrame(ohlc[key], columns=[
        'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = df['close'].astype(float)
    return df

def calculate_rsi(df, period=14):
    rsi = RSIIndicator(close=df['close'], window=period).rsi()
    return rsi.iloc[-1]

def place_order(order_type, percent):
    # Replace this with real Kraken order code
    print(f"🟢 {order_type.upper()} order placed for {percent * 100}% of capital.")

def decide_and_trade():
    global last_action
    df = fetch_ohlcv()
    rsi = calculate_rsi(df)
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    print(f"[{timestamp}] RSI: {rsi:.2f} | Last Action: {last_action}")

    # Bot skips all buying if RSI < 27 (manual DCA only)
    if rsi < 27:
        print("⚠️ RSI < 27 — No bot buys. Manual DCA with cash.")
        return

    # Prevent bot from buying after sell until RSI is back to 47 or lower
    if last_action == 'sell' and rsi > 47:
        print("🔁 Waiting for RSI to reset below 47 before rebuying...")
        return

    # BUY Logic
    if last_action != 'buy':
        for level, percent in sorted(BUY_LADDER):
            if rsi <= level:
                place_order('buy', percent)
                last_action = 'buy'
                return

    # SELL Logic
    if last_action != 'sell':
        for level, percent in sorted(SELL_LADDER):
            if rsi >= level:
                place_order('sell', percent)
                last_action = 'sell'
                return

# === MAIN LOOP ===
if __name__ == "__main__":
    while True:
        try:
            decide_and_trade()
        except Exception as e:
            print(f"❌ ERROR: {e}")
        time.sleep(60 * 60)  # Wait 1 hour
