import os
import time
import ccxt
import pandas as pd
import logging
from flask import Flask, jsonify
from ta.momentum import RSIIndicator
from threading import Thread

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask app for Render health checks
app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

# Coinbase API setup
def init_exchange():
    try:
        api_key = os.getenv('COINBASE_API_KEY')
        api_secret = os.getenv('COINBASE_API_SECRET')
        passphrase = os.getenv('COINBASE_PASSPHRASE')
        if not all([api_key, api_secret, passphrase]):
            logger.error("Missing API credentials")
            raise ValueError("API credentials not set")
        exchange = ccxt.coinbase({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True
        })
        logger.info("Coinbase exchange initialized")
        return exchange
    except Exception as e:
        logger.error(f"Failed to initialize exchange: {str(e)}")
        raise

# Fetch OHLCV data
def fetch_ohlcv(exchange, symbol, timeframe='5m', limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        logger.info(f"Fetched {len(df)} OHLCV candles for {symbol}")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch OHLCV for {symbol}: {str(e)}")
        return None

# Calculate RSI
def calculate_rsi(df, period=14):
    try:
        rsi = RSIIndicator(df['close'], period).rsi()
        logger.info(f"Calculated RSI for {df['timestamp'].iloc[-1]}: {rsi.iloc[-1]:.2f}")
        return rsi
    except Exception as e:
        logger.error(f"Failed to calculate RSI: {str(e)}")
        return None

# Trading logic for a single symbol
def trading_logic(exchange, symbol, fiat_limit, rsi_levels):
    try:
        # Fetch market data
        df = fetch_ohlcv(exchange, symbol)
        if df is None or df.empty:
            logger.error(f"No OHLCV data for {symbol}, skipping trade")
            return False

        # Calculate RSI
