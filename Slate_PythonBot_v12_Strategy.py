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
TIMEFRAME = 60  # 1-hour candles
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
REBUY_RSI_THRESHOLD = 47
MIN_RSI_TO_FORCE_BUY = 27

BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]
FULL_BUY_RSI = 32

SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

# === INIT ===
k = krakenex.API(API_KEY, API_SECRET)
api = KrakenAPI(k)
last_buy_rsi = 100
last_sell_rsi = 0

def log(msg):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()
    candles = list(data['result'].values())[0]
    df = pd.DataFrame(candles, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = pd.to_numeric(df['close'])
    return df

def get_rsi(df):
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    return rsi.iloc[-1]

def get_balances():
    balances = api.get_account_balance()
    fiat = float(balances[QUOTE]) if QUOTE in balances else 0.0
    btc = float(balances[ASSET]) if ASSET in balances else 0.0
    return fiat, btc

def execute_buy(percent):
    fiat, _ = get_balances()
    amount_to_spend = fiat * percent
    price = api.get_ticker_information(PAIR)['c'][0][0]
    volume = round(amount_to_spend / float(price), 6)
    log(f"BUY order: {amount_to_spend:.2f} USD ({volume} BTC)")
    api.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)

def execute_sell(percent):
    _, btc = get_balances()
    amount_to_sell = btc * percent
    log(f"SELL order: {amount_to_sell:.6f} BTC")
    api.add_standard_order(pair=PAIR, type='sell', ordertype='market', volume=round(amount_to_sell, 6))

while True:
    try:
        df = fetch_ohlcv()
        rsi = get_rsi(df)
        fiat, btc = get_balances()
        log(f"RSI: {rsi:.2f} | Fiat: {fiat:.2f} | BTC: {btc:.6f}")

        # === BUY LOGIC ===
        if rsi <= MIN_RSI_TO_FORCE_BUY and fiat > 5:
            log(f"RSI ≤ {MIN_RSI_TO_FORCE_BUY}: Buying ALL available fiat aggressively.")
            price = api.get_ticker_information(PAIR)['c'][0][0]
            volume = round(fiat / float(price), 6)
            log(f"FULL BUY at RSI {rsi:.2f}: {fiat:.2f} USD = {volume} BTC")
            api.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)
            last_buy_rsi = rsi

        elif rsi <= FULL_BUY_RSI and fiat > 5:
            price = api.get_ticker_information(PAIR)['c'][0][0]
            volume = round(fiat / float(price), 6)
            log(f"FULL BUY at RSI {rsi:.2f}: {fiat:.2f} USD = {volume} BTC")
            api.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)
            last_buy_rsi = rsi

        elif rsi <= REBUY_RSI_THRESHOLD and rsi < last_buy_rsi:
            for level_rsi, pct in BUY_LADDER:
                if rsi <= level_rsi and fiat > 5:
                    execute_buy(pct)
                    last_buy_rsi = rsi
                    break

        # === SELL LOGIC ===
        if rsi >= 72:
            for level_rsi, pct in SELL_LADDER:
                if rsi >= level_rsi and btc > 0.00001:
                    execute_sell(pct)
                    last_sell_rsi = rsi
                    break

        # === RESET FLAGS ===
        if rsi >= REBUY_RSI_THRESHOLD:
            last_buy_rsi = 100

        if rsi <= 72:
            last_sell_rsi = 0

    except Exception as e:
        log(f"Error: {e}")

    time.sleep(60)
