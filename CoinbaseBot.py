import coinbase
from coinbase import CoinbaseClient
from coinbase.websocket import WebsocketClient
import pandas as pd
import time
import os
import asyncio
from datetime import datetime

# Load API credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')
api_passphrase = os.getenv('COINBASE_PASSPHRASE')

# Initialize REST client
client = CoinbaseClient(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)

# Trading parameters
PAIR = 'BTC-USD'
RSI_PERIOD = 14
BUY_RSI = [47, 42, 37, 32]
SELL_RSI = [73, 77, 81, 85]
SLEEP_INTERVAL = 60  # seconds
TRADE_AMOUNT = 0.01675  # ~1/10th of 0.1675 BTC
PRICE_TOLERANCE = 0.005  # 0.5% price slippage for limit orders

# Logging
def log(message):
    print(f"{datetime.now()}: {message}")

# Get historical data for RSI
def get_rsi(pair, period=RSI_PERIOD):
    candles = client.get_candles(product_id=pair, query_params={'granularity': 'FIVE_MINUTE', 'limit': period + 1})
    df = pd.DataFrame(candles.get('candles', []), columns=['start', 'low', 'high', 'open', 'close', 'volume'])
    df['close'] = df['close'].astype(float)
    df = df.sort_values('start', ascending=True)
    deltas = df['close'].diff()
    gains = deltas.where(deltas > 0, 0)
    losses = -deltas.where(deltas < 0, 0)
    avg_gain = gains.rolling(window=period).mean().iloc[-1]
    avg_loss = losses.rolling(window=period).mean().iloc[-1]
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
    rsi = 100 - (100 / (1 + rs))
    return rsi, df['close'].iloc[-1]

# WebSocket for real-time price
class PriceFeed:
    def __init__(self):
        self.latest_price = None
        self.ws = WebsocketClient(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)

    async def subscribe(self, pair):
        await self.ws.subscribe(channels=['ticker'], product_ids=[pair])
        async for message in self.ws:
            if message.get('type') == 'ticker' and message.get('product_id') == pair:
                self.latest_price = float(message['price'])
                log(f"WebSocket Price: ${self.latest_price:.2f}")

    def get_price(self):
        return self.latest_price

# Main trading loop
async def main():
    price_feed = PriceFeed()
    asyncio.create_task(price_feed.subscribe(PAIR))

    while True:
        try:
            # Get RSI and price
            rsi, _ = get_rsi(PAIR)
            price = price_feed.get_price()
            if not price:
                log("Waiting for WebSocket price...")
                await asyncio.sleep(5)
                continue
            log(f"Price: ${price:.2f} | RSI: {rsi:.2f}")

            # Get balances
            accounts = client.get_accounts().get('accounts', [])
            btc_balance = float(next(acc for acc in accounts if acc['currency'] == 'BTC')['available'])
            usd_balance = float(next(acc for acc in accounts if acc['currency'] == 'USD')['available'])
            log(f"BTC: {btc_balance:.6f} | USD: ${usd_balance:.2f}")

            # Buy logic (limit order)
            for rsi_level in BUY_RSI:
                if rsi <= rsi_level and usd_balance >= price * TRADE_AMOUNT:
                    buy_price = price * (1 - PRICE_TOLERANCE)
                    order = client.create_order(
                        client_order_id=f"buy-{int(time.time())}",
                        product_id=PAIR,
                        side='BUY',
                        order_type='LIMIT',
                        limit={'base_size': str(TRADE_AMOUNT), 'limit_price': str(buy_price), 'time_in_force': 'GTC'}
                    )
                    log(f"Buy {TRADE_AMOUNT} BTC at ${buy_price:.2f} (RSI: {rsi:.2f}) | Order: {order['order_id']}")
                    break

            # Sell logic (limit order)
            for rsi_level in SELL_RSI:
                if rsi >= rsi_level and btc_balance >= TRADE_AMOUNT:
                    sell_price = price * (1 + PRICE_TOLERANCE)
                    order = client.create_order(
                        client_order_id=f"sell-{int(time.time())}",
                        product_id=PAIR,
                        side='SELL',
                        order_type='LIMIT',
                        limit={'base_size': str(TRADE_AMOUNT), 'limit_price': str(sell_price), 'time_in_force': 'GTC'}
                    )
                    log(f"Sell {TRADE_AMOUNT} BTC at ${sell_price:.2f} (RSI: {rsi:.2f}) | Order: {order['order_id']}")
                    break

        except Exception as e:
            log(f"Error: {str(e)}")
            await asyncio.sleep(5)  # Retry after delay

        await asyncio.sleep(SLEEP_INTERVAL)

# Run bot
if __name__ == '__main__':
    asyncio.run(main())
