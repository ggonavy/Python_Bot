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
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Full fiat at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]  # Full BTC out at RSI 85
REBUY_RSI_THRESHOLD = 47
MIN_RSI_FOR_MANUAL_BUY = 27  # Still allow buys at or below 27
last_buy_rsi = 100

# === KRAKEN SETUP ===
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def get_ohlc_data():
    df, _ = k.get_ohlc_data(PAIR, interval=60)  # 1H timeframe
    return df

def get_latest_rsi(df):
    df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
    return df['rsi'].iloc[-1]

def get_balance():
    balance = k.get_account_balance()
    fiat = float(balance.get(QUOTE, 0))
    btc = float(balance.get(ASSET, 0))
    return fiat, btc

def place_buy_order(pct, fiat):
    amount_usd = fiat * pct
    print(f"💰 Buying BTC with ${amount_usd:.2f}")
    # api.query_private('AddOrder', {...}) ← Live trade logic here

def place_sell_order(pct, btc):
    amount_btc = btc * pct
    print(f"🔻 Selling {amount_btc:.6f} BTC")
    # api.query_private('AddOrder', {...}) ← Live trade logic here

def main():
    global last_buy_rsi
    while True:
        try:
            df = get_ohlc_data()
            rsi = get_latest_rsi(df)
            fiat, btc = get_balance()

            now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{now} | RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

            # Buy logic
            if rsi <= REBUY_RSI_THRESHOLD and rsi < last_buy_rsi and fiat > 1:
                for level, pct in BUY_LADDER:
                    if rsi <= level:
                        print(f"✅ Buy Ladder Triggered at RSI {rsi:.2f}")
                        place_buy_order(pct, fiat)
                        last_buy_rsi = rsi
                        break

            # Manual buy override
            elif rsi <= MIN_RSI_FOR_MANUAL_BUY and fiat > 1:
                print(f"🚨 Deep RSI Manual Buy Override: RSI {rsi:.2f}")
                place_buy_order(1.0, fiat)
                last_buy_rsi = rsi

            # Sell logic
            elif rsi >= SELL_LADDER[0][0] and btc > 0:
                for level, pct in SELL_LADDER:
                    if rsi >= level:
                        print(f"📤 Sell Ladder Triggered at RSI {rsi:.2f}")
                        place_sell_order(pct, btc)
                        break

        except Exception as e:
            print(f"❌ Error: {e}")

        time.sleep(1)  # Check every second

if __name__ == "__main__":
    main()
