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
PAIR = "XXBTZUSD"       # ✅ Correct Kraken OHLC pair for BTC/USD
ASSET = "XXBT"
QUOTE = "ZUSD"
TIMEFRAME = 60          # 1H candles
TIMEZONE = 'US/Eastern'

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]  # Full buy at RSI 32
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)] # Sell 100% as we climb
REBUY_RSI_THRESHOLD = 47
last_buy_rsi = 100  # Start with a neutral state

# === INIT KRAKEN ===
kraken = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(kraken)

def fetch_latest_rsi():
    url = f"https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()

    if not data['error']:
        ohlc_key = list(data['result'].keys())[0]
        ohlc_data = data['result'][ohlc_key]
        df = pd.DataFrame(ohlc_data, columns=["time","open","high","low","close","vwap","volume","count"])
        df["close"] = pd.to_numeric(df["close"])
        rsi = RSIIndicator(df["close"], window=14).rsi().iloc[-1]
        return round(rsi, 2)
    else:
        print("❌ Kraken OHLC Error:", data['error'])
        return None

def get_balances():
    balances = k.get_account_balance()
    btc = float(balances.loc[ASSET]['vol'])
    usd = float(balances.loc[QUOTE]['vol'])
    return btc, usd

def place_order(order_type, volume):
    try:
        k.add_standard_order(pair="XBTUSD", type=order_type, ordertype="market", volume=volume)
        print(f"✅ Placed {order_type.upper()} order for {volume} BTC.")
    except Exception as e:
        print(f"❌ Order Error: {e}")

def execute_trade_logic():
    global last_buy_rsi
    rsi = fetch_latest_rsi()
    if rsi is None:
        return

    btc_balance, usd_balance = get_balances()
    print(f"🔁 RSI: {rsi} | BTC: {btc_balance:.6f} | USD: ${usd_balance:.2f}")

    # SELL Logic (Sell all BTC if RSI crosses ladder zones)
    for level, portion in SELL_LADDER:
        if rsi >= level and btc_balance > 0:
            sell_volume = btc_balance * portion
            place_order("sell", round(sell_volume, 6))
            time.sleep(1)

    # BUY Logic (Buy when RSI dips below levels)
    if rsi <= last_buy_rsi:
        for level, portion in BUY_LADDER:
            if rsi <= level and usd_balance > 10:
                buy_amount = usd_balance * portion
                price = float(k.get_ticker_information("XBTUSD")["c"][0])
                volume = round(buy_amount / price, 6)
                place_order("buy", volume)
                time.sleep(1)
        if rsi <= 32:
            last_buy_rsi = 100  # Reset to avoid rebuy until RSI climbs again
    elif rsi >= REBUY_RSI_THRESHOLD:
        last_buy_rsi = rsi  # Reset ladder after RSI recovery

# === MAIN LOOP ===
while True:
    try:
        execute_trade_logic()
    except Exception as e:
        print(f"❌ Bot Crash: {e}")
    time.sleep(60)
