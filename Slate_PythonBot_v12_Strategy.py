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
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
MIN_RSI_FOR_MANUAL = 27

# === KRAKEN CONNECTION ===
kraken = krakenex.API(key=API_KEY, secret=API_SECRET)
k = KrakenAPI(kraken)

# === FUNCTIONS ===
def get_ohlc():
    df, _ = k.get_ohlc_data(PAIR, interval=60)
    df = df.tz_localize(None)
    return df

def get_rsi(df):
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    return rsi.iloc[-1]

def get_balances():
    balances = k.get_account_balance()
    btc = float(balances.get(ASSET, 0))
    fiat = float(balances.get(QUOTE, 0))
    return btc, fiat

def place_buy_order(pct, fiat):
    spend = fiat * pct
    print(f"🟢 BUY Order: Using {pct*100:.0f}% = ${spend:.2f}")
    # Uncomment to execute live:
    # price = k.get_ticker_information(PAIR).ask[0]
    # volume = spend / price
    # k.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)

def place_sell_order(pct, btc):
    amount = btc * pct
    print(f"🔴 SELL Order: Selling {pct*100:.0f}% = {amount:.6f} BTC")
    # Uncomment to execute live:
    # k.add_standard_order(pair=PAIR, type='sell', ordertype='market', volume=amount)

# === MAIN LOOP ===
def main():
    last_buy_rsi = 100
    while True:
        try:
            df = get_ohlc()
            rsi = get_rsi(df)
            btc, fiat = get_balances()

            eastern = timezone(TIMEZONE)
            now = datetime.now(eastern).strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{now} | RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

            if rsi <= MIN_RSI_FOR_MANUAL:
                print(f"⚠️ RSI below {MIN_RSI_FOR_MANUAL} — manual buy zone")

            elif rsi <= BUY_LADDER[0][0] and fiat > 0:
                for level, pct in BUY_LADDER:
                    if rsi <= level:
                        print(f"🟢 Buy Ladder Triggered at RSI {rsi:.2f}")
                        place_buy_order(pct, fiat)
                        last_buy_rsi = rsi
                        break

            elif rsi >= SELL_LADDER[0][0] and btc > 0:
                for level, pct in SELL_LADDER:
                    if rsi >= level:
                        print(f"🔴 Sell Ladder Triggered at RSI {rsi:.2f}")
                        place_sell_order(pct, btc)
                        break

        except Exception as e:
            print(f"❌ Error: {e}")

        time.sleep(1)  # 1-second interval

if __name__ == "__main__":
    print("🔁 SlateBot v12 live. No sleep. Constant RSI scan.")
    main()
