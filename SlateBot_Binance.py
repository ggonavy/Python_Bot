# SlateBot_Binance.py

import time
import math
from binance.client import Client
from binance.enums import *

# === CONFIG ===
CHECK_INTERVAL = 15  # seconds
PAIR = 'BTCUSDT'
DECIMALS = 2  # for rounding BTC amounts

# === Placeholder for API keys ===
API_KEY = 'YOUR_API_KEY_HERE'
API_SECRET = 'YOUR_API_SECRET_HERE'

# === Initialize Binance client ===
client = Client(API_KEY, API_SECRET)

# === State ===
high_price = 0.0
buys = []  # Tracks each executed buy with price and amount

# === Buy Ladder Settings ===
BUY_LADDER = [
    {"drop_pct": 2.5, "amount_pct": 0.25, "sell_trigger_pct": 2.5},
    {"drop_pct": 3.5, "amount_pct": 0.35, "sell_trigger_pct": 3.5},
    {"drop_pct": 4.5, "amount_pct": 0.40, "sell_trigger_pct": 4.5},
]

# === Utility ===
def get_price():
    ticker = client.get_symbol_ticker(symbol=PAIR)
    return float(ticker['price'])

def get_balances():
    fiat_balance = float(client.get_asset_balance(asset='USDT')['free'])
    btc_balance = float(client.get_asset_balance(asset='BTC')['free'])
    return fiat_balance, btc_balance

def place_market_buy(usdt_amount):
    price = get_price()
    quantity = round(usdt_amount / price, DECIMALS)
    order = client.order_market_buy(symbol=PAIR, quantity=quantity)
    return quantity, price

def place_market_sell(btc_amount):
    quantity = round(btc_amount, DECIMALS)
    order = client.order_market_sell(symbol=PAIR, quantity=quantity)
    return get_price()

# === Main Loop ===
print("SlateBot_Binance started... 🧠")
while True:
    try:
        current_price = get_price()

        # Track high
        if current_price > high_price:
            high_price = current_price
            print(f"[High Updated] {high_price}")

        # Get available fiat
        fiat_balance, btc_balance = get_balances()
        total_fiat_start = fiat_balance + sum([b['usdt_used'] for b in buys])

        # === Buy Logic ===
        for entry in BUY_LADDER:
            dip_price = high_price * (1 - entry['drop_pct'] / 100)
            if current_price <= dip_price:
                if not any(abs(b['drop_pct'] - entry['drop_pct']) < 0.01 for b in buys):
                    usdt_to_spend = round(total_fiat_start * entry['amount_pct'], 2)
                    if usdt_to_spend <= fiat_balance:
                        quantity, price = place_market_buy(usdt_to_spend)
                        buys.append({
                            'drop_pct': entry['drop_pct'],
                            'usdt_used': usdt_to_spend,
                            'btc_bought': quantity,
                            'buy_price': price,
                            'sell_trigger': high_price * (1 + entry['sell_trigger_pct'] / 100),
                            'sold': False
                        })
                        print(f"[BUY] Dip –{entry['drop_pct']}%: Bought {quantity} BTC @ {price}, Target Sell: {round(high_price * (1 + entry['sell_trigger_pct'] / 100), 2)}")

        # === Sell Logic ===
        for b in buys:
            if not b['sold'] and current_price >= b['sell_trigger']:
                place_market_sell(b['btc_bought'])
                b['sold'] = True
                print(f"[SELL] Target +{BUY_LADDER[buys.index(b)]['sell_trigger_pct']}% hit. Sold {b['btc_bought']} BTC @ {current_price}")

        # === Reset logic ===
        if all(b['sold'] for b in buys) and buys:
            print("[RESET] All BTC sold. Restarting cycle.")
            buys.clear()
            high_price = 0.0

        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"[ERROR] {e}")
        time.sleep(CHECK_INTERVAL)

