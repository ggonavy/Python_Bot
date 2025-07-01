import warnings
import time
import logging
import sys
import json
import asyncio
import aiohttp
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
import pandas as pd

# --- Configuration ---
CONFIG = {
    "API_KEY": "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM",  # Replace with your Kraken API key
    "API_SECRET": "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q==",  # Replace with your Kraken API secret
    "TRADING_PAIR": "XBTUSD",
    "INITIAL_FIAT": 1000.0,  # Starting USD balance for simulation
    "EMA_WINDOW": 20,  # 20-period EMA (hourly)
    "RSI_WINDOW": 7,  # 7-period RSI (hourly)
    "ATR_WINDOW": 14,  # 14-period ATR for volatility
    "TIMEZONE": "US/Eastern",
    "MIN_USD_BALANCE": 10.0,  # Minimum USD for buy orders
    "MIN_BTC_BALANCE": 0.0001,  # Minimum BTC for sell orders
    "SLEEP_INTERVAL": 5,  # Seconds between cycles (for Kraken Intermediate)
    "TAKER_FEE": 0.0026,  # Kraken taker fee (0.26%)
    "RATE_LIMIT_SLEEP": 5,  # Base seconds to sleep on rate limit error
    "MAX_RATE_LIMIT_SLEEP": 10,  # Max seconds for backoff
    "OHLC_CACHE_DURATION": 300,  # Cache OHLC for 5 minutes
    "TICKER_CACHE_DURATION": 300,  # Cache ticker for 5 minutes
    "API_CALL_DELAY": 0.5,  # Seconds between synchronous API calls
    "MAX_RETRIES": 3,  # Max retries for API calls
    "PRICE_DIP_THRESHOLD": 0.01,  # 1% price dip to trigger buy
    "PRICE_DIP_THRESHOLD_HIGH": 0.02,  # 2% price dip for larger buy
    "STOP_LOSS_THRESHOLD": 0.05,  # 5% price drop for stop-loss
    "VOLATILITY_THRESHOLD": 0.005,  # ATR threshold for dynamic RSI
    "DATA_FILE": "trade_data.json",  # File to persist trade data
}

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),  # Log to console for Render
        logging.FileHandler("kraken_trading_bot.log", mode="a")  # Log to file
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
            if "call frequency exceeded" in str(e).lower():
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Public call frequency exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
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
                time.sleep(CONFIG["API_CALL_DELAY"])  # Synchronous delay for KrakenAPI
                ohlc, _ = k.get_ohlc_data(CONFIG["TRADING_PAIR"], interval=60, ascending=True)
                ohlc["close"] = ohlc["close"].astype(float)
                ohlc["high"] = ohlc["high"].astype(float)
                ohlc["low"] = ohlc["low"].astype(float)
                ohlc["rsi"] = RSIIndicator(ohlc["close"], CONFIG["RSI_WINDOW"]).rsi()
                ohlc["ema"] = EMAIndicator(ohlc["close"], CONFIG["EMA_WINDOW"]).ema_indicator()
                ohlc["atr"] = AverageTrueRange(ohlc["high"], ohlc["low"], ohlc["close"], CONFIG["ATR_WINDOW"]).average_true_range()
                return ohlc, None, current_time
            except Exception as e:
                if "call frequency exceeded" in str(e).lower():
                    sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                    logger.warning(f"Public call frequency exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                    await asyncio.sleep(sleep_time)
                if attempt == CONFIG["MAX_RETRIES"] - 1:
                    return last_ohlc, f"Data fetch error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}", last_fetch_time
        return last_ohlc, "Max retries exceeded", last_fetch_time
    return last_ohlc, "Using cached OHLC data", last_fetch_time

async def get_current_price_async(session, last_price=None, last_price_time=None):
    """Get real-time price for the trading pair, caching for specified duration."""
    current_time = time.time()
    if last_price_time is None or (current_time - last_price_time) > CONFIG["TICKER_CACHE_DURATION"]:
        for attempt in range(CONFIG["MAX_RETRIES"]):
            try:
                async with session.get(
                    f"https://api.kraken.com/0/public/Ticker?pair={CONFIG['TRADING_PAIR']}"
                ) as response:
                    data = await response.json()
                    if data["error"]:
                        return None, f"API error: {data['error']}", last_price_time
                    price = float(data["result"][CONFIG["TRADING_PAIR"]]["c"][0])
                    return price, None, current_time
            except Exception as e:
                if "call frequency exceeded" in str(e).lower():
                    sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                    logger.warning(f"Public call frequency exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                    await asyncio.sleep(sleep_time)
                if attempt == CONFIG["MAX_RETRIES"] - 1:
                    return None, f"Price fetch error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}", last_price_time
        return None, "Max retries exceeded", last_price_time
    return last_price, "Using cached price", last_price_time

async def get_balances_async():
    """Get current USD and BTC balances with retries."""
    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            time.sleep(CONFIG["API_CALL_DELAY"])  # Synchronous delay for KrakenAPI
            balance = k.get_account_balance()
            usd = float(balance.loc["ZUSD"]["vol"]) if "ZUSD" in balance.index else 0.0
            btc = float(balance.loc["XXBT"]["vol"]) if "XXBT" in balance.index else 0.0
            return usd, btc, None
        except Exception as e:
            if "call frequency exceeded" in str(e).lower():
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Private call frequency exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                return 0.0, 0.0, f"Balance fetch error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}"
    return 0.0, 0.0, "Max retries exceeded"

async def execute_order_async(order_type, amount):
    """Execute a market order with validation and retries."""
    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            min_order_size, err = await get_minimum_order_size_async(aiohttp.ClientSession())
            if err:
                return False, err
            if amount < min_order_size:
                return False, f"Order size {amount:.8f} below minimum {min_order_size}"
            
            time.sleep(CONFIG["API_CALL_DELAY"])  # Synchronous delay for KrakenAPI
            response = k.query_private(
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
            if "call frequency exceeded" in str(e).lower():
                sleep_time = min(CONFIG["RATE_LIMIT_SLEEP"] * (2 ** attempt), CONFIG["MAX_RATE_LIMIT_SLEEP"])
                logger.warning(f"Private call frequency exceeded, sleeping for {sleep_time} seconds (attempt {attempt+1})")
                await asyncio.sleep(sleep_time)
            if attempt == CONFIG["MAX_RETRIES"] - 1:
                return False, f"Order execution error after {CONFIG['MAX_RETRIES']} attempts: {str(e)}"
    return False, "Max retries exceeded"

# --- Trading Strategy ---
def buy_strategy(current_rsi, current_price, ema_value, usd_balance, prev_price, atr_value):
    """Determine buy amount based on RSI or price dip with dynamic thresholds."""
    # Adjust RSI levels based on volatility (ATR)
    atr_multiplier = 1.0 if atr_value is None else max(0.5, min(1.5, atr_value / CONFIG["VOLATILITY_THRESHOLD"]))
    buy_levels = [
        {"rsi": 60 * atr_multiplier, "percentage": 0.20},  # 20% allocation
        {"rsi": 50 * atr_multiplier, "percentage": 0.30},  # 30% allocation
        {"rsi": 40 * atr_multiplier, "percentage": 0.50},  # 50% allocation
    ]

    # RSI-based buy
    rsi_buy_amount = 0.0
    rsi_reason = "No RSI buy conditions met"
    for level in sorted(buy_levels, key=lambda x: x["rsi"]):
        if current_rsi <= level["rsi"]:
            rsi_buy_amount = usd_balance * level["percentage"] * (1 - CONFIG["TAKER_FEE"])
            rsi_reason = f"RSI {current_rsi:.2f} ≤ {level['rsi']:.2f} (Level {buy_levels.index(level)+1}, ATR adj: {atr_multiplier:.2f})"
            break

    # Price dip buy
    dip_buy_amount = 0.0
    dip_reason = "No price dip conditions met"
    if prev_price and current_price < prev_price:
        dip_percentage = (prev_price - current_price) / prev_price
        if dip_percentage >= CONFIG["PRICE_DIP_THRESHOLD_HIGH"]:
            dip_buy_amount = usd_balance * 0.50 * (1 - CONFIG["TAKER_FEE"])  # 50% for 2%+ dip
            dip_reason = f"Price dip {dip_percentage*100:.2f}% ≥ {CONFIG['PRICE_DIP_THRESHOLD_HIGH']*100}%"
        elif dip_percentage >= CONFIG["PRICE_DIP_THRESHOLD"]:
            dip_buy_amount = usd_balance * 0.20 * (1 - CONFIG["TAKER_FEE"])  # 20% for 1-2% dip
            dip_reason = f"Price dip {dip_percentage*100:.2f}% ≥ {CONFIG['PRICE_DIP_THRESHOLD']*100}%"

    # Choose larger buy amount (RSI or dip)
    if rsi_buy_amount > dip_buy_amount:
        return rsi_buy_amount, rsi_reason
    return dip_buy_amount, dip_reason

def sell_strategy(current_rsi, current_price, ema_value, btc_balance, avg_buy_price, atr_value):
    """Determine sell amount based on RSI or stop-loss with dynamic thresholds."""
    # Adjust RSI levels based on volatility (ATR)
    atr_multiplier = 1.0 if atr_value is None else max(0.5, min(1.5, atr_value / CONFIG["VOLATILITY_THRESHOLD"]))
    sell_levels = [
        {"rsi": 70 * atr_multiplier, "percentage": 0.20},  # 20% sell-off
        {"rsi": 80 * atr_multiplier, "percentage": 0.30},  # 30% sell-off
        {"rsi": 90 * atr_multiplier, "percentage": 1.00},  # 100% sell-off
    ]

    # RSI-based sell
    rsi_sell_amount = 0.0
    rsi_reason = "No RSI sell conditions met"
    for level in sorted(sell_levels, key=lambda x: x["rsi"], reverse=True):
        if current_rsi >= level["rsi"]:
            rsi_sell_amount = btc_balance * level["percentage"]
            rsi_reason = f"RSI {current_rsi:.2f} ≥ {level['rsi']:.2f} (Level {sell_levels.index(level)+1}, ATR adj: {atr_multiplier:.2f})"
            break

    # Stop-loss sell
    stop_sell_amount = 0.0
    stop_reason = "No stop-loss conditions met"
    if avg_buy_price and current_price <= avg_buy_price * (1 - CONFIG["STOP_LOSS_THRESHOLD"]):
        stop_sell_amount = btc_balance  # Sell all
        stop_reason = f"Stop-loss triggered: Price {current_price:.2f} ≤ {avg_buy_price * (1 - CONFIG['STOP_LOSS_THRESHOLD']):.2f}"

    # Choose larger sell amount (RSI or stop-loss)
    if rsi_sell_amount > stop_sell_amount:
        return rsi_sell_amount, rsi_reason
    return stop_sell_amount, stop_reason

# --- Main Loop ---
async def main():
    """Main trading bot loop."""
    logger.info("Starting Kraken BTC Trading Bot")
    print("Starting Kraken BTC Trading Bot... (Logs saved to kraken_trading_bot.log)")
    
    # Check for valid API credentials
    if not CONFIG["API_KEY"] or not CONFIG["API_SECRET"] or CONFIG["API_KEY"] == "your_actual_api_key_here" or CONFIG["API_SECRET"] == "your_actual_api_secret_here":
        logger.error("API key or secret not provided in CONFIG")
        print("Error: API key or secret not provided in CONFIG. Please update CONFIG with valid Kraken API credentials.")
        sys.exit(1)

    last_fetch_time = None
    last_ohlc = None
    current_rsi = None
    current_ema = None
    current_atr = None
    last_price = None
    last_price_time = None
    prev_price = None
    avg_buy_price, total_btc_bought, total_usd_spent = load_trade_data()

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Fetch market data
                ohlc, err, last_fetch_time = await get_ohlc_data_async(last_fetch_time, last_ohlc)
                if err and "cached" not in err:
                    print(f"Error: {err}")
                    logger.error(err)
                    await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])
                    continue

                if ohlc is not None:
                    last_ohlc = ohlc
                    current_rsi = round(ohlc["rsi"].iloc[-1], 2)
                    current_ema = round(ohlc["ema"].iloc[-1], 2)
                    current_atr = round(ohlc["atr"].iloc[-1], 4)

                price, price_err, last_price_time = await get_current_price_async(session, last_price, last_price_time)
                if price_err and "cached" not in price_err:
                    print(f"Error: {price_err}")
                    logger.error(price_err)
                    await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])
                    continue
                if price is not None:
                    prev_price = last_price
                    last_price = price

                usd, btc, balance_err = await get_balances_async()
                if balance_err:
                    print(f"Error: {balance_err}")
                    logger.error(balance_err)
                    await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])
                    continue

                # Skip trading if no valid RSI or price
                if current_rsi is None or last_price is None:
                    print("No valid RSI or price data, skipping trade")
                    logger.info("No valid RSI or price data, skipping trade")
                    await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])
                    continue

                # Log market status
                timestamp = datetime.now(timezone(CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M:%S")
                status = f"[{timestamp}] Price: ${last_price:.2f} | RSI: {current_rsi:.2f} | EMA: ${current_ema:.2f} | ATR: {current_atr:.4f} | USD: ${usd:.2f} | BTC: {btc:.6f}"
                print(status)
                logger.info(status)

                # Execute buy strategy
                if usd > CONFIG["MIN_USD_BALANCE"]:
                    buy_amount, buy_reason = buy_strategy(current_rsi, last_price, current_ema, usd, prev_price, current_atr)
                    if buy_amount > 0:
                        btc_amount = buy_amount / last_price
                        success, message = await execute_order_async("buy", btc_amount)
                        log_msg = f"Buy: {buy_reason} | Amount: ${buy_amount:.2f} ({btc_amount:.6f} BTC) | {message}"
                        print(log_msg)
                        logger.info(log_msg)
                        if success:
                            total_btc_bought += btc_amount
                            total_usd_spent += buy_amount
                            avg_buy_price = total_usd_spent / total_btc_bought if total_btc_bought > 0 else None
                            save_trade_data(avg_buy_price, total_btc_bought, total_usd_spent)
                    else:
                        print(f"Buy: {buy_reason}")
                        logger.info(f"Buy: {buy_reason}")

                # Execute sell strategy
                if btc > CONFIG["MIN_BTC_BALANCE"]:
                    sell_amount, sell_reason = sell_strategy(current_rsi, last_price, current_ema, btc, avg_buy_price, current_atr)
                    if sell_amount > 0:
                        success, message = await execute_order_async("sell", sell_amount)
                        log_msg = f"Sell: {sell_reason} | Amount: {sell_amount:.6f} BTC | {message}"
                        print(log_msg)
                        logger.info(log_msg)
                        if success:
                            total_btc_bought = max(0, total_btc_bought - sell_amount)
                            total_usd_spent = max(0, total_usd_spent - (sell_amount * last_price))
                            avg_buy_price = total_usd_spent / total_btc_bought if total_btc_bought > 0 else None
                            save_trade_data(avg_buy_price, total_btc_bought, total_usd_spent)
                    else:
                        print(f"Sell: {sell_reason}")
                        logger.info(f"Sell: {sell_reason}")

                # Sleep to avoid API rate limits
                await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])

            except KeyboardInterrupt:
                print("Bot stopped by user")
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                print(f"Unexpected error: {str(e)}")
                logger.error(f"Unexpected error: {str(e)}")
                await asyncio.sleep(CONFIG["SLEEP_INTERVAL"])

if __name__ == "__main__":
    asyncio.run(main())
