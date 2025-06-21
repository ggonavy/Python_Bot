import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime

# === CONFIG ===
PAIR = "XBTUSDT"
TIMEFRAME = 60  # 1-hour candles
KRAKEN_API = "https://api.kraken.com/0/public/OHLC"
TOTAL_USDT = 1000  # Total capital allocated to this bot

# === BUY LADDER (RSI → % of TOTAL_USDT) ===
BUY_LADDER = {
    47: 0.10,
    42: 0.20,
    37: 0.30,
    32: 0.40
}
# < 27 = no bot buy (manual DCA by user)

# === SELL LADDER (RSI → % of BTC position) ===
SELL_LADDER = {
    73: 0.40,
    77: 0.30,
    81: 0.20,
    85: 0.10
}

# === TIMING ===
COOLDOWN = 3600         # 1 hour between signals
CHECK_INTERVAL = 300    # 5-minute check loop

# === BOT STATE ===
position = 0.0              # BTC held
ladder_bought = set()       # Bought RSI levels
ladder_sold = set()         # Sold RSI levels
last_action_time = 0        # Last signal time

# === FETCH OHLCV FROM KRAKEN ===
def fetch_ohlcv():
    params = {"pair": PAIR, "interval": TIMEFRAME}
    response = requests.get(KRAKEN_API, params=params)
    data = response.json()
    if 'error' in data and data['error']:
        raise Exception(data['error'])
    pair_key = next(k for k in data['result'] if k != 'last')
    ohlc = data['result'][pair_key]
    df = pd.DataFrame(ohlc, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
    ])
    df['close'] = df['close'].astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    return df

# === CALCULATE RSI ===
def calculate_rsi(df, period=14):
    rsi = RSIIndicator(close=df['close'], window=period)
    df['rsi'] = rsi.rsi()
    return df

# === EXECUTE STRATEGY ===
def check_market():
    global position, ladder_bought, ladder_sold, last_action_time

    now = time.time()
    if now - last_action_time < COOLDOWN:
        return

    try:
        df = fetch_ohlcv()
        df = calculate_rsi(df)
        rsi = df['rsi'].iloc[-1]
        price = df['close'].iloc[-1]

        print(f"[{datetime.now()}] RSI: {rsi:.2f} | Price: ${price:.2f}")

        # === BUY LADDER ===
        if position == 0.0:
            for level, pct in sorted(BUY_LADDER.items()):
                if rsi <= level and level not in ladder_bought:
                    if rsi < 27:
                        print(f"❌ RSI {rsi:.2f} too low — No bot buys below 27. Use manual DCA.")
                        return
                    usdt = TOTAL_USDT * pct
                    btc = round(usdt / price, 6)
                    position += btc
                    ladder_bought.add(level)
                    last_action_time = now
                    print(f"✅ BUY {btc} BTC at ${price:.2f} [RSI {rsi:.2f}]")
                    break

        # === SELL LADDER ===
        elif position > 0.0:
            for level, pct in sorted(SELL_LADDER.items()):
                if rsi >= level and level not in ladder_sold:
                    btc_to_sell = round(position * pct, 6)
                    position -= btc_to_sell
                    ladder_sold.add(level)
                    last_action_time = now
                    print(f"🔻 SELL {btc_to_sell} BTC at ${price:.2f} [RSI {rsi:.2f}]")
                    break

        # === RESET CYCLE ===
        if position == 0.0 and rsi <= 47:
            print("🔁 Full cycle complete. RSI cooled to 47 or lower. Resetting ladder.")
            ladder_bought.clear()
            ladder_sold.clear()

    except Exception as e:
        print(f"[ERROR] {e}")

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🟢 SlateBot v12 (RSI Ladder Strategy) is LIVE — No shorting, 1H timeframe, DCA logic enabled")
    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)
