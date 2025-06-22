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
QUOTE = "ZUSD"
TIMEFRAME = 60  # 1 hour candles
TIMEZONE = 'US/Eastern'
CHECK_INTERVAL = 5  # seconds

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
BUY_ALL_RSI = 32
AGGRESSIVE_RSI = 27

# === CONNECT TO KRAKEN ===
k = krakenex.API(API_KEY, API_SECRET)
api = KrakenAPI(k)

# === UTILS ===
def log(msg):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": "XBTUSD", "interval": TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()
    ohlcv = list(data['result'].values())[1]
    df = pd.DataFrame(ohlcv, columns=[
        'timestamp', 'open', 'high', 'low', 'close',
        'vwap', 'volume', 'count'
    ])
    df['close'] = df['close'].astype(float)
    return df

def get_balances():
    balances = api.get_account_balance()
    fiat = float(balances[QUOTE].values[0]) if QUOTE in balances else 0.0
    btc = float(balances[ASSET].values[0]) if ASSET in balances else 0.0
    return fiat, btc

def execute_buy(percent):
    fiat, _ = get_balances()
    amount_to_spend = fiat * percent
    price = api.get_ticker_information(PAIR)['c'][0][0]
    volume = round(amount_to_spend / float(price), 6)
    log(f"BUY order: ${amount_to_spend:.2f
