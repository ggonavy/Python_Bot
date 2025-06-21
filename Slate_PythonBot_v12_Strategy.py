import time, requests, hashlib, hmac, base64, urllib.parse
import pandas as pd
import ta
from datetime import datetime
from pytz import timezone

# === CONFIG ===
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="
PAIR = "XBTUSD"
TIMEFRAME = 60  # 1h
RSI_PERIOD = 14

# RSI Tiers (Buy/Sell % of balance)
BUY_TIERS = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_TIERS = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

bought = []
sold = []

def log(msg):
    now = datetime.now(timezone("US/Eastern")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

def get_kraken_signature(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest())

def kraken_request(path, data):
    headers = {
        'API-Key': API_KEY,
        'API-Sign': get_kraken_signature(path, data, API_SECRET)
    }
    return requests.post(f"https://api.kraken.com{path}", headers=headers, data=data).json()

def get_balance(asset):
    data = {"nonce": str(int(1000 * time.time()))}
    res = kraken_request("/0/private/Balance", data)
    return float(res["result"].get(asset, 0.0)) if "result" in res else 0.0

def get_price():
    res = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD").json()
    return float(res["result"]["XXBTZUSD"]["c"][0])

def place_order(type_, volume):
    data = {
        "nonce": str(int(1000 * time.time())),
        "ordertype": "market",
        "type": type_,
        "volume": str(volume),
        "pair": "XBTUSD"
    }
    return kraken_request("/0/private/AddOrder", data)

def fetch_ohlcv():
    res = requests.get("https://api.kraken.com/0/public/OHLC", params={"pair": "XBTUSD", "interval": TIMEFRAME}).json()
    ohlc = res["result"]["XXBTZUSD"]
    df =
