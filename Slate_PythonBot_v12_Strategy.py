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
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Buy 100% at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
MIN_RSI_FOR_MANUAL = 27  # Manual dip DCA only
REBUY_RSI_THRESHOLD = 47  # Reset ladder if RSI goes above this

# === KRAKEN SETUP ===
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
    print(f"🟢 BUY: {pct*100:.0f}% of ${fiat:.2f} = ${spend:.2f}")
    # Live order (optional):
    # price = float(k.get_ticker_information(PAIR)['a'][0])
    # volume = spend / price
    # k.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)

def place_sell_order(pct, btc):
    amount = btc * pct
    print(f"🔴 SELL: {pct*100:.0f}% of {btc:.6f} BTC = {amount:.6f} BTC")
    # Live order (optional):
    # k.add_standard_order(pair=PAIR, type='sell', ordertype='market', volume=amount)

# === MAIN LOOP ===
def main():
    last_buy_rsi = 100
    while True:
        try:
            df = get_ohlc()
            rsi = get_rsi(df)
            btc, fiat = get_balances()
            now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')

            print(f"{now} | RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

            # Manual-only deep dip
            if rsi <= MIN_RSI_FOR_MANUAL:
                print("⚠️ RSI below 27 — Manual DCA Zone")

            # Buy ladder
            elif rsi <= BUY_LADDER[0][0] and fiat > 0:
                for level, pct in BUY_LADDER:
                    if rsi <= level:
                        print(f"🟢 Buy Triggered at RSI {rsi:.2f}")
                        place_buy_order(pct, fiat)
                        last_buy_rsi = rsi
                        break

            # Sell ladder
            elif rsi >= SELL_LADDER[0][0] and btc > 0:
                for level, pct in SELL_LADDER:
                    if rsi >= level:
                        print(f"🔴 Sell Triggered at RSI {rsi:.2f}")
                        place_sell_order(pct, btc)
                        break

        except Exception as e:
            print(f"❌ Error: {e}")

        time.sleep(1)  # ← 1-second rapid scan

if __name__ == "__main__":
    print("🚀 SlateBot v12 Started — 1s RSI Ladder Mode")
    main()
