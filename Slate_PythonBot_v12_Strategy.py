
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
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # 100% fiat at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
last_buy_rsi = 100

# === KRAKEN CONNECTION ===
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def get_rsi():
    ohlc, _ = k.get_ohlc_data(PAIR, interval=60)
    close_prices = ohlc['close']
    rsi = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    try:
        balances = k.get_account_balance()
        fiat = float(balances.get(QUOTE, 0))
        btc = float(balances.get(ASSET, 0))
        return fiat, btc
    except:
        return 0.0, 0.0

def execute_trade(order_type, volume):
    try:
        api.query_private('AddOrder', {
            'pair': PAIR,
            'type': order_type,
            'ordertype': 'market',
            'volume': str(volume)
        })
    except Exception as e:
        print(f"Trade Error: {e}")

print("Running SlateBot v12...")

while True:
    try:
        rsi = get_rsi()
        fiat, btc = get_balances()
        now = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] RSI: {rsi} | FIAT: {fiat:.2f} | BTC: {btc:.6f}")

        # === BUY LOGIC ===
        if fiat > 0:
            if rsi <= 32:
                amount = fiat
                print(f"Buying aggressively with all fiat: {amount}")
                execute_trade('buy', amount / rsi)
                last_buy_rsi = rsi
            else:
                for level, percent in BUY_LADDER:
                    if rsi <= level and rsi < last_buy_rsi:
                        amount = fiat * percent
                        print(f"Buying at RSI {rsi}: ${amount:.2f}")
                        execute_trade('buy', amount / rsi)
                        last_buy_rsi = rsi
                        break

        # === SELL LOGIC ===
        if btc > 0:
            for level, percent in SELL_LADDER:
                if rsi >= level:
                    amount = btc * percent
                    print(f"Selling {amount:.6f} BTC at RSI {rsi}")
                    execute_trade('sell', amount)
                    break

        time.sleep(1)  # 1-second interval to stay under Kraken API limits
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
