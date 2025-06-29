import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import time
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator

# --- CONFIG ---
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"  # Replace with your Kraken API key
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="  # Replace with your Kraken API secret
PAIR = "XBTUSD"
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEZONE = 'US/Eastern'

# --- INIT API ---
api = krakenex.API()
api.key = API_KEY
api.secret = API_SECRET
k = KrakenAPI(api)

# --- STRATEGY PARAMETERS ---
initial_fiat_amount = 100
initial_total_btc = 10

BUY_RSI_THRESHOLD = 32
REBUY_RSI_THRESHOLD = 47
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]

# Pre-calculate levels for buy and sell
buy_levels_amounts = [(lvl, initial_fiat_amount * pct) for lvl, pct in BUY_LADDER]
sell_levels_btc = [(lvl, initial_total_btc * pct) for lvl, pct in SELL_LADDER]

bought_levels = set()
sold_levels = set()

def get_rsi():
    try:
        ohlc, _ = k.get_ohlc_data(PAIR, interval=1)
        close_prices = ohlc['close']
        rsi = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
        return round(rsi, 2)
    except Exception as e:
        print(f"Error fetching RSI: {e}")
        return None

def get_balances():
    try:
        bal = k.get_account_balance()
        # Debug print to see raw balance data
        print(f"Raw balance data: {bal}")
        fiat = float(bal.get(QUOTE, 0))
        btc = float(bal.get(ASSET, 0))
        # Debug print to verify fetched balances
        print(f"Fetched balances - Fiat: {fiat}, BTC: {btc}")
        return fiat, btc
    except Exception as e:
        print(f"Error fetching balances: {e}")
        return 0, 0

def get_price():
    try:
        # Correct method: get_ticker_information
        ticker_info = k.get_ticker_information(PAIR)
        # 'last' price is inside 'result' dict under the pair key
        last_price = float(ticker_info.result[PAIR]['c'][0])
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

        # Log current status
        print(f"[{now}] RSI: {rsi} | Fiat: ${fiat:.2f} | BTC: {btc:.8f}")

        # --- BUY LOGIC ---
        if fiat > 1 and rsi is not None:
            if rsi <= BUY_RSI_THRESHOLD:
                # Buy all fiat
                amount_btc = fiat / current_price
                print(f"RSI {rsi} <= {BUY_RSI_THRESHOLD} - Buying all fiat ${fiat:.2f} ({amount_btc:.8f} BTC)")
                execute_trade('buy', amount_btc)
                bought_levels.clear()
            elif rsi <= REBUY_RSI_THRESHOLD:
                for level, dollar_amount in buy_levels_amounts:
                    if rsi <= level and level not in bought_levels:
                        amount_btc = dollar_amount / current_price
                        print(f"Buying {amount_btc:.8f} BTC at {current_price} USD (Level {level})")
                        execute_trade('buy', amount_btc)
                        bought_levels.add(level)
                        break

        # --- SELL LOGIC ---
        if btc > 0.0001 and rsi is not None:
            for level, btc_amount in sell_levels_btc:
                if rsi >= level and level not in sold_levels:
                    print(f"Selling {btc_amount:.8f} BTC at RSI {rsi} (Level {level})")
                    execute_trade('sell', btc_amount)
                    sold_levels.add(level)
                    break
            # Sell all remaining BTC at RSI >= 85
            if rsi >= 85 and 'ALL' not in sold_levels:
                print(f"RSI {rsi} >= 85 - Selling all remaining BTC {btc:.8f}")
                execute_trade('sell', btc)
                sold_levels.add('ALL')

        # --- RESET LEVELS ---
        if rsi is not None and rsi < REBUY_RSI_THRESHOLD:
            if bought_levels or sold_levels:
                print("RSI below threshold, resetting levels.")
            bought_levels.clear()
            sold_levels.clear()

        time.sleep(20)

    except Exception as e:
        print(f"Error in main loop: {e}")
        time.sleep(30)
