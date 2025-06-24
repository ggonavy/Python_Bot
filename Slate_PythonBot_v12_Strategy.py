
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
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
MIN_RSI_OVERRIDE = 27

# === STATE TRACKING ===
last_buy_rsi = 100

# === CONNECT TO KRAKEN ===
k = krakenex.API(API_KEY, API_SECRET)
api = KrakenAPI(k)

def fetch_ohlcv():
    df, _ = api.get_ohlc_data(PAIR, interval=TIMEFRAME)
    df = df.tz_convert(TIMEZONE)
    return df

def get_rsi(df):
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    return rsi.iloc[-1]

def get_balances():
    balances = api.get_account_balance()
    fiat = float(balances.get(QUOTE, 0))
    btc = float(balances.get(ASSET, 0))
    return fiat, btc

def execute_buy(percent, fiat_balance):
    if fiat_balance <= 0:
        return
    amount_to_spend = fiat_balance * percent
    price = float(api.get_ticker_information(PAIR).loc[PAIR]['c'][0])
    volume = round(amount_to_spend / price, 6)
    api.add_standard_order(PAIR, 'buy', 'market', volume)
    print(f"[{datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')}] ✅ BUY ${amount_to_spend:.2f} at ${price:.2f} ({volume} BTC)")

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
        current_rsi = get_rsi(df)
        fiat_balance, btc_balance = get_balances()

        print(f"\n--- {datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')} ---")
        print(f"RSI: {current_rsi:.2f} | Fiat: ${fiat_balance:.2f} | BTC: {btc_balance:.6f}")

        # === BUY LOGIC ===
        if current_rsi <= last_buy_rsi and fiat_balance > 5:
            for rsi_threshold, percent in BUY_LADDER:
                if current_rsi <= rsi_threshold:
                    if current_rsi <= 32:
                        percent = 1.00  # Override to use 100% fiat
                    print(f"Triggering BUY at RSI {current_rsi:.2f} for {percent * 100:.0f}% of fiat")
                    execute_buy(percent, fiat_balance)
                    last_buy_rsi = current_rsi
                    break

        # === EXTREME DIP OVERRIDE ===
        if current_rsi <= MIN_RSI_OVERRIDE and fiat_balance > 5:
            print("⚠️ RSI extremely low. FORCING full fiat deployment.")
            execute_buy(1.0, fiat_balance)

        # === SELL LOGIC ===
        if current_rsi >= 73 and btc_balance > 0.0001:
            for rsi_threshold, percent in SELL_LADDER:
                if current_rsi >= rsi_threshold:
                    print(f"Triggering SELL at RSI {current_rsi:.2f} for {percent * 100:.0f}% of BTC")
                    execute_sell(percent, btc_balance)
                    break

        # === RESET REBUY POINT ===
        if current_rsi > REBUY_RSI_THRESHOLD:
            last_buy_rsi = 100

    except Exception as e:
        print(f"❌ Error: {e}")
