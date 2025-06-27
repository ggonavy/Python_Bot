import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import time
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
import pandas as pd
import logging

# --- CONFIGURE YOUR API KEYS HERE ---
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"      # <-- Paste your Kraken API key
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="  # <-- Paste your Kraken API secret

# --- INITIALIZE API ---
api = krakenex.API()
api.key = API_KEY
api.secret = API_SECRET
k = KrakenAPI(api)

# --- SETTINGS ---
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEZONE = 'US/Eastern'

# --- STRATEGY PARAMETERS ---
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47

# --- INITIAL BALANCE TRACKING ---
initial_fiat_total = 100
bought_levels = set()
sold_levels = set()

# --- FUNCTIONS ---

def get_rsi():
    try:
        ohlc, _ = k.get_ohlc_data(PAIR, interval=1)
        close_prices = ohlc['close']
        rsi = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
        return round(rsi, 2)
    except Exception as e:
        print(f"RSI fetch error: {e}")
        return None

def get_balances():
    try:
        balances = k.get_account_balance()
        fiat = float(balances.get(QUOTE, 0))
        btc = float(balances.get(ASSET, 0))
        return fiat, btc
    except Exception as e:
        print(f"Balance fetch error: {e}")
        return 0, 0

def execute_trade(order_type, volume, is_quote=False):
    try:
        params = {
            'pair': PAIR,
            'type': order_type,
            'ordertype': 'market',
            'volume': str(volume)
        }
        if is_quote and order_type == 'buy':
            params['oflags'] = 'viqc'
        response = k.query_private('AddOrder', params)
        if response.get('error'):
            print(f"Trade error: {response['error']}")
        else:
            print(f"Trade executed: {order_type} {volume} {'USD' if is_quote else 'BTC'}")
    except Exception as e:
        print(f"Trade exception: {e}")

# --- MAIN LOOP ---

print("Starting trading bot...")

while True:
    try:
        # Fetch current balances
        fiat, btc = get_balances()
        # Fetch RSI
        rsi = get_rsi()
        now = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] RSI: {rsi} | FIAT: ${fiat:.2f} | BTC: {btc:.8f}")

        if rsi is None:
            print("RSI fetch failed, retrying...")
            time.sleep(20)
            continue

        # --- BUY LOGIC ---
        if fiat > 1:
            if rsi <= REBUY_RSI_THRESHOLD:
                # Buy all fiat
                print(f"RSI {rsi} <= {REBUY_RSI_THRESHOLD} - Buying all fiat ${fiat:.2f}")
                execute_trade('buy', fiat, is_quote=True)
                bought_levels.clear()
            else:
                for level, percent in BUY_LADDER:
                    if rsi <= level and level not in bought_levels:
                        # Calculate BTC to buy
                        ticker = k.get_ticker(PAIR)
                        current_price = float(ticker['last'])
                        amount_btc = (fiat * percent) / current_price
                        print(f"Buying {amount_btc:.8f} BTC at {current_price} for RSI {rsi} at level {level}")
                        execute_trade('buy', amount_btc)
                        bought_levels.add(level)
                        break

        # --- SELL LOGIC ---
        if btc > 0.0001:
            for level, percent in SELL_LADDER:
                if rsi >= level and level not in sold_levels:
                    amount_btc = btc * percent
                    print(f"Selling {amount_btc:.8f} BTC at RSI {rsi} at level {level}")
                    execute_trade('sell', amount_btc)
                    sold_levels.add(level)
                    break
            # Sell all if RSI >= 85
            if rsi >= 85 and 'ALL' not in sold_levels:
                print(f"RSI {rsi} >= 85 - Selling all remaining BTC {btc:.8f}")
                execute_trade('sell', btc)
                sold_levels.add('ALL')

        # Reset levels if RSI drops below threshold
        if rsi < REBUY_RSI_THRESHOLD:
            if bought_levels or sold_levels:
                print("RSI below threshold, resetting levels.")
            bought_levels.clear()
            sold_levels.clear()

        time.sleep(20)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
