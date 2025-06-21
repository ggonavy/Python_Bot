import time
import requests
import pandas as pd
import ta
import krakenex
from pykrakenapi import KrakenAPI
from datetime import datetime
from pytz import timezone

# === CONFIGURATION ===
KRAKEN_API_KEY = 'haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM'
KRAKEN_API_SECRET = 'MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=='
PAIR = 'XXBTZUSD'  # BTC/USD Kraken pair
TRADE_ASSET = 'XBT'
QUOTE_ASSET = 'ZUSD'
TIMEFRAME = 60  # in minutes (1h = 60)
RSI_PERIOD = 14

BUY_LEVELS = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LEVELS = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

MIN_TRADE_AMOUNT = 10  # Kraken requires minimum size
last_buy_time = 0
last_sell_time = 0
signal_cooldown = 60 * 60  # 1 hour cooldown

# === INIT ===
k = krakenex.API()
k.load_key('kraken.key')  # If using key file
k.key = KRAKEN_API_KEY
k.secret = KRAKEN_API_SECRET
kraken = KrakenAPI(k)

def log(msg):
    now = datetime.now(timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()
    candles = list(data['result'].values())[0]
    df = pd.DataFrame(candles, columns=[
        'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = pd.to_numeric(df['close'])
    return df

def calculate_rsi(df):
    rsi = ta.momentum.RSIIndicator(df['close'], window=RSI_PERIOD)
    return rsi.rsi().iloc[-1]

def get_balance(asset):
    balance = kraken.get_account_balance()
    return float(balance.get(asset, 0.0))

def place_order(type_, volume):
    try:
        k.add_standard_order(pair=PAIR,
                             type=type_,
                             ordertype='market',
                             volume=str(volume))
        log(f"ORDER PLACED: {type_.upper()} {volume} {TRADE_ASSET}")
    except Exception as e:
        log(f"ERROR placing order: {e}")

while True:
    try:
        df = fetch_ohlcv()
        current_rsi = calculate_rsi(df)
        log(f"Current RSI: {current_rsi:.2f}")
        now = time.time()

        usd_balance = get_balance(QUOTE_ASSET)
        btc_balance = get_balance(TRADE_ASSET)

        # BUY
        if now - last_buy_time > signal_cooldown:
            for level, pct in BUY_LEVELS:
                if current_rsi <= level:
                    amount_to_spend = usd_balance * pct
                    ticker = kraken.get_ticker_information(PAIR)
                    price = float(ticker[PAIR]['c'][0])
                    buy_volume = amount_to_spend / price
                    if amount_to_spend >= MIN_TRADE_AMOUNT:
                        place_order('buy', round(buy_volume, 6))
                        last_buy_time = now
                    break

        # SELL
        if now - last_sell_time > signal_cooldown:
            for level, pct in SELL_LEVELS:
                if current_rsi >= level:
                    amount_to_sell = btc_balance * pct
                    if amount_to_sell * price >= MIN_TRADE_AMOUNT:
                        place_order('sell', round(amount_to_sell, 6))
                        last_sell_time = now
                    break

    except Exception as e:
        log(f"Unexpected error: {e}")

    time.sleep(60)
