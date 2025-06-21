import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI

# === CONFIG ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEFRAME = 60  # 1h candles
CHECK_INTERVAL = 300  # Check every 5 minutes
TIMEZONE = 'US/Eastern'

# === STRATEGY SETTINGS ===
MIN_RSI_FOR_BUY = 27  # Bot stops buying below this (manual only)
REBUY_RSI_THRESHOLD = 47  # Bot resets only when RSI is below this again

BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

# === INIT ===
api = krakenex.API(key=API_KEY, secret=API_SECRET)
k = KrakenAPI(api)
buy_stack = []
sold_all = False

def log(msg):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_ohlcv():
    df, _ = k.get_ohlc_data(PAIR, interval=TIMEFRAME)
    df = df.dropna()
    df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
    return df

def get_balance(asset):
    balance = k.get_account_balance
