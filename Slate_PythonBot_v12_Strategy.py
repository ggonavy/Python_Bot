import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI

# === CONFIGURATION ===
API_KEY = "PASTE_YOUR_KRAKEN_API_KEY_HERE"
API_SECRET = "PASTE_YOUR_KRAKEN_SECRET_KEY_HERE"
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEFRAME = 60  # 1-hour candles
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

bought = False
last_rsi_buys = set()

# === CONNECT TO KRAKEN ===
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def log(msg):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

while True:
    try:
        # === FETCH DATA ===
        ohlc, _ = k.get_ohlc_data(PAIR, interval=TIMEFRAME)
        df = ohlc.tail(100).copy()
        df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
        current_rsi = df['rsi'].iloc[-1]
        current_price = df['close'].iloc[-1]
        fiat_balance = k.get_account_balance()[QUOTE]['vol']
        btc_balance = k.get_account_balance()[ASSET]['vol']

        log(f"RSI: {current_rsi:.2f} | Price: {current_price:.2f} | USD: {fiat_balance:.2f} | BTC: {btc_balance:.5f}")

        # === BUY LOGIC ===
        if float(current_rsi) <= 32:
            if float(current_rsi) <= 27:
                if float(fiat_balance) > 5:
                    volume = float(fiat_balance) / current_price
                    log(f"🔥 PANIC BUY @ RSI {current_rsi:.2f} — Using ALL ${fiat_balance:.2f} to buy BTC")
                    k.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)
                    bought = True
            else:
                if float(fiat_balance) > 5:
                    volume = float(fiat_balance) / current_price
                    log(f"⚡ RSI 32 Trigger — Buying FULL USD ${fiat_balance:.2f}")
                    k.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)
                    bought = True

        elif float(current_rsi) <= 47:
            for rsi_level, portion in BUY_LADDER:
                if float(current_rsi) <= rsi_level and rsi_level not in last_rsi_buys:
                    usd_to_spend = float(fiat_balance) * portion
                    if usd_to_spend > 5:
                        volume = usd_to_spend / current_price
                        log(f"✅ Ladder Buy @ RSI {current_rsi:.2f} ≤ {rsi_level} — Buying ${usd_to_spend:.2f}")
                        k.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)
                        last_rsi_buys.add(rsi_level)
                        bought = True
                    else:
                        log(f"💤 Not enough USD to buy @ RSI {rsi_level} (Only ${usd_to_spend:.2f})")
                    break

        # === SELL LOGIC ===
        if bought:
            for rsi_level, portion in SELL_LADDER:
                if float(current_rsi) >= rsi_level:
                    btc_to_sell = float(btc_balance) * portion
                    if btc_to_sell > 0.00001:
                        log(f"🔺 SELL @ RSI {current_rsi:.2f} ≥ {rsi_level} — Selling {btc_to_sell:.6f} BTC")
                        k.add_standard_order(pair=PAIR, type='sell', ordertype='market', volume=btc_to_sell)
                        last_rsi_buys.clear()
                        bought = False
                    else:
                        log(f"💤 Not enough BTC to sell @ RSI {rsi_level} ({btc_to_sell:.6f})")
                    break

        time.sleep(5)

    except Exception as e:
        log(f"⚠️ ERROR: {e}")
        time.sleep(10)
