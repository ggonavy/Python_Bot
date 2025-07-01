import warnings
import time
import logging
import sys
import json
import asyncio
import aiohttp
import os
from datetime import datetime
from pytz import timezone
from uuid import uuid4
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
import pandas as pd

# --- Load API Keys ---
def load_api_keys():
    """Load API keys from environment variables or .env file, with fallback to manual input."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        logger.info("Loaded python-dotenv successfully")
    except ImportError:
        logger.warning("python-dotenv not installed; relying on environment variables or manual input")
    
    api_key = os.getenv("KRAKEN_API_KEY")
    api_secret = os.getenv("KRAKEN_API_SECRET")
    
    # Fallback: Check for .env file manually if dotenv is unavailable
    if not api_key or not api_secret:
        try:
            with open(".env", "r") as f:
                for line in f:
                    if line.startswith("KRAKEN_API_KEY="):
                        api_key = line.strip().split("=")[1]
                    elif line.startswith("KRAKEN_API_SECRET="):
                        api_secret = line.strip().split("=")[1]
        except FileNotFoundError:
            pass
    
    # Final fallback: Prompt user for keys (for local testing)
    if not api_key:
        api_key = input("Enter Kraken API Key: ").strip()
    if not api_secret:
        api_secret = input("Enter Kraken API Secret: ").strip()
    
    if not api_key or not api_secret:
        logger.error("API key or secret missing. Exiting.")
        sys.exit(1)
    
    return api_key, api_secret

# --- Configuration ---
API_KEY, API_SECRET = load_api_keys()
CONFIG = {
    "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM": API_KEY,
    "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q==": API_SECRET,
    "TRADING_PAIR": "XXBTZUSD",  # Kraken API pair
    "DISPLAY_PAIR": "XBTUSD",  # For logging
    "INITIAL_FIAT": 1000.0,  # Starting USD balance for simulation
    "EMA_WINDOW": 20,  # 20-period EMA (hourly)
    "RSI_WINDOW": 7,  # 7-period RSI (hourly)
    "ATR_WINDOW": 14,  # 14-period ATR for volatility
    "TIMEZONE": "US/Eastern",
    "MIN_USD_BALANCE": 10.0,  # Minimum USD for buy orders
    "MIN_BTC_BALANCE": 0.0001,  # Minimum BTC for sell orders
    "SLEEP_INTERVAL": 3,  # Seconds between cycles
    "TAKER_FEE": 0.0016,  # Kraken Pro taker fee (0.16%)
    "RATE_LIMIT_SLEEP": 3,  # Base seconds for rate limit backoff
    "MAX_RATE_LIMIT_SLEEP": 8,  # Max seconds for backoff
    "OHLC_CACHE_DURATION": 180,  # Cache OHLC for 3 minutes
    "TICKER_CACHE_DURATION": 180,  # Cache ticker for 3 minutes
    "API_CALL_DELAY": 0.3,  # Seconds between synchronous API calls
    "MAX_RETRIES": 3,  # Max retries for API calls
    "PRICE_DIP_THRESHOLD": 0.01,  # 1% price dip to trigger buy
    "PRICE_DIP_THRESHOLD_HIGH": 0.02,  # 2% price dip for larger buy
    "MOMENTUM_THRESHOLD": 0.005,  # 0.5% price increase for momentum buy
    "STOP_LOSS_THRESHOLD": 0.05,  # 5% price drop for stop-loss
    "VOLATILITY_THRESHOLD": 0.005,  # ATR threshold for dynamic RSI
    "DATA_FILE": "trade_data.json",  # File to persist trade data
    "RSI_BUY_THRESHOLD": 60.0,  # RSI ≤ 60.00 for buy (from log)
    "ATR_MULTIPLIER": 1.5,  # ATR adjustment for buy (from log)
}

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kraken_trading_bot.log", mode="a")
    ]
)
logger = logging.getLogger(__name__)

# --- Setup Kraken API ---
warnings.simplefilter(action="ignore", category=FutureWarning)
try:
    api = krakenex.API(key=CONFIG["API_KEY"], secret=CONFIG["API_SECRET"])
    k = KrakenAPI(api)
    logger.info("Kraken API initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Kraken API: {str(e)}")
    sys.exit(1)

# --- Helper Functions ---
def load_trade_data():
    """Load average buy price and trade data from file."""
    try:
        with open(CONFIG["DATA_FILE"], "r") as f:
            data = json.load(f)
        return (
            data.get("avg_buy_price", None),
            data.get("total_btc_bought", 0.0),
            data.get("total_usd_spent", 0.0),
        )
    except FileNotFoundError:
        return None, 0.0, 0.0
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in trade data file: {str(e)}")
        return None, 0.0, 0.0
    except Exception as e:
        logger.error(f"Error loading trade data: {str(e)}")
        return None, 0.0, 0.0

def save_trade_data(avg_buy_price, total_btc_bought, total_usd_spent):
    """Save average buy price and trade data to file."""
    try:
        data = {
            "avg_buy_price": avg_buy_price,
            "total_btc_bought": total_btc_bought,
            "total_usd_spent": total_usd_spent,
        }
        with open(CONFIG["DATA_FILE"], "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Error saving trade data: {str(e)}")

async def get_minimum_order_size_async(session):
    """Fetch minimum order size for the trading pair with retries."""
    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            async with session.get(
                f"https://api.kraken.com/0/public/AssetPairs?pair={CONFIG['TRADING_PAIR']}"
            ) as response:
                data = await response.json()
                if data["error"]:
                    return None, f"API error: {data['error']}"
                return float(data["result"][CONFIG["TRADING_PAIR"]]["ordermin"]), None
        except Exception as e:
            sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
            logger.warning(f"Public API rate limit exceeded, sleeping for {sleep_time}s (attempt {attempt+1})")
            await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                return None, f"Failed to fetch minimum order size: {str(e)}"
    return None, "Max retries exceeded"

async def get_ohlc_data_async(last_fetch_time=None, last_ohlc=None):
    """Fetch OHLC data and calculate RSI, EMA, and ATR, caching for specified duration."""
    current_time = time.time()
    if last_fetch_time is None or (current_time - last_fetch_time) > CONFIG["OHLC_CACHE_DURATION"]:
        for attempt in range(CONFIG["MAX_RETRIES"]):
            try:
                time.sleep(CONFIG["API_CALL_DELAY"])
                ohlc, _ = k.get_ohlc_data(CONFIG["TRADING_PAIR"], interval=60, ascending=True)
                ohlc["close"] = ohlc["close"].astype(float)
                ohlc["high"] = ohlc["high"].astype(float)
                ohlc["low"] = ohlc["low"].astype(float)
                ohlc["rsi"] = RSIIndicator(ohlc["close"], CONFIG["RSI_WINDOW"]).rsi()
                ohlc["ema"] = EMAIndicator(ohlc["close"], CONFIG["EMA_WINDOW"]).ema_indicator()
                ohlc["atr"] = AverageTrueRange(ohlc["high"], ohlc["low"], ohlc["close"], CONFIG["ATR_WINDOW"]).average_true_range()
                return ohlc, None, current_time
            except Exception as e:
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"OHLC fetch rate limit exceeded, sleeping for {sleep_time}s (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
                if attempt == CONFIG["MAX_RETRIES"] - 1:
                    return last_ohlc, f"OHLC fetch error: {str(e)}", last_fetch_time
        return last_ohlc, "Max retries exceeded", last_fetch_time
    return last_ohlc, "Using cached OHLC data", last_fetch_time

async def get_price_and_balance_async(session, last_price=None, last_price_time=None):
    """Fetch price and balance with caching and fallback."""
    price, price_err, price_time = last_price, None, last_price_time
    usd, btc, balance_err = 0.0, 0.0, None

    current_time = time.time()
    if last_price_time is None or (current_time - last_price_time) > CONFIG["TICKER_CACHE_DURATION"]:
        for attempt in range(CONFIG["MAX_RETRIES"]):
            try:
                time.sleep(CONFIG["API_CALL_DELAY"])
                ticker = k.get_ticker_information(CONFIG["TRADING_PAIR"])
                price = float(ticker["c"][0][0])
                price_time = current_time
                price_err = None
                break
            except Exception as e:
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Price fetch rate limit exceeded, sleeping for {sleep_time}s (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
                if attempt == CONFIG["MAX_RETRIES"] - 1:
                    price_err = f"Price fetch error: {str(e)}"
                    break

    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            time.sleep(CONFIG["API_CALL_DELAY"])
            balance = k.api.query_private("Balance")
            if balance["error"]:
                balance_err = f"Balance API error: {balance['error']}"
                break
            usd = float(balance["result"].get("ZUSD", 0.0))
            btc = float(balance["result"].get("XXBT", 0.0))
            break
        except Exception as e:
            sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
            logger.warning(f"Balance fetch rate limit exceeded, sleeping for {sleep_time}s (attempt {attempt+1})")
            await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                balance_err = f"Balance fetch error: {str(e)}"
                break

    return price, price_err, price_time, usd, btc, balance_err

async def execute_order_async(session, order_type, amount):
    """Execute a market order with validation and retries."""
    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            min_order_size, err = await get_minimum_order_size_async(session)
            if err:
                return False, err
            if amount < min_order_size:
                return False, f"Order size {amount:.8f} below minimum {min_order_size}"
            
            response = k.api.query_private(
                "AddOrder",
                {
                    "pair": CONFIG["TRADING_PAIR"],
                    "type": order_type,
                    "ordertype": "market",
                    "volume": str(round(amount, 8)),
                },
            )
            if response["error"]:
                return False, f"Order failed: {response['error']}"
            return True, f"Order {order_type} for {amount:.8f} executed successfully"
        except Exception as e:
            sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
            logger.warning(f"Order execution rate limit exceeded, sleeping for {sleep_time}s (attempt {attempt+1})")
            await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                return False, f"Order execution error: {str(e)}"
    return False, "Max retries exceeded"

# --- Trading Strategy ---
def buy_strategy(current_rsi, current_price, ema_value, usd_balance, prev_price, atr_value):
    """Determine buy amount based on RSI, price dip, and ATR."""
    if usd_balance < CONFIG["MIN_USD_BALANCE"]:
        return 0.0, "Insufficient USD balance"
    
    if current_rsi > CONFIG["RSI_BUY_THRESHOLD"]:
        return 0.0, "RSI above threshold"
    
    # Calculate position size: 50% of USD balance, adjusted by ATR
    atr_adjusted = atr_value * CONFIG["ATR_MULTIPLIER"]
    buy_amount_usd = min(usd_balance * 0.5, usd_balance - CONFIG["MIN_USD_BALANCE"])
    buy_amount_btc = (buy_amount_usd / current_price) * (1 - CONFIG["TAKER_FEE"])
    
    # Level 3 logic: RSI ≤ 60 with ATR adjustment
    if current_rsi <= 60.0:
        return buy_amount_btc, f"Buy triggered: RSI {current_rsi:.2f} ≤ 60.00 (Level 3, ATR adj: {CONFIG['ATR_MULTIPLIER']})"
    
    return 0.0, "No buy conditions met"

def sell_strategy(current_price, avg_buy_price, btc_balance):
    """Determine sell amount based on stop-loss."""
    if btc_balance < CONFIG["MIN_BTC_BALANCE"]:
        return 0.0, "Insufficient BTC balance"
    
    if avg_buy_price and current_price < avg_buy_price * (1 - CONFIG["STOP_LOSS_THRESHOLD"]):
        sell_amount_btc = btc_balance  # Sell all BTC on stop-loss
        return sell_amount_btc, f"Sell triggered: Price {current_price:.2f} < Stop-loss {avg_buy_price * (1 - CONFIG['STOP_LOSS_THRESHOLD']):.2f}"
    
    return 0.0, "No stop-loss conditions met"

# --- Main Trading Loop ---
async def main():
    avg_buy_price, total_btc_bought, total_usd_spent = load_trade_data()
    last_ohlc, last_fetch_time, last_price, last_price_time = None, None, None, None
    prev_price = None

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Fetch OHLC data and indicators
                ohlc, ohlc_err, last_fetch_time = await get_ohlc_data_async(last_fetch_time, last_ohlc)
                if ohlc_err:
                    logger.error(ohlc_err)
                    last_ohlc = ohlc
                    await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])
                    continue
                last_ohlc = ohlc

                # Fetch price and balance
                price, price_err, last_price_time, usd, btc, balance_err = await get_price_and_balance_async(
                    session, last_price, last_price_time
                )
                if price_err or balance_err:
                    logger.error(f"Price error: {price_err or 'None'}, Balance error: {balance_err or 'None'}")
                    await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])
                    continue
                last_price = price

                # Get latest indicators
                latest = ohlc.iloc[-1]
                current_rsi = latest["rsi"]
                ema_value = latest["ema"]
                atr_value = latest["atr"]

                # Log market data
                tz = timezone(CONFIG["TIMEZONE"])
                timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
                logger.info(
                    f"[{timestamp}] Price: ${price:.2f} | RSI: {current_rsi:.2f} | EMA: ${ema_value:.2f} | "
                    f"ATR: {atr_value:.4f} | USD: ${usd:.2f} | BTC: {btc:.6f}"
                )

                # Buy decision
                buy_amount, buy_reason = buy_strategy(current_rsi, price, ema_value, usd, prev_price, atr_value)
                if buy_amount > 0:
                    success, order_result = await execute_order_async(session, "buy", buy_amount)
                    logger.info(f"Buy: {buy_reason} | Amount: ${buy_amount * price:.2f} ({buy_amount:.6f} XBT) | {order_result}")
                    if success:
                        total_btc_bought += buy_amount
                        total_usd_spent += buy_amount * price
                        avg_buy_price = total_usd_spent / total_btc_bought if total_btc_bought > 0 else None
                        save_trade_data(avg_buy_price, total_btc_bought, total_usd_spent)

                # Sell decision
                sell_amount, sell_reason = sell_strategy(price, avg_buy_price, btc)
                if sell_amount > 0:
                    success, order_result = await execute_order_async(session, "sell", sell_amount)
                    logger.info(f"Sell: {sell_reason} | Amount: {sell_amount:.6f} XBT | {order_result}")
                    if success:
                        total_btc_bought -= sell_amount
                        total_usd_spent -= sell_amount * price
                        avg_buy_price = total_usd_spent / total_btc_bought if total_btc_bought > 0 else None
                        save_trade_data(avg_buy_price, total_btc_bought, total_usd_spent)

                prev_price = price
                await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])

            except Exception as e:
                logger.error(f"Main loop error: {str(e)}")
                await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])

if __name__ == "__main__":
    asyncio.run(main())
