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
last_buy_rsi = 100

# === CONNECT TO KRAKEN ===
k = krakenex.API(key=API_KEY, secret=API_SECRET)
api = KrakenAPI(k)

def get_ohlcv():
    try:
        ohlc, _ = api.get_ohlc_data(PAIR, interval=TIMEFRAME)
        return ohlc
    except Exception as e:
        print(f"[Error] Failed to fetch OHLCV: {e}")
        return None

def get_rsi(ohlcv):
    close_prices = ohlcv['close']
    rsi = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    try:
        balances = k.query_private('Balance')['result']
        fiat = float(balances.get(QUOTE, 0))
        btc = float(balances.get(ASSET, 0))
        return fiat, btc
    except Exception as e:
        print(f"[Error] Failed to fetch balances: {e}")
        return 0, 0

def place_order(order_type, volume):
    try:
        print(f"[Placing {order_type}] Volume: {volume}")
        response = k.query_private('AddOrder', {
            'pair': PAIR,
            'type': order_type,
            'ordertype': 'market',
            'volume': volume
        })
        print(f"[Order Response] {response}")
    except Exception as e:
        print(f"[Error] Order failed: {e}")

def run_bot():
    global last_buy_rsi
    while True:
        now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n=== {now} ===")
        ohlcv = get_ohlcv()
        if ohlcv is None or ohlcv.empty:
            print("No OHLCV data pulled.")
            time.sleep(30)
            continue

        try:
            rsi = get_rsi(ohlcv)
            fiat, btc = get_balances()
            print(f"RSI: {rsi} | Fiat: {fiat:.2f} | BTC: {btc:.6f}")

            # === BUY LOGIC ===
            if rsi <= REBUY_RSI_THRESHOLD:
                last_buy_rsi = 100  # Reset after cooldown

            if rsi <= last_buy_rsi:
                for threshold, portion in BUY_LADDER:
                    if rsi <= threshold and fiat > 10:
                        if threshold == 32:
                            portion = 1.0  # Use 100% fiat
                        buy_usd = fiat * portion
                        btc_price = ohlcv['close'].iloc[-1]
                        volume = round(buy_usd / btc_price, 6)
                        print(f"Triggering BUY at RSI {rsi} for ${buy_usd:.2f}")
                        place_order('buy', volume)
                        last_buy_rsi = rsi
                        break

            # === SELL LOGIC ===
            for threshold, portion in SELL_LADDER:
                if rsi >= threshold and btc > 0.0001:
                    sell_volume = btc * portion
                    print(f"Triggering SELL at RSI {rsi} for {
