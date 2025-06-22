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
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # 100% fiat at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
MIN_RSI_FOR_MANUAL = 27

# === STATE TRACKERS ===
last_buy_rsi = 100
already_sold = set()

# === KRAKEN INITIALIZATION ===
k = krakenex.API(key=API_KEY, secret=API_SECRET)
kraken = KrakenAPI(k)

def get_rsi():
    ohlc = k.query_public('OHLC', {'pair': PAIR, 'interval': TIMEFRAME})['result']
    pair_key = next(iter(ohlc))
    candles = ohlc[pair_key]
    df = pd.DataFrame(candles, columns=['time','open','high','low','close','vwap','volume','count'])
    df['close'] = pd.to_numeric(df['close'])
    rsi = RSIIndicator(df['close'], window=14).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    balances = kraken.get_account_balance()
    fiat = float(balances[QUOTE]) if QUOTE in balances else 0.0
    btc = float(balances[ASSET]) if ASSET in balances else 0.0
    return fiat, btc

def get_price():
    ticker = k.query_public('Ticker', {'pair': PAIR})['result']
    price = float(list(ticker.values())[0]['c'][0])
    return price

def buy_btc(amount_usd):
    print(f"[BUY] Buying ${amount_usd:.2f} worth of BTC")
    price = get_price()
    volume = round(amount_usd / price, 8)
    k.query_private('AddOrder', {
        'pair': PAIR,
        'type': 'buy',
        'ordertype': 'market',
        'volume': str(volume)
    })

def sell_btc(percent):
    fiat, btc = get_balances()
    sell_amt = round(btc * percent, 8)
    if sell_amt > 0:
        print(f"[SELL] Selling {percent*100:.0f}% = {sell_amt} BTC")
        k.query_private('AddOrder', {
            'pair': PAIR,
            'type': 'sell',
            'ordertype': 'market',
            'volume': str(sell_amt)
        })

def run_bot():
    global last_buy_rsi
    while True:
        try:
            rsi = get_rsi()
            fiat, btc = get_balances()
            now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now}] RSI: {rsi}, USD: {fiat:.2f}, BTC: {btc:.6f}")

            # === BUY LOGIC ===
            if rsi <= MIN_RSI_FOR_MANUAL and fiat > 0:
                print("[EMERGENCY BUY] RSI <= 27 – Buying ALL fiat!")
                buy_btc(fiat)

            elif rsi <= REBUY_RSI_THRESHOLD and rsi < last_buy_rsi:
                for level, portion in BUY_LADDER:
                    if rsi <= level and fiat > 0:
                        allocation = fiat * portion if level != 32 else fiat
                        print(f"[BUY] RSI ≤ {level} – Executing buy for ${allocation:.2f}")
                        buy_btc(allocation)
                        last_buy_rsi = rsi
                        break

            # === SELL LOGIC ===
            for level, portion in SELL_LADDER:
                if rsi >= level and level not in already_sold:
                    sell_btc(portion)
                    already_sold.add(level)

            # Reset sell ladder
            if rsi <= REBUY_RSI_THRESHOLD:
                already_sold.clear()

        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(60)  # Run every 1 minute

if __name__ == "__main__":
    run_bot()
