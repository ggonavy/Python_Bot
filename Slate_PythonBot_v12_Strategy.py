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

# === STRATEGY SETTINGS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Full buy at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]  # Full sell by RSI 85
REBUY_RSI_THRESHOLD = 47
last_buy_rsi = 100  # High to allow first buy

# === INIT KRAKEN ===
k = krakenex.API(API_KEY, API_SECRET)
kraken = KrakenAPI(k)

# === FUNCTIONS ===
def get_ohlcv(pair, interval):
    url = f'https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}'
    response = requests.get(url).json()
    key = list(response['result'].keys())[0]
    df = pd.DataFrame(response['result'][key], columns=[
        'time','open','high','low','close','vwap','volume','count'
    ])
    df['close'] = df['close'].astype(float)
    return df

def get_rsi(df, period=14):
    return RSIIndicator(df['close'], window=period).rsi().iloc[-1]

def get_balances():
    try:
        balances = kraken.get_account_balance()
        fiat = float(balances.get(QUOTE, 0))
        btc = float(balances.get(ASSET, 0))
        return fiat, btc
    except Exception as e:
        print(f"[ERROR] Failed to get balances: {e}")
        return 0, 0

def place_market_order(pair, side, volume):
    try:
        response = kraken.add_standard_order(pair=pair, type=side, ordertype='market', volume=volume)
        print(f"✅ Executed {side.upper()} order for {volume:.6f}")
    except Exception as e:
        print(f"[ERROR] Order failed: {e}")

# === MAIN LOOP ===
def run_bot():
    global last_buy_rsi
    while True:
        try:
            df = get_ohlcv(PAIR, TIMEFRAME)
            rsi = get_rsi(df)
            fiat, btc = get_balances()
            now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')

            print(f"[{now}] RSI: {rsi:.2f} | FIAT: {fiat:.2f} | BTC: {btc:.6f}")

            # === BUY LOGIC ===
            if fiat > 5:
                if rsi <= 27:
                    place_market_order(PAIR, 'buy', fiat / df['close'].iloc[-1])
                    last_buy_rsi = rsi
                elif rsi <= 32:
                    place_market_order(PAIR, 'buy', fiat / df['close'].iloc[-1])
                    last_buy_rsi = rsi
                elif rsi <= REBUY_RSI_THRESHOLD and rsi < last_buy_rsi:
                    for level, pct in BUY_LADDER:
                        if rsi <= level:
                            amount = fiat * pct
                            if amount > 5:
                                place_market_order(PAIR, 'buy', amount / df['close'].iloc[-1])
                                last_buy_rsi = rsi
                                break

            # === SELL LOGIC ===
            if btc > 0.0001:
                for level, pct in SELL_LADDER:
                    if rsi >= level:
                        amount = btc * pct
                        if amount > 0.0001:
                            place_market_order(PAIR, 'sell', amount)
                        break

        except Exception as e:
            print(f"[ERROR] Bot crash: {e}")

        time.sleep(1)  # keep under Kraken 20/sec limit

# === START BOT ===
run_bot()
