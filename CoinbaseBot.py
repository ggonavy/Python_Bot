from coinbase.rest import RESTClient
import os
import pandas as pd
from ta.momentum import RSIIndicator
import time
import logging
from datetime import datetime, timedelta
from flask import Flask
import threading
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Coinbase client
api_key_name = os.getenv("COINBASE_API_KEY_NAME")
api_private_key = os.getenv("COINBASE_PRIVATE_KEY")

client = None
try:
    client = RESTClient(key=api_key_name, secret=api_private_key)
    logger.info("Coinbase client initialized")
except Exception as e:
    logger.error(f"Failed to initialize client: {e}")

def get_market_data(product_id="BTC-USD", limit=100):
    if client is None:
        logger.error("No Coinbase client available")
        return None
    try:
        end = int(datetime.now().timestamp())
        start = end - (limit * 900)
        candles = client.get_candles(product_id=product_id, granularity=900, start=str(start), end=str(end))
        if not candles or "candles" not in candles:
            logger.error("No candles returned")
            return None
        df = pd.DataFrame(candles["candles"], columns=["start", "low", "high", "open", "close", "volume"])
        df["close"] = df["close"].astype(float)
        df["start"] = pd.to_datetime(df["start"], unit="s")
        logger.info(f"Fetched {len(df)} candles for {product_id}")
        return df
    except Exception as e:
        logger.error(f"Error fetching market data: {e}")
        if "429" in str(e):
            logger.warning("Rate limit hit, sleeping 10s")
            time.sleep(10)
        return None

def trade_logic():
    while True:
        df = get_market_data()
        if df is None or len(df) < 14:
            logger.warning("Not enough data for RSI")
            time.sleep(900)
            continue

        try:
            rsi = RSIIndicator(df["close"], window=14).rsi()
            latest_rsi = rsi.iloc[-1]
            logger.info(f"Latest RSI: {latest_rsi}")
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}")
            time.sleep(60)
            continue

        try:
            accounts = client.get_accounts()
            btc_account = next((acc for acc in accounts["accounts"] if acc["currency"] == "BTC"), None)
            usd_account = next((acc for acc in accounts["accounts"] if acc["currency"] == "USD"), None)
            if not btc_account or not usd_account:
                logger.error("BTC or USD account not found")
                time.sleep(60)
                continue
            btc_balance = float(btc_account["available_balance"]["value"])
            usd_balance = float(usd_account["available_balance"]["value"])
            logger.info(f"BTC balance: {btc_balance}, USD balance: {usd_balance}")
        except Exception as e:
            logger.error(f"Error fetching balances: {e}")
            time.sleep(60)
            continue

        trade_size_btc = 0.1675
        price = float(df["close"].iloc[-1])
        buy_signals = [47, 42, 37, 32]
        sell_signals = [73, 77, 81, 85]

        if any(latest_rsi <= signal for signal in buy_signals) and usd_balance > trade_size_btc * price:
            try:
                order = client.market_order_buy(product_id="BTC-USD", quote_size=f"{trade_size_btc * price:.2f}")
                logger.info(f"Buy order placed: {order}")
            except Exception as e:
                logger.error(f"Buy order error: {e}")
        elif any(latest_rsi >= signal for signal in sell_signals) and btc_balance >= trade_size_btc:
            try:
                order = client.market_order_sell(product_id="BTC-USD", base_size=f"{trade_size_btc:.8f}")
                logger.info(f"Sell order placed: {order}")
            except Exception as e:
                logger.error(f"Sell order error: {e}")

        logger.info("Sleeping for 15 minutes")
        time.sleep(900)

# Flask routes
@app.route('/')
def index():
    return "Bot is running", 200

@app.route('/health')
def health():
    return "Bot is running", 200

# Start trading logic in background thread
if __name__ == "__main__":
    threading.Thread(target=trade_logic, daemon=True).start()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
