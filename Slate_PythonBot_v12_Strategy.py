import time
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
TIMEFRAME = 60  # 1 hour
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Last step uses 100%
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
MIN_RSI_FOR_BUY = 0  # Allow buying even under RSI 27

# === CONNECT TO KRAKEN ===
k = krakenex.API(key=API_KEY, secret=API_SECRET)
api = KrakenAPI(k)

# === TRACKER ===
last_buy_rsi = 100

def get_ohlc():
    df, _ = api.get_ohlc_data(PAIR, interval=TIMEFRAME)
    df = df.tz_convert(TIMEZONE)
    return df

def get_latest_rsi(df):
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    return rsi.iloc[-1]

def get_balance(asset):
    balances = api.get_account_balance()
    return float(balances.loc[asset, 'vol']) if asset in balances.index else 0.0

def place_market_order(pair, volume, side):
    try:
        k.query_private('AddOrder', {
            'pair': pair,
            'type': side,
            'ordertype': 'market',
            'volume': str(volume)
        })
        print(f">>> Placed {side.upper()} order for {volume} BTC")
    except Exception as e:
        print(f"Order failed: {e}")

def get_price():
    try:
        price = float(k.get_ticker_information(PAIR)["c"][0])
        return price
    except Exception as e:
        print(f"Price fetch failed: {e}")
        return None

def main():
    global last_buy_rsi
    while True:
        try:
            df = get_ohlc()
            current_rsi = get_latest_rsi(df)
            price = get_price()
            fiat = get_balance(QUOTE)
            btc = get_balance(ASSET)

            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RSI: {current_rsi:.2f}, Price: {price}, Fiat: {fiat}, BTC: {btc}")

            # === BUY Logic ===
            if current_rsi <= REBUY_RSI_THRESHOLD and fiat > 10:
                for rsi_level, percent in BUY_LADDER:
                    if current_rsi <= rsi_level and fiat > 10:
                        buy_amount = (percent * fiat) / price
                        place_market_order(PAIR, buy_amount, 'buy')
                        last_buy_rsi = current_rsi
                        time.sleep(5)

            # === Continue buying below RSI 32 using all fiat
            if current_rsi <= 32 and fiat > 10:
                buy_amount = fiat / price
                place_market_order(PAIR, buy_amount, 'buy')
                last_buy_rsi = current_rsi
                time.sleep(5)

            # === SELL Logic ===
            for rsi_level, percent in SELL_LADDER:
                if current_rsi >= rsi_level and btc > 0.0001:
                    sell_amount = percent * btc
                    place_market_order(PAIR, sell_amount, 'sell')
                    time.sleep(5)

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(300)  # Check every 5 minutes

if __name__ == "__main__":
    main()
