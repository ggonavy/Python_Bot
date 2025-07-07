import ccxt.async_support as ccxt
import pandas as pd
import asyncio
import os
import base64
from datetime import datetime
from aiohttp import web

# Load API credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')
api_passphrase = os.getenv('COINBASE_PASSPHRASE')
port = int(os.getenv('PORT', 8000))

# Validate credentials
def validate_credentials():
    if not all([api_key, api_secret, api_passphrase]):
        log("Error: Missing API credentials")
        exit(1)
    try:
        # Validate base64 secret
        base64.b64decode(api_secret, validate=True)
    except Exception as e:
        log(f"Error: Invalid COINBASE_API_SECRET format: {str(e)}")
        exit(1)
    if not (30 <= len(api_key) <= 40):
        log(f"Error: COINBASE_API_KEY length invalid ({len(api_key)})")
        exit(1)
    if not (40 <= len(api_secret) <= 50):
        log(f"Error: COINBASE_API_SECRET length invalid ({len(api_secret)})")
        exit(1)

# Logging
def log(message):
    print(f"{datetime.now()}: {message}")

# Initialize Coinbase client
validate_credentials()
try:
    client = ccxt.coinbase({
        'apiKey': api_key,
        'secret': api_secret,
        'password': api_passphrase,
        'enableRateLimit': True
    })
except Exception as e:
    log(f"Error initializing client: {str(e)}")
    exit(1)

# Trading parameters
PAIR = 'BTC/USD'
RSI_PERIOD = 14
BUY_RSI = [47, 42, 37, 32]
SELL_RSI = [73, 77, 81, 85]
SLEEP_INTERVAL = 60  # seconds
TRADE_AMOUNT = 0.01675  # ~1/10th of 0.1675 BTC
PRICE_TOLERANCE = 0.005  # 0.5% price slippage for limit orders

# Get historical data for RSI
async def get_rsi(pair, period=RSI_PERIOD):
    try:
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
    except Exception as e:
        log(f"RSI Error: {str(e)}")
        return None, None

# WebSocket for real-time price
class PriceFeed:
    def __init__(self):
        self.latest_price = None
        self.running = True

    async def subscribe(self, pair, exchange):
        while self.running:
            try:
                ticker = await exchange.fetch_ticker(pair)
                self.latest_price = float(ticker['last'])
                log(f"Price: ${self.latest_price:.2f}")
                await asyncio.sleep(5)
            except Exception as e:
                log(f"Price Error: {str(e)}")
                await asyncio.sleep(5)

    def get_price(self):
        return self.latest_price

    def stop(self):
        self.running = False

# Minimal HTTP server for Render
async def handle_health_check(request):
    return web.Response(text="Bot is running")

async def start_server():
    try:
        app = web.Application()
        app.add_routes([web.get('/', handle_health_check)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        log(f"HTTP server started on port {port}")
    except Exception as e:
        log(f"HTTP Server Error: {str(e)}")

# Main trading loop
async def main():
    price_feed = PriceFeed()
    price_task = asyncio.create_task(price_feed.subscribe(PAIR, client))
    server_task = asyncio.create_task(start_server())

    try:
        while True:
            try:
                # Get RSI
                rsi, _ = await get_rsi(PAIR)
                if rsi is None:
                    log("Skipping trade due to RSI fetch error")
                    await asyncio.sleep(5)
                    continue

                # Get price
                price = price_feed.get_price()
                if not price:
                    log("Waiting for price...")
                    await asyncio.sleep(5)
                    continue
                log(f"RSI: {rsi:.2f}")

                # Get balances
                balance = await client.fetch_balance()
                btc_balance = float(balance.get('BTC', {}).get('free', 0))
                usd_balance = float(balance.get('USD', {}).get('free', 0))
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
                await asyncio.sleep(5)

            await asyncio.sleep(SLEEP_INTERVAL)

    finally:
        price_feed.stop()
        await client.close_connection()

# Run bot and server
if __name__ == '__main__':
    asyncio.run(main())
