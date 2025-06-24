
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
TIMEFRAME = 60  # 1-hour candles
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Full deploy at 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]  # Full sell by 85
REBUY_RSI_THRESHOLD = 47
MIN_RSI_FOR_BUY = 27
last_buy_rsi = 100

# === KRAKEN SETUP ===
k = krakenex.API(API_KEY, API_SECRET)
kraken = KrakenAPI(k)

def get_rsi():
    ohlc, _ = kraken.get_ohlc_data(PAIR, interval=TIMEFRAME)
    ohlc.index.freq = 'min'  # Updated to avoid future warnings
    close_prices = ohlc['close']
    rsi = RSIIndicator(close_prices, window=14).rsi().iloc[-1]
    return rsi

def get_balances():
    balance = kraken.get_account_balance()
    fiat = float(balance.get(QUOTE, 0))
    btc = float(balance.get(ASSET, 0))
    return fiat, btc

def place_buy_order(percent, fiat_balance):
    amount_to_spend = fiat_balance * percent
    price = float(kraken.get_ticker_information(PAIR)['c'][0][0])
    volume = round(amount_to_spend / price, 8)
    kraken.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)

def place_sell_order(percent, btc_balance):
    volume = round(btc_balance * percent, 8)
    kraken.add_standard_order(pair=PAIR, type='sell', ordertype='market', volume=volume)

def main():
    global last_buy_rsi
    while True:
        try:
            rsi = get_rsi()
            fiat, btc = get_balances()

            print(f"RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.8f}")

            if rsi <= MIN_RSI_FOR_BUY and fiat > 0:
                print("🔥 RSI crashed — full manual buy mode below 27")
                place_buy_order(1.0, fiat)

            elif rsi <= REBUY_RSI_THRESHOLD and fiat > 0:
                for level, pct in BUY_LADDER:
                    if rsi <= level:
                        print(f"✅ Buy Ladder Triggered at RSI {rsi:.2f}")
                        place_buy_order(pct, fiat)
                        last_buy_rsi = rsi
                        break

            elif rsi >= SELL_LADDER[0][0] and btc > 0:
                for level, pct in SELL_LADDER:
                    if rsi >= level:
                        print(f"📈 Sell Ladder Triggered at RSI {rsi:.2f}")
                        place_sell_order(pct, btc)
                        break

        except Exception as e:
            print(f"❌ Error: {e}")

        time.sleep(3600)  # 1 hour interval

if __name__ == "__main__":
    main()
