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
TIMEFRAME = 60  # 1-hour candles
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Full buy at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
MIN_RSI_FOR_BUY = 27
last_buy_rsi = 100

# === INIT ===
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def get_rsi():
    ohlc, _ = k.get_ohlc_data(PAIR, interval=TIMEFRAME)
    close_prices = ohlc['close'].astype(float)
    rsi = RSIIndicator(close_prices).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    balance = k.get_account_balance()
    fiat = float(balance[QUOTE]) if QUOTE in balance else 0
    btc = float(balance[ASSET]) if ASSET in balance else 0
    return fiat, btc

def place_buy_order(pct, fiat):
    usd_amount = fiat * pct
    print(f"💰 Buy Order: {pct*100:.0f}% of ${fiat:.2f} = ${usd_amount:.2f}")
    # Uncomment for live trading:
    # k.add_standard_order(PAIR, type='buy', ordertype='market', volume=usd_amount / get_price())

def place_sell_order(pct, btc):
    btc_amount = btc * pct
    print(f"🔻 Sell Order: {pct*100:.0f}% of {btc:.6f} BTC = {btc_amount:.6f} BTC")
    # Uncomment for live trading:
    # k.add_standard_order(PAIR, type='sell', ordertype='market', volume=btc_amount)

def main():
    global last_buy_rsi
    while True:
        try:
            rsi = get_rsi()
            fiat, btc = get_balances()
            now = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{now} | RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

            # === BUY CONDITIONS ===
            if rsi <= BUY_LADDER[-1][0] and fiat > 0:
                print(f"🟢 RSI {rsi:.2f} <= {BUY_LADDER[-1][0]} → Full Buy")
                place_buy_order(1.0, fiat)
                last_buy_rsi = rsi
            elif rsi <= REBUY_RSI_THRESHOLD and rsi < last_buy_rsi and fiat > 0:
                for level, pct in BUY_LADDER:
                    if rsi <= level:
                        print(f"🪙 Buy Triggered at RSI {rsi:.2f}")
                        place_buy_order(pct, fiat)
                        last_buy_rsi = rsi
                        break

            # === SELL CONDITIONS ===
            elif rsi >= SELL_LADDER[0][0] and btc > 0:
                for level, pct in SELL_LADDER:
                    if rsi >= level:
                        print(f"📉 Sell Triggered at RSI {rsi:.2f}")
                        place_sell_order(pct, btc)
                        break

        except Exception as e:
            print(f"❌ Error: {e}")

        time.sleep(1)  # Runs every second (No sleep mode)

if __name__ == "__main__":
    main()
