import time
import requests
import pandas as pd
import ta
import hashlib
import hmac
import base64
import urllib.parse
import os
from datetime import datetime
from pytz import timezone

# === USER CONFIG ===
API_KEY = os.environ.get("haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM")
API_SECRET = os.environ.get("MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q==")
PAIR = "XBTUSDT"
BASE_CURRENCY = "XBT"
QUOTE_CURRENCY = "USDT"
TIMEFRAME = 60  # 1h candles
RSI_WINDOW = 14

buy_levels = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
sell_levels = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

min_rsi_to_buy = 27
reset_rsi = 47

bought_levels = set()
sold_levels = set()

def log(msg):
    now = datetime.now(timezone("US/Eastern")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

# === OHLCV and RSI ===
def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()["result"]
    pair_key = next(k for k in data if k != "last")
    df = pd.DataFrame(data[pair_key], columns=[
        "time", "open", "high", "low", "close",
        "vwap", "volume", "count"
    ])
    df["close"] = df["close"].astype(float)
    return df

def get_latest_rsi():
    df = fetch_ohlcv()
    rsi = ta.momentum.RSIIndicator(df["close"], window=RSI_WINDOW).rsi()
    return rsi.iloc[-1]

# === KRAKEN API CALLS ===
def kraken_request(uri_path, data):
    url = f"https://api.kraken.com{uri_path}"
    nonce = str(int(1000 * time.time()))
    data["nonce"] = nonce
    postdata = urllib.parse.urlencode(data)
    encoded = (nonce + postdata).encode()
    message = uri_path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(API_SECRET), message, hashlib.sha512)
    headers = {
        "API-Key": API_KEY,
        "API-Sign": base64.b64encode(mac.digest())
    }
    return requests.post(url, headers=headers, data=data).json()

def get_balance(asset):
    res = kraken_request("/0/private/Balance", {})
    return float(res["result"].get(asset, 0))

def get_price():
    url = f"https://api.kraken.com/0/public/Ticker?pair={PAIR}"
    res = requests.get(url).json()
    pair_data = next(iter(res["result"].values()))
    return float(pair_data["c"][0])

def place_market_order(type_, volume):
    data = {
        "pair": PAIR,
        "type": type_,
        "ordertype": "market",
        "volume": volume
    }
    res = kraken_request("/0/private/AddOrder", data)
    log(f"Order Response: {res}")
    return res

# === TRADE LOGIC ===
def trade_logic():
    global bought_levels, sold_levels

    rsi = get_latest_rsi()
    price = get_price()
    usdt = get_balance(QUOTE_CURRENCY)
    btc = get_balance(BASE_CURRENCY)

    log(f"RSI: {rsi:.2f} | USDT: {usdt:.2f} | BTC: {btc:.6f}")

    # === RESET CYCLE ===
    if rsi <= reset_rsi:
        bought_levels.clear()
        sold_levels.clear()
        log("🔄 Cycle reset: RSI <= 47")

    # === BUY LADDER ===
    for level, percent in buy_levels:
        if rsi <= level and level not in bought_levels and rsi >= min_rsi_to_buy:
            amount_usdt = usdt * percent
            btc_to_buy = round(amount_usdt / price, 6)
            if btc_to_buy > 0.0001:
                place_market_order("buy", btc_to_buy)
                bought_levels.add(level)
                log(f"✅ BUY {btc_to_buy:.6f} BTC at RSI {rsi:.2f} | Level {level}")

    # === SELL LADDER ===
    for level, percent in sell_levels:
        if rsi >= level and level not in sold_levels:
            btc_to_sell = round(btc * percent, 6)
            if btc_to_sell > 0.0001:
                place_market_order("sell", btc_to_sell)
                sold_levels.add(level)
                log(f"✅ SELL {btc_to_sell:.6f} BTC at RSI {rsi:.2f} | Level {level}")

# === MAIN LOOP ===
if __name__ == "__main__":
    log("🚀 SlateBot v12 started with RSI ladder logic")
    while True:
        try:
            trade_logic()
        except Exception as e:
            log(f"Error: {e}")
        time.sleep(60)
