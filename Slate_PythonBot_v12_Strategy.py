import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI

# === CONFIGURATION ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"  # ⚠️ TEMP — we’ll update this once logs confirm correct fiat key
TIMEFRAME = 60  # 1-hour candles
TIMEZONE = 'US/Eastern'

# === STRATEGY SETTINGS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # RSI ≤ 32 → 100% fiat
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
last_buy_rsi = 100

# === KRAKEN CONNECTION ===
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def log(msg):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_latest_rsi():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params).json()
    ohlc_key = [key for key in response['result'] if key != 'last'][0]
    candles = response['result'][ohlc_key]

    df = pd.DataFrame(candles, columns=[
        'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = pd.to_numeric(df['close'])
    rsi = RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]  # ✅ FIXED
    return round(rsi, 2)

def get_balances():
    balances = k.get_account_balance()

    log("🔍 RAW BALANCES:")
    for asset in balances.index:
        vol = balances.loc[asset]["vol"]
        log(f"  {asset} => {vol}")

    btc = float(balances.loc[ASSET]["vol"]) if ASSET in balances.index else 0.0
    usd = float(balances.loc[QUOTE]["vol"]) if QUOTE in balances.index else 0.0
    return btc, usd

def place_market_buy(usd_amount):
    if usd_amount < 5:
        log(f"🟡 Not enough USD to buy: ${usd_amount
