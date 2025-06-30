import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import time
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator

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
initial_fiat = 100      # Set your initial fiat amount (e.g., USD)
initial_btc = 10        # Set your initial BTC amount

# --- Variables ---
bought_levels = set()
sold_levels = set()
can_buy = True
sold_all_btc = False  # Flag to indicate all BTC sold

# --- Helper functions ---
def get_rsi():
    try:
        ohlc, _ = k.get_ohlc_data(PAIR, interval=1)
        close_prices = ohlc['close'].astype(float)
        from ta.momentum import RSIIndicator
        rsi_value = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
        return round(rsi_value, 2)
    except Exception as e:
        print(f"Error calculating RSI: {e}")
        return None

def get_balances():
    df = k.get_account_balance()
    fiat = float(df.loc['ZUSD']['vol']) if 'ZUSD' in df.index else 0
    btc = float(df.loc['XXBT']['vol']) if 'XXBT' in df.index else 0
    return fiat, btc

def get_price():
    try:
        ticker_df = k.get_ticker_info(PAIR)
        last_price = float(ticker_df['c'][0])  # 'c' is last trade price
        return last_price
    except Exception as e:
        print(f"Error fetching price: {e}")
        return None

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

        if current_price is None:
            time.sleep(20)
            continue

        print(f"[{now}] RSI: {rsi} | Fiat: ${fiat:.2f} | BTC: {btc:.8f}")

        # --- Reset after selling all BTC ---
        if btc < 0.0001 and not sold_all_btc:
            # Sold all BTC; reset flags and levels
            sold_all_btc = True
            bought_levels.clear()
            sold_levels.clear()
            can_buy = True
            print("All BTC sold. Resetting levels. Waiting for RSI 42 to rebuy.")

        # --- Rebuy only at RSI 42 after full sale ---
        if btc < 0.0001 and sold_all_btc:
            if rsi is not None and rsi >= 42:
                # Rebuy with full initial fiat
                amount_btc = initial_fiat / current_price
                print(f"RSI {rsi} >= 42 - Rebuying with full initial fiat ${initial_fiat} ({amount_btc:.8f} BTC)")
                execute_trade('buy', amount_btc)
                sold_all_btc = False
                bought_levels.clear()
                sold_levels.clear()
                can_buy = False  # Prevent buying again until RSI drops below 42

        # --- Buying logic ---
        if btc < 0.0001 and rsi is not None:
            # Only buy at RSI 42 or 36 or ≤30
            if rsi >= 42:
                # Rebuy handled above
                pass
            elif rsi == 42 and '42' not in bought_levels:
                dollar_amount = initial_fiat * 0.30
                amount_btc = dollar_amount / current_price
                print(f"RSI {rsi} = 42 - Buying 30% of initial fiat: ${dollar_amount} ({amount_btc:.8f} BTC)")
                execute_trade('buy', amount_btc)
                bought_levels.add('42')
            elif rsi == 36 and '36' not in bought_levels:
                dollar_amount = initial_fiat * 0.30
                amount_btc = dollar_amount / current_price
                print(f"RSI {rsi} = 36 - Buying 30% of initial fiat: ${dollar_amount} ({amount_btc:.8f} BTC)")
                execute_trade('buy', amount_btc)
                bought_levels.add('36')
            elif rsi <= 30:
                # Buy all remaining fiat
                dollar_amount = fiat
                amount_btc = dollar_amount / current_price
                print(f"RSI {rsi} <= 30 - Buying all remaining fiat ${dollar_amount} ({amount_btc:.8f} BTC)")
                execute_trade('buy', amount_btc)
                bought_levels.clear()  # Reset levels after full buy
                can_buy = False

        # --- Selling logic ---
        if btc >= 0.0001:
            # At RSI 69: sell 40% of initial BTC
            if rsi >= 69 and '69' not in sold_levels:
                btc_to_sell = initial_btc * 0.40
                btc_to_sell = min(btc_to_sell, btc)
                print(f"RSI {rsi} >= 69 - Selling 40% of initial BTC: {btc_to_sell:.8f}")
                execute_trade('sell', btc_to_sell)
                sold_levels.add('69')
            # At RSI 73: sell 30% of initial BTC
            if rsi >= 73 and '73' not in sold_levels:
                btc_to_sell = initial_btc * 0.30
                btc_to_sell = min(btc_to_sell, btc)
                print(f"RSI {rsi} >= 73 - Selling 30% of initial BTC: {btc_to_sell:.8f}")
                execute_trade('sell', btc_to_sell)
                sold_levels.add('73')
            # At RSI >= 79: sell all BTC
            if rsi >= 79 and 'ALL' not in sold_levels:
                print(f"RSI {rsi} >= 79 - Selling all remaining BTC: {btc:.8f}")
                execute_trade('sell', btc)
                sold_levels.add('ALL')

        time.sleep(20)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
