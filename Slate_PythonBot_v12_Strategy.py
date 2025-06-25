import time
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
import pandas as pd

# === CONFIGURATION ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]  # RSI thresholds and % of total fiat
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]  # RSI thresholds and % of BTC
REBUY_RSI_THRESHOLD = 47

# === INITIALIZE ===
initial_fiat_total = 100  # Your total fiat amount
last_buy_rsi = 100
bought_levels = set()
sold_levels = set()

# Setup Kraken API
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def get_rsi():
    ohlc, _ = k.get_ohlc_data(PAIR, interval=1)  # 1-minute interval for better RSI calculation
    close_prices = ohlc['close']
    rsi = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    balances = k.get_account_balance()
    fiat = float(balances.get(QUOTE, 0))
    btc = float(balances.get(ASSET, 0))
    return fiat, btc

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
        k.query_private('AddOrder', params)
        print(f"Placed {order_type} order for {volume:.8f} {'USD' if is_quote else 'BTC'}")
    except Exception as e:
        print(f"Trade Error: {e}")

print("Starting trading bot...")

while True:
    try:
        rsi = get_rsi()
        fiat, btc = get_balances()
        now = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] RSI: {rsi} | FIAT: ${fiat:.2f} | BTC: {btc:.8f}")

        # === BUY LOGIC ===
        if fiat > 0:
            if rsi <= REBUY_RSI_THRESHOLD:
                # Buy all remaining fiat
                print(f"RSI {rsi} <= {REBUY_RSI_THRESHOLD}: Buying all remaining fiat: ${fiat:.2f}")
                execute_trade('buy', fiat, is_quote=True)
                bought_levels.clear()  # reset buy levels after big buy
                last_buy_rsi = rsi
            else:
                for level, percent in BUY_LADDER:
                    if rsi <= level and level not in bought_levels:
                        amount = initial_fiat_total * percent
                        print(f"Buying {percent*100:.0f}% of total fiat: ${amount:.2f} at RSI {rsi}")
                        execute_trade('buy', amount, is_quote=True)
                        bought_levels.add(level)
                        break

        # === SELL LOGIC ===
        if btc > 0:
            for level, percent in SELL_LADDER:
                if rsi >= level and level not in sold_levels:
                    amount = btc * percent
                    print(f"Selling {percent*100:.0f}% of BTC: {amount:.8f} at RSI {rsi}")
                    execute_trade('sell', amount)
                    sold_levels.add(level)
                    break
            # Special case: RSI >= 85, sell all remaining BTC
            if rsi >= 85 and 'ALL' not in sold_levels:
                amount = btc
                print(f"RSI {rsi} >= 85: Selling all remaining BTC: {amount:.8f}")
                execute_trade('sell', amount)
                sold_levels.add('ALL')

        # Reset buy/sell levels when RSI crosses back below 47
        if rsi < REBUY_RSI_THRESHOLD:
            bought_levels.clear()
            sold_levels.clear()

        # Wait 15 seconds before next check
        time.sleep(15)

    except Exception as e:
        print(f"Error: {e}")
        print("Waiting 30 seconds before retrying...")
        time.sleep(30)
