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
TIMEFRAME = 60  # 1 hour candles
CHECK_INTERVAL = 300  # check every 5 minutes
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
MIN_RSI_FOR_BUY = 27
REBUY_RSI_THRESHOLD = 47

BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

last_buy_rsi = 100  # reset value
bought_btc = 0.0

# === INIT API ===
api = krakenex.API(API_KEY, API_SECRET)
kraken = KrakenAPI(api)

def log(message):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {message}")

def fetch_rsi():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    res = requests.get(url, params=params).json()
    candles = list(res['result'].values())[0]
    df = pd.DataFrame(candles, columns=[
        "time", "open", "high", "low", "close", "vwap", "volume", "count"
    ])
    df['close'] = df['close'].astype(float)
    rsi = RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    balances = kraken.get_account_balance()
    usd = float(balances.get(QUOTE, 0.0))
    btc = float(balances.get(ASSET, 0.0))
    return usd, btc

def execute_market_order(pair, type_, volume):
    try:
        kraken.add_standard_order(pair=pair, type=type_, ordertype='market', volume=str(volume))
        log(f"Executed {type_} order for {volume} {ASSET}")
    except Exception as e:
        log(f"Order failed: {e}")

def main():
    global last_buy_rsi, bought_btc

    while True:
        try:
            rsi = fetch_rsi()
            usd_balance, btc_balance = get_balances()
            log(f"RSI: {rsi} | USD: {usd_balance:.2f} | BTC: {btc_balance:.6f}")

            # === SELL LADDER ===
            for level, percent in SELL_LADDER:
                if rsi >= level and btc_balance > 0:
                    sell_amount = btc_balance * percent
                    execute_market_order(PAIR, 'sell', round(sell_amount, 6))
                    btc_balance -= sell_amount

            # === BUY LADDER ===
            if rsi >= MIN_RSI_FOR_BUY:
                if last_buy_rsi > REBUY_RSI_THRESHOLD and rsi <= REBUY_RSI_THRESHOLD:
                    log("RSI reset, rebuy enabled.")

                if last_buy_rsi <= REBUY_RSI_THRESHOLD:
                    for level, percent in BUY_LADDER:
                        if rsi <= level and usd_balance > 0:
                            usd_to_use = usd_balance * percent
                            price_res = kraken.get_ticker_information(PAIR)
                            price = float(price_res[0]['c'][0])
                            volume = usd_to_use / price
                            execute_market_order(PAIR, 'buy', round(volume, 6))
                            usd_balance -= usd_to_use

            last_buy_rsi = rsi
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            log(f"Main loop error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
