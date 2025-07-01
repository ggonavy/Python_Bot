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
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
import pandas as pd
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()
API_KEY = os.getenv("haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM")
API_SECRET = os.getenv("MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q==")

# --- Configuration ---
CONFIG = {
    "API_KEY": API_KEY,
    "API_SECRET": API_SECRET,
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
    print(f"Error: Failed to initialize Kraken API: {str(e)}")
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
            if "rate limit" in str(e).lower() or "eapi" in str(e).lower():
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Public API rate limit exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                return None, f"Failed to fetch minimum order size after {CONFIG['MAX_RETRIES']} attempts: {str(e)}"
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
                if "rate limit" in str(e).lower() or "eapi" in str(e).lower():
                    sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                    logger.warning(f"Public API rate limit exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                    await asyncio.sleep(sleep_time)
                if attempt == CONFIG["MAX_RETRIES"] - 1:
                    return last_ohlc, f"Data fetch error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}", last_fetch_time
        return last_ohlc, "Max retries exceeded", last_fetch_time
    return last_ohlc, "Using cached OHLC data", last_fetch_time

async def get_price_and_balance_async(session, last_price=None, last_price_time=None):
    """Batch fetch price and balance with fallback to synchronous call."""
    price, price_err, price_time = last_price, None, last_price_time
    usd, btc, balance_err = 0.0, 0.0, None

    current_time = time.time()
    if last_price_time is None or (current_time - last_price_time) > CONFIG["TICKER_CACHE_DURATION"]:
        for attempt in range(CONFIG["MAX_RETRIES"]):
            try:
                async with session.get(
                    f"https://api.kraken.com/0/public/Ticker?pair={CONFIG['TRADING_PAIR']}"
                ) as response:
                    data = await response.json()
                    if data["error"]:
                        price_err = f"API error: {data['error']}"
                        break
                    price = float(data["result"][CONFIG["TRADING_PAIR"]]["c"][0])
                    price_time = current_time
                    price_err = None
                    break
            except Exception as e:
                price_err = f"Async price fetch error: {str(e)}"
                if "rate limit" in str(e).lower() or "eapi" in str(e).lower():
                    sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                    logger.warning(f"Public API rate limit exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                    await asyncio.sleep(sleep_time)
                if attempt == CONFIG["MAX_RETRIES"] - 1:
                    price_err = f"Async price fetch failed after {CONFIG['MAX_RETRIES']} attempts: {str(e)}"
                    break

        if price_err:
            try:
                time.sleep(CONFIG["API_CALL_DELAY"])
                ticker = k.get_ticker_information(CONFIG["TRADING_PAIR"])
                price = float(ticker["c"][0][0])
                price_time = current_time
                price_err = None
                logger.info("Price fetch fallback to synchronous call successful")
            except Exception as e:
                price_err = f"Synchronous price fetch failed: {str(e)}"

    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            time.sleep(CONFIG["API_CALL_DELAY"])
            balance = k.get_account_balance()
            usd = float(balance.loc["ZUSD"]["vol"]) if "ZUSD" in balance.index else 0.0
            btc = float(balance.loc["XXBT"]["vol"]) if "XXBT" in balance.index else 0.0
            break
        except Exception as e:
            if "rate limit" in str(e).lower() or "eapi" in str(e).lower():
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Private API rate limit exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                balance_err = f"Balance fetch error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}"
                break

    return price, price_err, price_time, usd, btc, balance_err

async def execute_order_async(order_type, amount):
    """Execute a market order with validation and retries."""
    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            async with aiohttp.ClientSession() as session:
                min_order_size, err = await get_minimum_order_size_async(session)
                if err:
                    return False, err
                if amount < min_order_size:
                    return False, f"Order size {amount:.8f} below minimum {min_order_size}"
                
                time.sleep(CONFIG["API_CALL_DELAY"])
                response = api.query_private(
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
                return True, "Order executed successfully"
        except Exception as e:
            if "rate limit" in str(e).lower() or "eapi" in str(e).lower():
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Private API rate limit exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                return False, f"Order execution error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}"
    return False, "Max retries exceeded"

# --- Trading Strategy ---
def buy_strategy(current_rsi, current_price, ema_value, usd_balance, prev_price, atr_value):
    """Determine buy amount based on RSI, price dip, or momentum with dynamic thresholds."""
    atr_multiplier = 1.0
