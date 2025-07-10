from flask import Flask, jsonify
from coinbase_advanced.client import CoinbaseAdvancedTradeClient
import os
import time
import logging
import pandas as pd
from ta.momentum import RSIIndicator
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Coinbase API credentials
API_KEY = os.getenv('COINBASE_API_KEY')
API_SECRET = os.getenv('COINBASE_API_SECRET')
API_PASSPHRASE = os.getenv('COINBASE_PASSPHRASE')

# Initialize Coinbase Advanced Trade client
client = CoinbaseAdvancedTradeClient(
    api_key=API_KEY,
    secret_key=API_SECRET,
    passphrase=API_PASSPHRASE
)

# Health check endpoint
@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def fetch_ohlcv(symbol, timeframe='1h', limit=100):
    """Fetch OHLCV data from Coinbase."""
    try:
        candles = client.get_candles(
            product_id=symbol,
            granularity='ONE_HOUR',  # 1 hour
            limit=limit
        )
        # Convert candles to DataFrame
        df = pd.DataFrame(candles, columns=['timestamp', 'low', 'high', 'open', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {str(e)}")
        return None

def trading_bot():
    symbols = ['BTC-USD', 'ETH-USD']
    timeframe = '1h'
    rsi_period = 14
    buy_ladder = [47, 42, 37, 32]
    sell_ladder = [73, 77, 81, 85]
    btc_amount = 0.1675  # BTC amount to trade
    eth_amount = 0.5     # ETH amount to trade

    while True:
        for symbol in symbols:
            try:
                # Fetch OHLCV data
                df = fetch_ohlcv(symbol, timeframe)
                if df is None or df.empty:
                    logger.error(f"No data for {symbol}, skipping...")
                    continue
                
                # Calculate RSI using ta
                rsi = RSIIndicator(close=df['close'], window=rsi_period)
                df['rsi'] = rsi.rsi()
                
                current_rsi = df['rsi'].iloc[-1]
                current_price = df['close'].iloc[-1]
                
                logger.info(f"{symbol} | Price: {current_price:.2f} | RSI: {current_rsi:.2f}")
                
                # Trading logic
                amount = btc_amount if symbol == 'BTC-USD' else eth_amount
                
                for buy_rsi in buy_ladder:
                    if current_rsi <= buy_rsi:
                        logger.info(f"{symbol} RSI {current_rsi:.2f} <= {buy_rsi}, buying...")
                        client.place_market_order(
                            product_id=symbol,
                            side='BUY',
                            base_size=str(amount)
                        )
                        break
                
                for sell_rsi in sell_ladder:
                    if current_rsi >= sell_rsi:
                        logger.info(f"{symbol} RSI {current_rsi:.2f} >= {sell_rsi}, selling...")
                        client.place_market_order(
                            product_id=symbol,
                            side='SELL',
                            base_size=str(amount)
                        )
                        break
                
            except Exception as e:
                logger.error(f"Error in trading loop for {symbol}: {str(e)}")
                
        time.sleep(3600)  # Wait for 1 hour

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
