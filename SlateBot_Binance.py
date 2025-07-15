# SlateBot_Binance.py

import time
import math
from binance.client import Client
from binance.enums import *

# === CONFIG ===
CHECK_INTERVAL = 15  # seconds
PAIR = 'BTCUSDT'
DECIMALS = 6  # BTC precision to 6 decimal places (Binance requirement)

# === Placeholder for API keys ===
API_KEY = 'YOUR_API_KEY_HERE'
API_SECRET = 'YOUR_API_SECRET_HERE'

# === Initialize Binance client ===
client = Client(API_KEY, API_SECRET)

# === State ===
high_price = 0.0
buys = []  # Tracks each executed buy: price, amount, sell trigger

# === Buy Ladder Settings ===
BUY_LADDER = [
    {"drop_pct": 2.5, "amount_pct": 0.25, "sell_trigger_pct": 2.5},
    {"drop_pct": 3.5, "amount_pct": 0.35, "sell_trigger_pct": 3.5},
    {"drop_pct": 4.5, "amount_pct": 0.40, "sell_trigger_pct": 4.5},
]

# === Utility Functions ===
def get_price():
    ticker = client.get_symbol_ticker(symbol=PAIR)
    return float(ticker['price'])

def get_balances():
    fiat = float(client.get_asset_balance(asset='USDT')['free'])
    btc = float(client.get_asset_balance(asset='BTC')['free'])
    return fiat, btc

def place_market_buy(usdt_amount):
    price = get_price()
    quantity = round(usdt_amount / price, DECIMALS)
    order = client.order_market_buy(symbol=PAIR, quantity=quantity)
    return quantity, price

def place_market_sell(btc_amount):
    quantity = round(btc_amount, DECIMALS)
    order = client.order_market_sell(symbol=PAIR, quantity=quantity)
    return get_price()

# === Main Logic ===
p
