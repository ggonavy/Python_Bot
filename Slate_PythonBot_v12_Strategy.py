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
TIMEFRAME = 60  # 1H candles
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
MIN_RSI_OVERRIDE = 27

# === STATE TRACKING ===
last_buy_rsi = 100

# === KRAKEN CONNECTION ===
k = krakenex.API(API_KEY, API_SECRET)
api = KrakenAPI(k)

def fetch_ohlcv():
    df, _ = api.get_ohlc_data(PAIR, interval=TIMEFRAME)
    try:
        df.index = df.index.tz_localize(TIMEZONE)
    except TypeError:
        df.index = df.index.tz_convert(TIMEZONE)
    df.index.freq = None  # Fix FutureWarning: 'T' deprecated
    return df

def get_rsi(df):
    return RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]

def get_balances():
    balances = api.get_account_balance()
    fiat = float(balances.get(QUOTE, 0))
    btc = float(balances.get(ASSET, 0))
    return fiat, btc

def execute_buy(percent, fiat_balance):
    if fiat_balance <= 0:
        return
    amount = fiat_balance * percent
    price = float(api.get_ticker_information(PAIR).loc[PAIR]['c'][0])
    volume = round(amount / price, 6)
    api.add_standard_order(PAIR, 'buy', 'market', volume)
    print(f"[{datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')}] ✅ BUY ${amount:.2f} at ${price:.2f} ({volume} BTC)")

def execute_sell(percent, btc_balance):
    if btc_balance <= 0:
        return
    volume = round(btc_balance * percent, 6)
    price = float(api.get_ticker_information(PAIR).loc[PAIR]['c'][0])
    api.add_standard_order(PAIR, 'sell', 'market', volume)
    print(f"[{datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')}] 🔻 SELL {volume} BTC at ${price:.2f}")

# === MAIN LOOP ===
while True:
    try:
        df = fetch_ohlcv()
        rsi = get_rsi(df)
        fiat, btc = get_balances()

        print(f"\n--- {datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')} ---")
        print(f"RSI: {rsi:.2f} | Fiat: ${fiat:.2f} | BTC: {btc:.6f}")

        # === BUY LOGIC ===
        if rsi <= last_buy_rsi and fiat > 5:
            for level, pct in BUY_LADDER:
                if rsi <= level:
                    if rsi <= 32:
                        pct = 1.00
                    print(f"Triggering BUY at RSI {rsi:.2f} for {pct * 100:.0f}% of fiat")
                    execute_buy(pct, fiat)
                    last_buy_rsi = rsi
                    break

        # === EXTREME DIP BUY ===
        if rsi <= MIN_RSI_OVERRIDE and fiat > 5:
            print("⚠️ RSI extremely low. FORCING full fiat deployment.")
            execute_buy(1.0, fiat)

        # === SELL LOGIC ===
        if rsi >= 73 and btc > 0.0001:
            for level, pct in SELL_LADDER:
                if rsi >= level:
                    print(f"Triggering SELL at RSI {rsi:.2f} for {pct * 100:.0f}% of BTC")
                    execute_sell(pct, btc)
                    break

        # === RESET POINT ===
        if rsi > REBUY_RSI_THRESHOLD:
            last_buy_rsi = 100

    except Exception as e:
        print(f"❌ Error: {e}")

    time.sleep(5)  # Kraken-safe
