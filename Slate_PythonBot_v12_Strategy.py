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
QUOTE = "ZUSD"  # ⚠️ This might be incorrect — we will debug and confirm
TIMEFRAME = 60  # 1 hour candles
TIMEZONE = 'US/Eastern'

# === STRATEGY SETTINGS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 1.00)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
last_buy_rsi = 100

# === CONNECT TO KRAKEN ===
api = krakenex.API(API_KEY, API_SECRET)
k = KrakenAPI(api)

def log(msg):
    now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_latest_rsi():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(url, params=params).json()
    ohlc_key = [key for key in response['result'] if key != 'last'][0]
    candles = response['result'][ohlc_key]
    df = pd.DataFrame(candles, columns=[
        'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = pd.to_numeric(df['close'])
    rsi = RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]
    return round(rsi, 2)

def get_balances():
    balances = k.get_account_balance()
    
    # === 🔍 DEBUG: Print all keys so we know your real fiat symbol
    log("🔍 RAW BALANCES:")
    for asset in balances.index:
        log(f"  {asset} => {balances.loc[asset]['vol']}")

    btc = float(balances.loc[ASSET]['vol']) if ASSET in balances.index else 0.0
    usd = float(balances.loc[QUOTE]['vol']) if QUOTE in balances.index else 0.0
    return btc, usd

def place_market_buy(usd_amount):
    if usd_amount < 5:
        log(f"🟡 Not enough USD to buy: ${usd_amount:.2f}")
        return
    price = float(k.get_ticker_information(PAIR).loc[PAIR]['c'][0])
    volume = round(usd_amount / price, 8)
    response = k.add_standard_order(pair=PAIR, type='buy', ordertype='market', volume=volume)
    log(f"✅ Bought {volume:.8f} BTC at ~${price:.2f} for ${usd_amount:.2f}")
    return response

def place_market_sell(btc_amount):
    if btc_amount < 0.0001:
        log(f"🟡 Not enough BTC to sell: {btc_amount:.8f}")
        return
    response = k.add_standard_order(pair=PAIR, type='sell', ordertype='market', volume=round(btc_amount, 8))
    log(f"✅ Sold {btc_amount:.8f} BTC at market price")
    return response

def run_bot():
    global last_buy_rsi

    while True:
        try:
            rsi = fetch_latest_rsi()
            btc_balance, usd_balance = get_balances()
            log(f"🔁 RSI: {rsi} | BTC: {btc_balance:.6f} | USD: ${usd_balance:.2f}")

            # === SELL LOGIC ===
            for sell_rsi, portion in SELL_LADDER:
                if rsi >= sell_rsi and btc_balance > 0:
                    sell_amount = btc_balance * portion
                    place_market_sell(sell_amount)
                    last_buy_rsi = 100

            # === BUY LOGIC ===
            if rsi <= REBUY_RSI_THRESHOLD:
                for buy_rsi, portion in BUY_LADDER:
                    if rsi <= buy_rsi and usd_balance > 5:
                        buy_amount = usd_balance * portion if buy_rsi != 32 else usd_balance
                        place_market_buy(buy_amount)
                        last_buy_rsi = rsi

        except Exception as e:
            log(f"❌ ERROR: {e}")

        time.sleep(60)

# === START BOT ===
if __name__ == "__main__":
    log("🚀 Starting SlateBot v12 (Kraken Live 1H)")
    run_bot()
