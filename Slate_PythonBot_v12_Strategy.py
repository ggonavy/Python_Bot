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
TIMEFRAME = 60
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47

# === KRAKEN CONNECTION ===
k = krakenex.API(API_KEY, API_SECRET)
kraken = KrakenAPI(k)

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
    rsi = RSIIndicator(df['close'], window=14).rsi()
    return rsi.iloc[-1]

def get_balances():
    try:
        balances = kraken.get_account_balance()
        print(f"[DEBUG] Full Kraken balance snapshot:\n{balances}")  # <-- debug line
        fiat = float(balances.get(QUOTE, 0))
        btc = float(balances.get(ASSET, 0))
        return fiat, btc
    except Exception as e:
        print(f"[ERROR] Failed to fetch balances: {e}")
        return 0, 0

def place_market_order(pair, type_, volume):
    try:
        kraken.add_standard_order(pair=pair, type=type_, ordertype='market', volume=volume)
        print(f"✅ Order executed: {type_.upper()} {volume:.6f} {ASSET}")
    except Exception as e:
        print(f"❌ Order error: {e}")

# === MAIN BOT LOOP ===
def run_bot():
    step = 0
    fiat, btc = 0, 0

    while True:
        try:
            df = get_ohlcv(PAIR, TIMEFRAME)
            rsi = get_rsi(df)

            if step % 3 == 0:
                fiat, btc = get_balances()

            now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now}] RSI: {rsi:.2f} | FIAT: ${fiat:.2f} | BTC: {btc:.6f}")

            # === BUY LOGIC ===
            if fiat > 5:
                if rsi <= 27:
                    place_market_order(PAIR, 'buy', fiat / df['close'].iloc[-1])
                elif rsi <= 32:
                    place_market_order(PAIR, 'buy', fiat / df['close'].iloc[-1])
                elif rsi <= REBUY_RSI_THRESHOLD:
                    for threshold, pct in BUY_LADDER:
                        if rsi <= threshold:
                            amount = fiat * pct
                            if amount > 5:
                                place_market_order(PAIR, 'buy', amount / df['close'].iloc[-1])
                            break

            # === SELL LOGIC ===
            if btc > 0.0001:
                for threshold, pct in SELL_LADDER:
                    if rsi >= threshold:
                        amount = btc * pct
                        if amount > 0.0001:
                            place_market_order(PAIR, 'sell', amount)
                        break

        except Exception as e:
            print(f"[ERROR] Bot loop failed: {e}")

        step += 1
        time.sleep(1.2)  # Throttle-safe
