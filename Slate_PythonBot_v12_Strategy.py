
import time
import requests
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime
from pytz import timezone
import pandas as pd
import ta

# === CONFIG ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="
PAIR = "XBTUSD"
ASSET = "XXBT"
FIAT = "ZUSD"
TIMEFRAME = 60  # 1H

BUY_LADDERS = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LADDERS = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

last_buy_rsi = 100
bought_total = 0.0  # BTC currently held by bot

def log(msg):
    now = datetime.now(timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def kraken_request(uri_path, data, private=True):
    url = "https://api.kraken.com" + uri_path
    headers = {}
    if private:
        nonce = str(int(1000 * time.time()))
        data['nonce'] = nonce
        post_data = urllib.parse.urlencode(data)
        encoded = (nonce + post_data).encode()
        message = uri_path.encode() + hashlib.sha256(encoded).digest()
        signature = hmac.new(base64.b64decode(API_SECRET), message, hashlib.sha512)
        sig_digest = base64.b64encode(signature.digest())
        headers = {
            'API-Key': API_KEY,
            'API-Sign': sig_digest.decode()
        }
        response = requests.post(url, headers=headers, data=data)
    else:
        response = requests.get(url, params=data)
    return response.json()

def get_balance():
    res = kraken_request('/0/private/Balance', {}, private=True)
    return float(res['result'].get(FIAT, 0)), float(res['result'].get(ASSET, 0))

def place_order(type_, volume):
    data = {
        'pair': PAIR,
        'type': type_,
        'ordertype': 'market',
        'volume': str(volume)
    }
    res = kraken_request('/0/private/AddOrder', data)
    log(f"{type_.upper()} ORDER: {res}")
    return res

def fetch_ohlcv():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": TIMEFRAME}
    r = requests.get(url, params=params)
    candles = r.json()['result']
    key = list(candles.keys())[0]
    df = pd.DataFrame(candles[key], columns=[
        'time','open','high','low','close','vwap','volume','count'])
    df['close'] = pd.to_numeric(df['close'])
    return df

def get_rsi():
    df = fetch_ohlcv()
    rsi_series = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    return round(rsi_series.iloc[-1], 2)

def run_bot():
    global last_buy_rsi, bought_total

    rsi = get_rsi()
    usd_balance, btc_balance = get_balance()
    log(f"RSI: {rsi} | USD: {usd_balance:.2f} | BTC: {btc_balance:.6f}")

    # === BUY LOGIC ===
    if rsi <= last_buy_rsi:
        for level, pct in BUY_LADDERS:
            if rsi <= level and usd_balance > 5:
                amount_usd = usd_balance * pct
                price = float(fetch_ohlcv()['close'].iloc
