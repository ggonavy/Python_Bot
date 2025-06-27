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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === YOUR API KEYS HERE ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"        # <-- Paste your Kraken API key here
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="  # <-- Paste your Kraken API secret here

# Initialize Kraken API
api = krakenex.API()
api.key = API_KEY
api.secret = API_SECRET
k = KrakenAPI(api)

# Configuration
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEZONE = 'US/Eastern'

# Strategy parameters
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]  # RSI thresholds and % of total fiat
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]  # RSI thresholds and % of BTC
REBUY_RSI_THRESHOLD = 47

# Initial balances and tracking
initial_fiat_total = 100
bought_levels = set()
sold_levels = set()

def get_rsi():
    try:
        ohlc, _ = k.get_ohlc_data(PAIR, interval=1)
        close_prices = ohlc['close']
        rsi_value = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
        return round(rsi_value, 2)
    except Exception as e:
        logging.error(f"Error fetching RSI: {e}")
        return None

def get_balances():
    try:
        balances = k.get_account_balance()
        fiat = float(balances.get(QUOTE, 0))
        btc = float(balances.get(ASSET, 0))
        return fiat, btc
    except Exception as e:
        logging.error(f"Error fetching balances: {e}")
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
            params['oflags'] = 'viqc'  # Volume in quote currency
        response = k.query_private('AddOrder', params)
        if response.get('error'):
            logging.error(f"Trade error: {response['error']}")
        else:
            logging.info(f"Successfully placed {order_type} order for {volume:.8f} {'USD' if is_quote else 'BTC'}")
    except Exception as e:
        logging.error(f"Exception during trade: {e}")

print("Starting trading bot...")

while True:
    try:
        rsi = get_rsi()
        fiat, btc = get_balances()
        now = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"[{now}] RSI: {rsi} | FIAT: ${fiat:.2f} | BTC: {btc:.8f}")

        if rsi is None:
            logging.warning("RSI fetch failed, skipping iteration.")
            time.sleep(20)
            continue

        # --- BUY LOGIC ---
        if fiat > 1:  # Prevent tiny orders
            if rsi <= REBUY_RSI_THRESHOLD:
                # Buy all remaining fiat
                logging.info(f"RSI {rsi} <= {REBUY_RSI_THRESHOLD}: Buying all fiat ${fiat:.2f}")
                execute_trade('buy', fiat, is_quote=True)
                bought_levels.clear()
                # After buying, update balances
                fiat, btc = get_balances()
            else:
                for level, percent in BUY_LADDER:
                    if rsi <= level and level not in bought_levels:
                        ticker = k.get_ticker(PAIR)
                        current_price = float(ticker['last'])
                        amount_btc = (fiat * percent) / current_price
                        logging.info(f"Buying {amount_btc:.8f} BTC at price {current_price} for RSI {rsi} at level {level}")
                        execute_trade('buy', amount_btc)
                        bought_levels.add(level)
                        break

        # --- SELL LOGIC ---
        if btc > 0.0001:
            for level, percent in SELL_LADDER:
                if rsi >= level and level not in sold_levels:
                    amount_btc = btc * percent
                    logging.info(f"Selling {amount_btc:.8f} BTC at RSI {rsi} at level {level}")
                    execute_trade('sell', amount_btc)
                    sold_levels.add(level)
                    break
            # Sell all remaining BTC if RSI >= 85
            if rsi >= 85 and 'ALL' not in sold_levels:
                logging.info(f"RSI {rsi} >= 85: Selling all remaining BTC {btc:.8f}")
                execute_trade('sell', btc)
                sold_levels.add('ALL')

        # Reset levels when RSI drops below threshold
        if rsi < REBUY_RSI_THRESHOLD:
            if bought_levels or sold_levels:
                logging.info("RSI dropped below threshold, resetting levels.")
            bought_levels.clear()
            sold_levels.clear()

        time.sleep(20)

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        time.sleep(30)
