from coinbase.rest import RESTClient
import os
import pandas as pd
from ta.momentum import RSIIndicator
import time
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

try:
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    logger.info("Coinbase client initialized")
except Exception as e:
    logger.error(f"Failed to initialize client: {e}")
    exit(1)

def get_market_data(product_id="BTC-USD", limit=100):
    try:
        # Calculate start and end timestamps (Unix epoch in seconds)
        end = int(datetime.now().timestamp())
        start = end - (limit * 900)  # 15m candles (900s) for limit candles
        candles = client.get_candles(product_id=product_id, granularity=900, start=str(start), end=str(end))
        df = pd.DataFrame(candles["candles"], columns=["start", "low", "high", "open", "close", "volume"])
        df["close"] = df["close"].astype(float)
        df["start"] = pd.to_datetime(df["start"], unit="s")
        logger.info(f"Fetched {len(df)} candles for {product_id}")
        return df
    except Exception as e:
        logger.error(f"Error fetching market data: {e}")
        return None

def trade_logic():
    df = get_market_data()
    if df is None or len(df) < 14:
        logger.warning("Not enough data for RSI")
        return

    try:
        rsi = RSIIndicator(df["close"], window=14).rsi()
        latest_rsi = rsi.iloc[-1]
        logger.info(f"Latest RSI: {latest_rsi}")
    except Exception as e:
        logger.error(f"Error calculating RSI: {e}")
        return

    try:
        accounts = client.get_accounts()
        btc_account = next((acc for acc in accounts["accounts"] if acc["currency"] == "BTC"), None)
        usd_account = next((acc for acc in accounts["accounts"] if acc["currency"] == "USD"), None)
        btc_balance = float(btc_account["available_balance"]["value"]) if btc_account else 0
        usd_balance = float(usd_account["available_balance"]["value"]) if usd_account else 0
        logger.info(f"BTC balance: {btc_balance}, USD balance: {usd_balance}")
    except Exception as e:
        logger.error(f"Error fetching balances: {e}")
        return

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

if __name__ == "__main__":
    while True:
        try:
            trade_logic()
            logger.info("Sleeping for 15 minutes")
            time.sleep(900)
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(60)
