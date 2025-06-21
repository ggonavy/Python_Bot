import time
import requests
import hmac
import hashlib
import base64
import urllib.parse
import os
import json
from datetime import datetime
from pytz import timezone
import pandas as pd
import ta

# === 🔐 KRAKEN API CONFIG ===
KRAKEN_API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
KRAKEN_API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="

# === ⚙️ BOT CONFIG ===
PAIR = "XBTUSDT"
TRADE_VOLUME = 500  # Adjust this to your USD allocation per full cycle
RSI_TIMEFRAME = 240  # 4h = 240 minutes
THROTTLE_DELAY = 60 * 60  # 1 hour between signals
CYCLE_STATE_FILE = "cycle_state.json"

BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]

last_trade_time = 0


# === 📜 UTILITIES ===
def log(msg):
    now = datetime.now(timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")


def load_state():
    if os.path.exists(CYCLE_STATE_FILE):
        with open(CYCLE_STATE_FILE, 'r') as f:
            return json.load(f)
    return {"sold_out": False}


def save_state(state):
    with open(CYCLE_STATE_FILE, 'w') as f:
        json.dump(state, f)


def sign_request(urlpath, data, secret, nonce):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(nonce) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()

    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sig_digest = base64.b64encode(mac.digest())
    return sig_digest.decode()


def kraken_request(uri_path, data):
    url = "https://api.kraken.com" + uri_path
    data['nonce'] = str(int(1000 * time.time()))
    headers = {
        'API-Key': KRAKEN_API_KEY,
        'API-Sign': sign_request(uri_path, data, KRAKEN_API_SECRET, data['nonce'])
    }
    response = requests.post(url, headers=headers, data=data)
    return response.json()


def get_ohlcv():
    url = f"https://api.kraken.com/0/public/OHLC"
    params = {"pair": PAIR, "interval": RSI_TIMEFRAME}
    response = requests.get(url, params=params)
    data = response.json()
    ohlcv_key = list(data['result'].keys())[0]
    df = pd.DataFrame(data['result'][ohlcv_key], columns=[
        'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
    df['close'] = df['close'].astype(float)
    return df


def get_rsi(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    return df['rsi'].iloc[-1]


def execute_trade(side, volume):
    pair = "XBT/USDT"
    type = "buy" if side == "buy" else "sell"
    order = {
        "pair": pair,
        "type": type,
        "ordertype": "market",
        "volume": volume
    }
    result = kraken_request('/0/private/AddOrder', order)
    log(f"🔁 Executed {side.upper()} order: {result}")
    return result


# === 🤖 MAIN BOT LOOP ===
while True:
    try:
        current_time = time.time()
        if current_time - last_trade_time < THROTTLE_DELAY:
            time.sleep(60)
            continue

        df = get_ohlcv()
        rsi = get_rsi(df)
        state = load_state()
        log(f"RSI: {rsi:.2f} | Cycle sold out: {state['sold_out']}")

        # === BUY LOGIC ===
        if not state['sold_out']:
            for level, pct in BUY_LADDER:
                if rsi <= level:
                    amount = TRADE_VOLUME * pct
                    log(f"🟢 RSI {rsi:.2f} <= {level} → BUY ${amount}")
                    execute_trade("buy", round(amount / df['close'].iloc[-1], 6))
                    last_trade_time = current_time
                    break
            if rsi < 27:
                log("⛔ RSI < 27 — bot halts buys, wait for manual DCA")
        
        # === SELL LOGIC ===
        if state['sold_out'] is False:
            for level, pct in SELL_LADDER:
                if rsi >= level:
                    amount = TRADE_VOLUME * pct
                    log(f"🔴 RSI {rsi:.2f} >= {level} → SELL ${amount}")
                    execute_trade("sell", round(amount / df['close'].iloc[-1], 6))
                    last_trade_time = current_time
                    state['sold_out'] = True
                    save_state(state)
                    break

        # === RESET LOGIC ===
        if state['sold_out'] and rsi <= 47:
            log("🔁 RSI <= 47 — cycle reset, bot can buy again")
            state['sold_out'] = False
            save_state(state)

        time.sleep(300)

    except Exception as e:
        log(f"⚠️ ERROR: {e}")
        time.sleep(60)
