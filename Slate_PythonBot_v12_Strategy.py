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
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # 100% fiat deploy at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

REBUY_RSI_THRESHOLD = 47
MIN_BUY_RSI = 27  # Force buy at or below this RSI

last_buy_rsi = 100  # Track last buy RSI to prevent repeats

# === INIT KRAKEN ===
k = krakenex.API(API_KEY, API_SECRET)
kraken = KrakenAPI(k)

def fetch_rsi():
    url = f"https://api.kraken.com/0/public/OHLC?pair={PAIR}&interval={TIMEFRAME}"
    df = pd.DataFrame(requests.get(url).json()['result'][PAIR], columns=[
        'time','open','high','low','close','vwap','volume','count'
    ])
    df['close'] = df['close'].astype(float)
    rsi = RSIIndicator(df['close'], window=14).rsi().iloc[-1]
    return round(rsi, 2)

def fetch_balances():
    balances = kraken.get_account_balance()
    fiat = float(balances.get(QUOTE, 0))
    btc = float(balances.get(ASSET, 0))
    return fiat, btc

def place_buy_order(percent):
    fiat, _ = fetch_balances()
    amount = fiat * percent
    price = float(kraken.get_ticker_information(PAIR)['c'][0])
    volume = round(amount / price, 6)
    if volume > 0:
        print(f"📈 BUYING {volume} BTC using ${amount:.2f}")
        # kraken.add_standard_order(PAIR, 'buy', 'market', volume)

def place_sell_order(percent):
    _, btc = fetch_balances()
    amount = btc * percent
    if amount > 0:
        print(f"📉 SELLING {amount:.6f} BTC at current RSI step")
        # kraken.add_standard_order(PAIR, 'sell', 'market', round(amount, 6))

def execute_strategy():
    global last_buy_rsi
    while True:
        try:
            now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
            rsi = fetch_rsi()
            fiat, btc = fetch_balances()
            print(f"[{now}] RSI: {rsi} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

            # === SELL LOGIC ===
            for level, pct in SELL_LADDER:
                if rsi >= level and btc > 0:
                    place_sell_order(pct)

            # === BUY LOGIC ===
            if fiat > 0:
                if rsi <= MIN_BUY_RSI:
                    print("🚨 EXTREME DIP: RSI ≤ 27 — BUYING FULL FIAT")
                    place_buy_order(1.0)
                    last_buy_rsi = rsi

                elif rsi < last_buy_rsi:
                    for level, pct in BUY_LADDER:
                        if rsi <= level:
                            print(f"✅ RSI {rsi} hit buy ladder level {level} — buying {pct*100:.0f}% of fiat")
                            place_buy_order(pct)
                            last_buy_rsi = rsi
                            break

            # === RESET FLAG ===
            if rsi > REBUY_RSI_THRESHOLD:
                last_buy_rsi = 100

            time.sleep(60)  # Check every 60 seconds

        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(60)

# === START BOT ===
if __name__ == "__main__":
    execute_strategy()
