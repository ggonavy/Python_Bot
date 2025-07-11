import os
import time
import ccxt
import pandas as pd
import logging
from flask import Flask, jsonify
from ta.momentum import RSIIndicator
from threading import Thread
import hmac
import hashlib
import base64

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler('coinbase_bot.log'),
    logging.StreamHandler()
])
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
            'enableRateLimit': True,
            'rateLimit': 100
        })
        # Override sign method for Coinbase API authentication
        def custom_sign(self, path, api='public', method='GET', params={}, headers=None, body=None):
            request = '/' + path
            timestamp = str(int(time.time()))
            message = timestamp + method + request + (body or '')
            signature = hmac.new(
                self.secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            headers = {
                'CB-ACCESS-KEY': self.apiKey,
                'CB-ACCESS-SIGN': signature,
                'CB-ACCESS-TIMESTAMP': timestamp,
                'CB-ACCESS-PASSPHRASE': self.password,
                'Content-Type': 'application/json',
                'User-Agent': 'ccxt/' + ccxt.__version__,
                'Accept': 'application/json'
            }
            return {'url': self.urls['api'][api] + request, 'method': method, 'body': body, 'headers': headers}
        exchange.sign = custom_sign.__get__(exchange, ccxt.coinbase)
        # Test authentication with public endpoint
        exchange.publicGetProducts()
        exchange.load_markets()
        logger.info("Coinbase exchange initialized")
        return exchange
    except Exception as e:
        logger.error(f"Failed to initialize exchange: {str(e)}")
        raise

# Fetch OHLCV data with retry
def fetch_ohlcv(exchange, symbol, timeframe='5m', limit=100, retries=5, delay=10):
    try:
        symbol = symbol.replace('/', '-')  # Convert BTC/USD to BTC-USD
        for attempt in range(retries):
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                if not ohlcv:
                    logger.error(f"No OHLCV data returned for {symbol} on attempt {attempt+1}")
                    if attempt < retries - 1:
                        time.sleep(delay)
                        continue
                    return None
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                if df.empty or len(df) < limit:
                    logger.error(f"Insufficient OHLCV data for {symbol} on attempt {attempt+1}")
                    if attempt < retries - 1:
                        time.sleep(delay)
                        continue
                    return None
                logger.info(f"Fetched {len(df)} OHLCV candles for {symbol}")
                return df
            except Exception as e:
                logger.error(f"Failed to fetch OHLCV for {symbol} on attempt {attempt+1}: {str(e)}")
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
        logger.error(f"Failed to fetch OHLCV for {symbol} after {retries} attempts")
        return None
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
        rsi = calculate_rsi(df)
        if rsi is None:
            logger.error(f"No RSI data for {symbol}, skipping trade")
            return False
        current_rsi = rsi.iloc[-1]
        current_price = df['close'].iloc[-1]

        # Get account balance
        balance = exchange.fetch_balance()
        base = symbol.split('/')[0]  # BTC or ETH
        quote = symbol.split('/')[1]  # USD
        usd_balance = balance[quote]['free'] if quote in balance else 0
        asset_balance = balance[base]['free'] if base in balance else 0
        logger.info(f"{symbol} - USD: {usd_balance:.2f}, {base}: {asset_balance:.6f}, RSI: {current_rsi:.2f}, Price: {current_price:.2f}")

        # Check RSI buy/sell levels
        for rsi_level, amount in rsi_levels['buy'].items():
            amount_usd = amount * current_price
            if current_rsi <= rsi_level and usd_balance >= amount_usd and usd_balance >= fiat_limit:
                try:
                    order = exchange.create_market_buy_order(symbol.replace('/', '-'), amount)
                    logger.info(f"Buy {amount:.6f} {base} at {current_price:.2f} (RSI: {current_rsi:.2f})")
                    return True
                except Exception as e:
                    logger.error(f"Buy order failed for {symbol} at RSI {rsi_level}: {str(e)}")
        for rsi_level, amount in rsi_levels['sell'].items():
            if current_rsi >= rsi_level and asset_balance >= amount:
                try:
                    order = exchange.create_market_sell_order(symbol.replace('/', '-'), amount)
                    logger.info(f"Sell {amount:.6f} {base} at {current_price:.2f} (RSI: {current_rsi:.2f})")
                    return True
                except Exception as e:
                    logger.error(f"Sell order failed for {symbol} at RSI {rsi_level}: {str(e)}")
        logger.info(f"No trade for {symbol}: RSI {current_rsi:.2f} not at trigger level")
        return False
    except Exception as e:
        logger.error(f"Trading logic failed for {symbol}: {str(e)}")
        return False

# Main trading loop
def trading_bot():
    exchange = init_exchange()
    configs = [
        {
            'symbol': 'BTC/USD',
            'fiat_limit': 2880,  # Minimum USD for smallest buy
            'rsi_levels': {
                'buy': {47: 0.02330, 42: 0.03107, 37: 0.03884, 32: 0.06214},
                'sell': {73: 0.02330, 77: 0.03107, 81: 0.03884, 85: 0.06214}
            }
        },
        {
            'symbol': 'ETH/USD',
            'fiat_limit': 720,  # Minimum USD for smallest buy
            'rsi_levels': {
                'buy': {47: 0.16000, 42: 0.21333, 37: 0.26667, 32: 0.42667},
                'sell': {73: 0.16000, 77: 0.21333, 81: 0.26667, 85: 0.42667}
            }
        }
    ]
    while True:
        try:
            # Prioritize BTC, allow ETH if no BTC trade
            btc_traded = trading_logic(exchange, configs[0]['symbol'], configs[0]['fiat_limit'], configs[0]['rsi_levels'])
            if not btc_traded:
                trading_logic(exchange, configs[1]['symbol'], configs[1]['fiat_limit'], configs[1]['rsi_levels'])
            logger.info("Sleeping for 30 seconds")
            time.sleep(30)
        except Exception as e:
            logger.error(f"Main loop error: {str(e)}")
            time.sleep(30)

if __name__ == '__main__':
    # Start trading bot in a separate thread
    Thread(target=trading_bot).start()
    # Run Flask app
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)), debug=False)
