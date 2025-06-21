import requests
import pandas as pd
import time
from datetime import datetime
from pytz import timezone

# ============ CONFIG ============
PAIR = "XBTUSDT"
RSI_BUY = 43
RSI_SELL = 73
TIMEFRAME_MIN = 240  # 4H
CHECK_INTERVAL = 60 * 15  # 15 minutes
QUOTE_BALANCE = 1000
MAX_POSITION_SIZE = 1000
# =================================

position = 0.0
last_signal = None


def fetch_ohlcv(pair="XBTUSDT", interval=240):
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": pair, "interval": interval}
    response = requests.get(url, params=params)
    data = response.json()
    if 'result' not in data:
        return None
    key = list(data['result'].keys())[0]
    ohlcv = data['result'][key]
    df = pd.DataFrame(ohlcv, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap',
        'volume', 'count'])
    df['close'] = pd.to_numeric(df['close'])
    return df


def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def execute_trade(action):
    global position

    now = datetime.now(timezone("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] ACTION: {action.upper()}")

    if action == "buy":
        position += QUOTE_BALANCE / get_current_price()
        print(f"--> New position size: {round(position, 6)} BTC")
    elif action == "sell":
        print(f"--> Selling all {round(position, 6)} BTC")
        position = 0.0


def get_current_price():
    url = "https://api.kraken.com/0/public/Ticker"
    params = {"pair": PAIR}
    r = requests.get(url, params=params)
    result = r.json()['result']
    key = list(result.keys())[0]
    return float(result[key]['c'][0])


def main_loop():
    global last_signal, position

    while True:
        df = fetch_ohlcv(PAIR, TIMEFRAME_MIN)
        if df is None or len(df) < 15:
            print("Error fetching data. Retrying...")
            time.sleep(60)
            continue

        df['rsi'] = calculate_rsi(df)

        current_rsi = df['rsi'].iloc[-1]
        current_price = df['close'].iloc[-1]

        print(f"[{datetime.utcnow()}] RSI: {round(current_rsi,2)} | BTC: ${round(current_price,2)}")

        if current_rsi <= RSI_BUY and position * current_price < MAX_POSITION_SIZE:
            if last_signal != "buy":
                execute_trade("buy")
                last_signal = "buy"

        elif current_rsi >= RSI_SELL and position > 0:
            if last_signal != "sell":
                execute_trade("sell")
                last_signal = "sell"

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    print("Starting SlateBot V12 Manual RSI Strategy...")
    main_loop()
