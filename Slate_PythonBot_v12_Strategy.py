import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import time
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI

# --- CONFIG ---
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"        # Replace with your Kraken API key
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="  # Replace with your Kraken API secret
PAIR = "XBTUSD"
TIMEZONE = 'US/Eastern'

# --- SETUP ---
warnings.simplefilter(action='ignore', category=FutureWarning)
api = krakenex.API()
api.key = API_KEY
api.secret = API_SECRET
k = KrakenAPI(api)

# --- INITIAL TOTALS ---
initial_fiat = 100  # Set your initial fiat amount
initial_btc = 10    # Set your initial BTC amount

# --- Variables ---
bought_levels = set()
sold_levels = set()
can_buy = True
sold_all_btc = False  # Flag to know when we've sold all BTC

# --- Helper functions ---
def get_rsi():
    try:
        ohlc, _ = k.get_ohlc_data(PAIR, interval=1)
        close_prices = ohlc['close'].astype(float)
        from ta.momentum import RSIIndicator
        rsi_value = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
        return round(rsi_value, 2)
    except:
        return None

def get_balances():
    df = k.get_account_balance()
    fiat = float(df.loc[QUOTE]['vol']) if 'ZUSD' in df.index else 0
    btc = float(df.loc[ASSET]['vol']) if 'XXBT' in df.index else 0
    return fiat, btc

def get_price():
    ticker = k.get_ticker(PAIR)
    return float(ticker['c'][0])

def execute_trade(order_type, volume):
    try:
        response = k.query_private('AddOrder', {
            'pair': PAIR,
            'type': order_type,
            'ordertype': 'market',
            'volume': str(volume)
        })
        if response.get('error'):
            print(f"Trade error: {response['error']}")
        else:
            print(f"{order_type.capitalize()} {volume:.8f} BTC executed.")
    except Exception as e:
        print(f"Trade exception: {e}")

print("Trading bot started.")
while True:
    try:
        now = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        fiat, btc = get_balances()
        rsi = get_rsi()
        current_price = get_price()

        print(f"[{now}] RSI: {rsi} | Fiat: ${fiat:.2f} | BTC: {btc:.8f}")

        # --- Reset after selling all BTC ---
        if btc < 0.0001 and not sold_all_btc:
            # Sold all BTC, reset flags
            sold_all_btc = True
            bought_levels.clear()
            sold_levels.clear()
            can_buy = True
            print("All BTC sold. Resetting levels. Waiting for RSI 42 to rebuy.")

        # --- Buy logic ---
        if btc < 0.0001 and rsi is not None:
            # Only buy at RSI 42
            if rsi >= 42:
                # Rebuy only at RSI 42
                dollar_amount = initial_fiat
                amount_btc = dollar_amount / current_price
                print(f"RSI {rsi} >= 42 - Rebuying with full initial fiat ${dollar_amount} ({amount_btc:.8f} BTC)")
                execute_trade('buy', amount_btc)
                sold_all_btc = False  # Reset flag after rebuy
                bought_levels.clear()
                sold_levels.clear()
                can_buy = False

        if btc >= 0.0001:
            # --- Sell at RSI 69 ---
            if rsi >= 69 and '69' not in sold_levels:
                btc_to_sell = initial_btc * 0.40
                btc_to_sell = min(btc_to_sell, btc)
                print(f"RSI {rsi} >= 69 - Selling 40% of initial BTC: {btc_to_sell:.8f}")
                execute_trade('sell', btc_to_sell)
                sold_levels.add('69')

            # --- Sell at RSI 73 ---
            if rsi >= 73 and '73' not in sold_levels:
                btc_to_sell = initial_btc * 0.30
                btc_to_sell = min(btc_to_sell, btc)
                print(f"RSI {rsi} >= 73 - Selling 30% of initial BTC: {btc_to_sell:.8f}")
                execute_trade('sell', btc_to_sell)
                sold_levels.add('73')

            # --- Sell all at RSI >= 79 ---
            if rsi >= 79 and 'ALL' not in sold_levels:
                print(f"RSI {rsi} >= 79 - Selling all remaining BTC: {btc:.8f}")
                execute_trade('sell', btc)
                sold_levels.add('ALL')

        # --- Wait for RSI 42 to rebuy after full sell ---
        if btc < 0.0001 and sold_all_btc:
            # Wait until RSI >= 42 to rebuy
            if rsi is not None and rsi >= 42:
                # Rebuy logic handled above
                pass

        time.sleep(20)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
