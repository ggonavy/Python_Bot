import requests
import pandas as pd
import ta
import time
from datetime import datetime
from pytz import timezone
import krakenex

# === CONFIG ===
PAIR = "XXBTZUSD"  # Kraken symbol for BTC/USDT
BUY_RSI = 43
SELL_RSI = 73
TIMEFRAME_MIN = 240  # 4h = 240 min
QUOTE_VOLUME = 100  # $100 worth of BTC per order
THRESHOLD_DELAY = 60 * 60  # 1 hour between signals
API_KEY_FILE = 'kraken.key'  # contains your Kraken keys

# === STATE ===
last_signal_time = None
position = None  # "long" or None

# === LOAD API KEYS ===
api = krakenex.API()
api.load_key(API_KEY_FILE)

# === FETCH OHLCV DATA ===
def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": "XBTUSDT", "interval": TIMEFRAME_MIN}
    response = requests.get(url, params=params)
    result = response.json()['result']
    pair_key = list(result.keys())[0]  # 'XBTUSDT' or 'XXBTZUSD'
    ohlcv = result[pair_key]
    df = pd.DataFrame(ohlcv, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = pd.to_numeric(df['close'])
    return df

# === CALCULATE RSI ===
def get_rsi(df, period=14):
    rsi_series = ta.momentum.RSIIndicator(df['close'], window=period).rsi()
    return rsi_series.iloc[-1]

# === PLACE ORDER ===
def place_order(order_type='buy', volume='0.001'):
    response = api.query_private('AddOrder', {
        'pair': PAIR,
        'type': order_type,
        'ordertype': 'market',
        'volume': volume
    })
    print(f"[{order_type.upper()} ORDER] Kraken response:", response)
    return response

# === MAIN LOOP ===
def main_loop():
    global last_signal_time, position
    while True:
        try:
            now = time.time()
            if last_signal_time and (now - last_signal_time < THRESHOLD_DELAY):
                print("Waiting before sending another signal...")
                time.sleep(60)
                continue

            df = fetch_ohlcv()
            rsi = get_rsi(df)

            print(f"[{datetime.now(timezone('US/Eastern'))}] RSI: {rsi:.2f}, Position: {position}")

            if rsi <= BUY_RSI and position != "long":
                btc_price = df['close'].iloc[-1]
                btc_amount = round(QUOTE_VOLUME / btc_price, 6)
