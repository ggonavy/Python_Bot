# SlateBot_Binance_v2_FINAL.py
# FINAL Version: Matches full confirmed strategy with fixed profit targets

import time
import os
import json
from datetime import datetime
from binance.client import Client
from binance.enums import *

# === CONFIGURATION ===
CHECK_INTERVAL = 15  # seconds
PAIR = 'BTCUSDT'
DECIMALS = 6
TRADE_FEE_PCT = 0.001  # 0.1% per trade

# === Buy Ladder and Fixed Sell Prices ===
BUY_LADDER = [
    {"drop_pct": 2.5, "amount_pct": 0.25, "sell_price": 102500.0},
    {"drop_pct": 3.5, "amount_pct": 0.35, "sell_price": 103500.0},
    {"drop_pct": 4.5, "amount_pct": 0.40, "sell_price": 104500.0},
]

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

# === State ===
high_price = 0.0
buys = []
INITIAL_FIAT = 25000.0
available_fiat = INITIAL_FIAT
LOG_FILE = "slatebot_trade_log.json"

# === Load existing state ===
def load_log():
    global high_price, buys, available_fiat
    try:
        with open(LOG_FILE, 'r') as f:
            state = json.load(f)
            high_price = state.get("high_price", 0.0)
            buys.extend(state.get("buys", []))
            available_fiat = state.get("available_fiat", INITIAL_FIAT)
    except FileNotFoundError:
        pass

# === Save current state ===
def save_log():
    with open(LOG_FILE, 'w') as f:
        json.dump({
            "high_price": high_price,
            "buys": buys,
            "available_fiat": available_fiat
        }, f, indent=2)

# === Get BTC price ===
def get_price():
    ticker = client.get_symbol_ticker(symbol=PAIR)
    return float(ticker['price'])

# === Market Buy ===
def execute_buy(usdt_amount):
    price = get_price()
    qty = round((usdt_amount * (1 - TRADE_FEE_PCT)) / price, DECIMALS)
    # client.order_market_buy(symbol=PAIR, quantity=qty)
    return price, qty

# === Market Sell ===
def execute_sell(btc_amount):
    price = get_price()
    qty = round(btc_amount * (1 - TRADE_FEE_PCT), DECIMALS)
    # client.order_market_sell(symbol=PAIR, quantity=qty)
    return price, qty

# === Main Loop ===
load_log()
print("[SlateBot v2] Running final strategy...")

while True:
    try:
        price = get_price()

        # Update high
        if not buys or price > high_price:
            high_price = price

        # Buy checks
        for i, ladder in enumerate(BUY_LADDER):
            target_price = high_price * (1 - ladder['drop_pct'] / 100)
            already_bought = any(b['level'] == i for b in buys)
            if price <= target_price and not already_bought:
                fiat_to_use = INITIAL_FIAT * ladder['amount_pct']
                if available_fiat >= fiat_to_use:
                    buy_price, qty = execute_buy(fiat_to_use)
                    buys.append({
                        "level": i,
                        "buy_price": buy_price,
                        "btc": qty,
                        "sell_price": ladder['sell_price'],
                        "timestamp": str(datetime.utcnow())
                    })
                    available_fiat -= fiat_to_use
                    print(f"[BUY] Level {i}: {qty} BTC at ${buy_price:.2f}")

        # Sell checks
        for b in buys[:]:
            if price >= b['sell_price']:
                sell_price, qty_sold = execute_sell(b['btc'])
                profit = (sell_price - b['buy_price']) * qty_sold * (1 - TRADE_FEE_PCT)
                available_fiat += qty_sold * sell_price
                print(f"[SELL] Sold {qty_sold} BTC at ${sell_price:.2f}, Profit: ${profit:.2f}")
                buys.remove(b)

        # Reset high when all BTC sold
        if not buys:
            print("[CYCLE RESET] All positions closed. High reset.")
            high_price = price
            available_fiat = INITIAL_FIAT

        save_log()
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print("[ERROR]", e)
        time.sleep(5)
