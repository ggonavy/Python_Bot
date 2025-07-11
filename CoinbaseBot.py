import ccxt
import time
import os
import hmac
import hashlib
import base64
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', force=True)
logger = logging.getLogger(__name__)

# Environment variables
API_KEY = os.getenv('COINBASE_API_KEY')
API_SECRET = os.getenv('COINBASE_API_SECRET')
PASSPHRASE = os.getenv('COINBASE_PASSPHRASE')

# Initialize exchange
try:
    exchange = ccxt.coinbase({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'password': PASSPHRASE,
        'enableRateLimit': True
    })
    logger.info("Exchange initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize exchange: {e}")
    sys.exit(1)

# Trading parameters
SYMBOL = 'BTC-USD'
QUOTE_AMOUNT = 0.1675 * 0.8  # 80% of 0.1675 BTC
ETH_QUOTE_AMOUNT = 0.1675 * 0.2  # 20% in ETH
RSI_BUY_LEVELS = [47, 42, 37, 32]
RSI_SELL_LEVELS = [73, 77, 81, 85]
POSITION_SIZES = [0.15, 0.20, 0.25, 0.40]  # % of quote amount
TIMEFRAME = '1h'
RSI_PERIOD = 14

# HTTP server to satisfy Render
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def do_HEAD(self):  # Handle HEAD requests
        self.send_response(200)
        self.end_headers()

def start_server():
    server = HTTPServer(('0.0.0.0', int(os.getenv('PORT', 8000))), SimpleHTTPRequestHandler)
    logger.info("Starting HTTP server")
    server.serve_forever()

def calculate_rsi(data, periods=14):
    close_prices = [float(candle[4]) for candle in data]
    gains = []
    losses = []
    for i in range(1, len(close_prices)):
        diff = close_prices[i] - close_prices[i-1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    
    avg_gain = sum(gains[:periods]) / periods
    avg_loss = sum(losses[:periods]) / periods
    
    for i in range(periods, len(gains)):
        avg_gain = (avg_gain * (periods - 1) + gains[i]) / periods
        avg_loss = (avg_loss * (periods - 1) + losses[i]) / periods
    
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
    rsi = 100 - (100 / (1 + rs))
    return rsi

def trading_loop():
    logger.info(f"Starting bot at {datetime.now()}")
    while True:
        try:
            # Fetch OHLCV data
            logger.info("Fetching OHLCV data")
            ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=RSI_PERIOD + 1)
            rsi = calculate_rsi(ohlcv, RSI_PERIOD)
            logger.info(f"RSI: {rsi:.2f}")

            # Get current price and balance
            logger.info("Fetching ticker and balance")
            ticker = exchange.fetch_ticker(SYMBOL)
            price = ticker['last']
            balance = exchange.fetch_balance()
            usd_balance = balance['USD']['free']
            btc_balance = balance['BTC']['free']
            logger.info(f"Price: {price:.2f}, USD: {usd_balance:.2f}, BTC: {btc_balance:.6f}")

            # Trading logic
            for i, (buy_level, sell_level, size) in enumerate(zip(RSI_BUY_LEVELS, RSI_SELL_LEVELS, POSITION_SIZES)):
                trade_amount = QUOTE_AMOUNT * size / price
                if rsi <= buy_level and usd_balance >= QUOTE_AMOUNT * size:
                    logger.info(f"Buying {trade_amount:.6f} BTC at {price:.2f} (RSI: {rsi:.2f})")
                    exchange.create_market_buy_order(SYMBOL, trade_amount)
                elif rsi >= sell_level and btc_balance >= trade_amount:
                    logger.info(f"Selling {trade_amount:.6f} BTC at {price:.2f} (RSI: {rsi:.2f})")
                    exchange.create_market_sell_order(SYMBOL, trade_amount)

            # ETH allocation
            eth_symbol = 'ETH-USD'
            eth_ticker = exchange.fetch_ticker(eth_symbol)
            eth_price = eth_ticker['last']
            eth_amount = ETH_QUOTE_AMOUNT / eth_price
            if rsi <= RSI_BUY_LEVELS[0] and usd_balance >= ETH_QUOTE_AMOUNT:
                logger.info(f"Buying {eth_amount:.6f} ETH at {eth_price:.2f}")
                exchange.create_market_buy_order(eth_symbol, eth_amount)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
        
        time.sleep(3600)  # Wait 1 hour

def main():
    # Start HTTP server in a separate thread
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Run trading loop
    trading_loop()

if __name__ == "__main__":
    main()
