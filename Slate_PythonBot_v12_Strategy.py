import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime
import hmac
import hashlib
import base64
import urllib.parse

# === CONFIG ===
API_KEY = 'haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM'
API_SECRET = 'MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=='
PAIR = 'XBTUSDT'
TIMEFRAME_MINUTES = 60
BASE_URL = 'https://api.kraken.com'

# === LADDER LOGIC ===
BUY_LEVELS = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LEVELS = [(85, 0.10), (81, 0.20), (77, 0.30), (73, 0.40)]

# === STATE ===
position_percent = 0.0
last_sell = False

def get_ohlcv():
    url = f'{BASE_URL}/0/public/OHLC'
    params = {
        'pair': 'XBTUSDT',
        'interval': TIMEFRAME_MINUTES // 60
    }
    r = requests.get(url, params=params).json()
    candles = r['result']['XBTUSDT']
    df = pd.DataFrame(candles, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
    df['close'] = df['close'].astype(float)
    return df

def calculate_rsi(df):
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    return rsi.iloc[-1]

def get_nonce():
    return str(int(1000 * time.time()))

def sign_request(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    signature = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sig_digest = base64.b64encode(signature.digest())
    return sig_digest.decode()

def kraken_request(endpoint, data={}):
    urlpath = f'/0/private/{endpoint}'
    url = BASE_URL + urlpath
    data['nonce'] = get_nonce()
    headers = {
        'API-Key': API_KEY,
        'API-Sign': sign_request(urlpath, data, API_SECRET)
    }
    r = requests.post(url, headers=headers, data=data)
    return r.json()

def place_market_order(side, percentage):
    volume = 0.001 * percentage * 10  # Adjust this multiplier to match your capital size
    order = {
        'pair': PAIR,
        'type': side,
        'ordertype': 'market',
        'volume': str(volume)
    }
    response = kraken_request('AddOrder', order)
    print(f"[{datetime.now()}] Placed {side.upper()} {percentage*100}% order: {response}")

def log_status(rsi, action=None):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] RSI: {rsi:.2f} | Action: {action if action else 'HOLD'} | Position: {position_percent*100:.1f}%")

def main():
    global position_percent, last_sell

    while True:
        try:
            df = get_ohlcv()
            rsi = calculate_rsi(df)
            log_status(rsi)

            # SELL LADDER
            for level, pct in SELL_LEVELS:
                if rsi >= level and position_percent > 0:
                    place_market_order('sell', pct)
                    position_percent -= pct
                    if position_percent < 0: position_percent = 0
                    last_sell = True
                    log_status(rsi, f"SELL {pct*100}%")
                    break

            # No re-buying unless RSI drops to 47 or lower after a sell
            if last_sell and rsi > 47:
                log_status(rsi, "Waiting to rebuy after SELL")
                time.sleep(TIMEFRAME_MINUTES * 60)
                continue
            else:
                last_sell = False

            # BUY LADDER
            if rsi < 27:
                log_status(rsi, "RSI < 27 — YOU DCA MANUALLY")
            else:
                for level, pct in BUY_LEVELS:
                    if rsi <= level and position_percent + pct <= 1.0:
                        place_market_order('buy', pct)
                        position_percent += pct
                        log_status(rsi, f"BUY {pct*100}%")
                        break

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(TIMEFRAME_MINUTES * 60)

if __name__ == "__main__":
    main()
