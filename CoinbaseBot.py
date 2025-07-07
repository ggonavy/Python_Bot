import ccxt.async_support as ccxt
import pandas as pd
import time
import os
import asyncio
from datetime import datetime

# Load API credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')
api_passphrase = os.getenv('COINBASE_PASSPHRASE')

# Initialize Coinbase client
client = ccxt.coinbase({
    'apiKey': api_key,
    'secret': api_secret,
    'password': api_passphrase,
    'enableRateLimit': True
})

# Trading parameters
PAIR = 'BTC/USD'  # ccxt uses BTC/USD
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
async def get_rsi(pair, period=RSI_PERIOD):
    candles = await client.fetch_ohlcv(pair, timeframe='5m', limit=period + 1)
    df = pd.DataFrame(candles, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
    df['close'] = df['close'].astype(float)
    df = df.sort_values('time', ascending=True)
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
        self.ws = client

    async def subscribe(self, pair):
        while True:
            try:
                ticker = await self.ws.fetch_ticker(pair)
                self.latest_price = float(ticker['last'])
                log(f"WebSocket Price: ${self.latest_price:.2f}")
                await asyncio.sleep(5)
            except Exception as e:
                log(f"WebSocket Error: {str(e)}")
                await asyncio.sleep(5)

    def get_price(self):
        return self.latest_price

# Main trading loop
async def main():
    price_feed = PriceFeed()
    asyncio.create_task(price_feed.subscribe(PAIR))

    while True:
        try:
            # Get RSI and price
            rsi, _ = await get_rsi(PAIR)
            price = price_feed.get_price()
            if not price:
                log("Waiting for WebSocket price...")
                await asyncio.sleep(5)
                continue
            log(f"Price: ${price:.2f} | RSI: {rsi:.2f}")

            # Get balances
            balance = await client.fetch_balance()
            btc_balance = float(balance['BTC']['free'])
            usd_balance = float(balance['USD']['free'])
            log(f"BTC: {btc_balance:.6f} | USD: ${usd_balance:.2f}")

            # Buy logic (limit order)
            for rsi_level in BUY_RSI:
                if rsi <= rsi_level and usd_balance >= price * TRADE_AMOUNT:
                    buy_price = price * (1 - PRICE_TOLERANCE)
                    order = await client.create_limit_buy_order(
                        symbol=PAIR,
                        amount=TRADE_AMOUNT,
                        price=buy_price
                    )
                    log(f"Buy {TRADE_AMOUNT} BTC at ${buy_price:.2f} (RSI: {rsi:.2f}) | Order: {order['id']}")
                    break

            # Sell logic (limit order)
            for rsi_level in SELL_RSI:
                if rsi >= rsi_level and btc_balance >= TRADE_AMOUNT:
                    sell_price = price * (1 + PRICE_TOLERANCE)
                    order = await client.create_limit_sell_order(
                        symbol=PAIR,
                        amount=TRADE_AMOUNT,
                        price=sell_price
                    )
                    log(f"Sell {TRADE_AMOUNT} BTC at ${sell_price:.2f} (RSI: {rsi:.2f}) | Order: {order['id']}")
                    break

        except Exception as e:
            log(f"Error: {str(e)}")
            await asyncio.sleep(5)  # Retry after delay

        await asyncio.sleep(SLEEP_INTERVAL)

# Run bot
if __name__ == '__main__':
    asyncio.run(main())
