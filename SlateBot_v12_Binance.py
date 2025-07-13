import time
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from datetime import datetime
from pytz import timezone
from binance.client import Client
from binance.enums import *

# === CONFIGURATION ===
BINANCE_API_KEY = "PASTE_YOUR_BINANCE_API_KEY"
BINANCE_SECRET_KEY = "PASTE_YOUR_BINANCE_SECRET_KEY"
PAIR = "BTCUSDT"
ASSET = "BTC"
QUOTE = "USDT"
TIMEZONE = 'US/Eastern'
TIMEFRAME = "1h"

# === STRATEGY PARAMETERS ===
BUY_LADDER = [(47, 0.10), (42, 0.20), (37, 0.30)]
SELL_LADDER = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]
REBUY_RSI_THRESHOLD = 47
last_buy_rsi = 100

# === CONNECT TO BINANCE ===
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

def fetch_ohlc(symbol, interval, limit=100):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    return df

def get_rsi(df, period=14):
    rsi = RSIIndicator(close=df['close'], window=period)
    return rsi.rsi().iloc[-1]

def get_balance(asset):
    balance = client.get_asset_balance(asset=asset)
    return float(balance['free']) if balance else 0.0

def get_price():
    ticker = client.get_symbol_ticker(symbol=PAIR)
    return float(ticker['price'])

def place_market_order(symbol, side, quantity):
    try:
        order = client.create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        print(f"{side} executed: {quantity} {ASSET} @ market")
    except Exception as e:
        print(f"Order error: {e}")

# === MAIN LOOP ===
print("SlateBot v12 Binance starting...")
while True:
    try:
        df = fetch_ohlc(PAIR, TIMEFRAME)
        rsi = get_rsi(df)
        now = datetime.now(timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
        fiat = get_balance(QUOTE)
        btc = get_balance(ASSET)
        price = get_price()

        print(f"[{now}] RSI: {rsi:.2f} | USDT: {fiat:.2f} | BTC: {btc:.6f}")

        # === BUY LOGIC ===
        if rsi <= 32:
            allocation = 1.0 if rsi <= 27 else next((a for lvl, a in reversed(BUY_LADDER) if rsi <= lvl), 0)
            buy_amount = fiat * allocation
            if buy_amount > 5:
                quantity = round(buy_amount / price, 6)
                place_market_order(PAIR, SIDE_BUY, quantity)
                last_buy_rsi = rsi

        # === SELL LOGIC ===
        for lvl, pct in SELL_LADDER:
            if rsi >= lvl and btc > 0.0001:
                sell_qty = round(btc * pct, 6)
                place_market_order(PAIR, SIDE_SELL, sell_qty)
                time.sleep(1)

        if rsi > REBUY_RSI_THRESHOLD:
            last_buy_rsi = 100

    except Exception as e:
        print(f"Error: {e}")

    time.sleep(1)
