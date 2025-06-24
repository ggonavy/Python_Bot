import time import pandas as pd from ta.momentum import RSIIndicator from datetime import datetime from pytz import timezone import krakenex from pykrakenapi import KrakenAPI

=== CONFIGURATION ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM" API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q==" PAIR = "XBTUSD" ASSET = "XXBT" QUOTE = "ZUSD" TIMEFRAME = 60 # 1-hour candles (Kraken uses minutes) TIMEZONE = 'US/Eastern'

=== STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)] SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)] REBUY_RSI_THRESHOLD = 47 MIN_RSI_FOR_BUY = 0 # allow full manual override at extreme dips

last_buy_rsi = 100 # Prevent re-buying until RSI drops below REBUY_RSI_THRESHOLD

def get_kraken_balance(api): balance = api.get_account_balance() fiat = float(balance.get(QUOTE, 0)) btc = float(balance.get(ASSET, 0)) return fiat, btc

def place_buy_order(pct, fiat): usd_to_spend = fiat * pct print(f"\n\U0001F7E2 Buy Order: Using {pct*100:.0f}% of fiat = ${usd_to_spend:.2f}") # Place actual order with Kraken API here (buy market)

def place_sell_order(pct, btc): btc_to_sell = btc * pct print(f"\n\U0001F534 Sell Order: Selling {pct*100:.0f}% of BTC = {btc_to_sell:.6f} BTC") # Place actual order with Kraken API here (sell market)

def get_rsi(): df, _ = k.get_ohlc_data(PAIR, interval=TIMEFRAME) df.index.freq = 'min' # Suppress 'T' frequency warning rsi = RSIIndicator(close=df['close'], window=14).rsi() return float(rsi.iloc[-1])

def main(): global last_buy_rsi api = krakenex.API(API_KEY, API_SECRET) global k k = KrakenAPI(api)

while True:
    try:
        est = timezone(TIMEZONE)
        now = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
        rsi = get_rsi()
        fiat, btc = get_kraken_balance(k)

        print(f"\n{now} | RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

        if rsi <= BUY_LADDER[-1][0] and fiat > 0:
            print(f"\U0001F4C9 RSI below {BUY_LADDER[-1][0]}: Full Deploy Mode")
            place_buy_order(1.00, fiat)
            last_buy_rsi = rsi

        elif rsi <= REBUY_RSI_THRESHOLD and rsi < last_buy_rsi and fiat > 0:
            for level, pct in reversed(BUY_LADDER):
                if rsi <= level:
                    print(f"\U0001F7E2 Buy Ladder Triggered at RSI {rsi:.2f}")
                    place_buy_order(pct, fiat)
                    last_buy_rsi = rsi
                    break

        elif rsi >= SELL_LADDER[0][0] and btc > 0:
            for level, pct in SELL_LADDER:
                if rsi >= level:
                    print(f"\U0001F534 Sell Ladder Triggered at RSI {rsi:.2f}")
                    place_sell_order(pct, btc)
                    break

    except Exception as e:
        print(f"\n\u274C Error: {e}")

    time.sleep(1)  # ⏱ Check every second
if name == "main": main()
