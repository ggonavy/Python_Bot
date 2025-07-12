import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime
from pytz import timezone

# === CONFIG ===
SYMBOL = "BTC-USD"
TIMEFRAME_MINUTES = 60  # 1-hour RSI
TIMEZONE = 'US/Eastern'

# === STRATEGY ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]
RSI_PANIC_BUY = 27
RSI_FULL_SELL = 73
last_buy_rsi = 100

# === API PLACEHOLDERS (replace with real Coinbase code) ===
def get_account_balance():
    return {"usd": 10000, "btc": 0.25}  # Replace with actual API call

def execute_market_buy(amount_usd):
    print(f"[BUY] Buying ${amount_usd:.2f} BTC")

def execute_market_sell(amount_btc):
    print(f"[SELL] Selling {amount_btc:.6f} BTC")

def fetch_ohlcv():
    url = f"https://api.pro.coinbase.com/products/{SYMBOL}/candles?granularity={TIMEFRAME_MINUTES * 60}"
    try:
        response = requests.get(url)
        data = response.json()
        df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
        df = df.sort_values("time")
        df["rsi"] = RSIIndicator(close=df["close"]).rsi()
        return df
    except Exception as e:
        print("Error fetching candles:", e)
        return pd.DataFrame()

# === MAIN LOGIC ===
def check_and_trade():
    global last_buy_rsi
    df = fetch_ohlcv()
    if df.empty or df["rsi"].isna().all():
        print("No RSI data.")
        return

    latest_rsi = df["rsi"].iloc[-1]
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] RSI: {latest_rsi:.2f}")

    balances = get_account_balance()
    fiat = balances["usd"]
    btc = balances["btc"]

    # === SELL ALL BTC IF RSI ≥ 73 ===
    if latest_rsi >= RSI_FULL_SELL and btc > 0.00001:
        print(f"🚨 RSI {latest_rsi:.2f} ≥ {RSI_FULL_SELL} → SELLING ALL BTC")
        execute_market_sell(btc)
        return

    # === PANIC BUY ZONE RSI ≤ 27 ===
    if latest_rsi <= RSI_PANIC_BUY and fiat > 5:
        print(f"⚠️ RSI {latest_rsi:.2f} ≤ {RSI_PANIC_BUY} → PANIC BUY ALL-IN")
        execute_market_buy(fiat)
        return

    # === LADDERED BUYS ===
    for rsi_level, percent in BUY_LADDER:
        if latest_rsi <= rsi_level and last_buy_rsi > rsi_level:
            buy_amount = fiat * percent
            if buy_amount > 5:
                print(f"✅ BUY TRIGGERED | RSI: {latest_rsi:.2f} ≤ {rsi_level} → Buying ${buy_amount:.2f}")
                execute_market_buy(buy_amount)
                last_buy_rsi = latest_rsi
            return

if __name__ == "__main__":
    while True:
        try:
            check_and_trade()
            time.sleep(1)  # Check every second
        except Exception as e:
            print("Runtime error:", e)
            time.sleep(5)
