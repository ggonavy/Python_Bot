import os
import logging
import time
from flask import Flask
from coinbase import RESTClient
from dotenv import load_dotenv
import pandas as pd
import numpy as np

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Health endpoint for Render
@app.route('/health')
def health():
    return {"status": "ok"}, 200

# Coinbase API client setup
try:
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    if not api_key or not api_secret:
        logging.error("API_KEY or API_SECRET not set in environment variables")
        raise ValueError("Missing API credentials")
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    logging.info("Coinbase client initialized")
except Exception as e:
    logging.error(f"Failed to initialize Coinbase client: {e}")
    raise

# RSI calculation
def calculate_rsi(data, periods=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# Trading logic
def trade():
    try:
        # Fetch market data (BTC-USD, last 100 trades)
        trades = client.get_market_trades(product_id="BTC-USD", limit=100)
        prices = [float(trade["price"]) for trade in trades["trades"]]
        df = pd.DataFrame(prices, columns=["price"])
        
        # Calculate RSI
        rsi = calculate_rsi(df["price"])
        current_rsi = rsi.iloc[-1]
        logging.info(f"Current RSI: {current_rsi}")

        # Trading logic (example: buy if RSI < 30, sell if RSI > 70)
        account = client.get_accounts()[0]  # Assumes first account
        btc_balance = float(account["available_balance"]["value"])
        usd_balance = float(account["available_balance"]["value"])
        current_price = float(client.get_product("BTC-USD")["price"])

        if current_rsi < 30 and usd_balance > 10:
            # Buy ~0.1675 BTC
            amount = 0.1675
            client.place_market_order(
                product_id="BTC-USD",
                side="BUY",
                quote_size=str(amount * current_price)
            )
            logging.info(f"Buy order placed: {amount} BTC at ${current_price}")
        elif current_rsi > 70 and btc_balance >= 0.1675:
            # Sell ~0.1675 BTC
            client.place_market_order(
                product_id="BTC-USD",
                side="SELL",
                base_size="0.1675"
            )
            logging.info(f"Sell order placed: 0.1675 BTC at ${current_price}")
        else:
            logging.info("No trade: RSI or balance conditions not met")

    except Exception as e:
        logging.error(f"Error in trade loop: {e}")

# Main loop
if __name__ == "__main__":
    # Test API connectivity
    try:
        accounts = client.get_accounts()
        logging.info(f"API test successful: {len(accounts)} accounts found")
    except Exception as e:
        logging.error(f"Test API call failed: {e}")
        raise

    # Run Flask app and trading loop
    from threading import Thread
    def run_trading_loop():
        while True:
            trade()
            time.sleep(60)  # Check every minute
    Thread(target=run_trading_loop).start()
    app.run(host="0.0.0.0", port=8080)
