import warnings
import time
import logging
from datetime import datetime
from pytz import timezone
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

# --- Configuration ---
CONFIG = {
    "API_KEY": "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM",  # Replace with your Kraken API key
    "API_SECRET": "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q==",  # Replace with your Kraken API secret
    "TRADING_PAIR": "XBTUSD",
    "INITIAL_FIAT": 1000.0,  # Starting USD balance for simulation
    "EMA_WINDOW": 20,  # 20-day EMA
    "RSI_WINDOW": 14,  # 14-day RSI
    "TIMEZONE": "US/Eastern",
    "MIN_USD_BALANCE": 10.0,  # Minimum USD for buy orders
    "MIN_BTC_BALANCE": 0.0001,  # Minimum BTC for sell orders
    "SLEEP_INTERVAL": 60,  # Seconds between cycles to respect API limits
    "TAKER_FEE": 0.0026,  # Kraken taker fee (0.26%)
}

# Trading levels for buy/sell signals
BUY_LEVELS = [
    {"rsi": 45, "percentage": 0.20},  # 20% allocation
    {"rsi": 38, "percentage": 0.30},  # 30% allocation
    {"rsi": 30, "percentage": 1.00},  # 100% allocation
]
SELL_LEVELS = [
    {"rsi": 65, "percentage": 0.20},  # 20% sell-off
    {"rsi": 72, "percentage": 0.30},  # 30% sell-off
    {"rsi": 80, "percentage": 1.00},  # 100% sell-off
]

# --- Setup Logging ---
logging.basicConfig(
    filename="kraken_trading_bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --- Setup Kraken API ---
warnings.simplefilter(action="ignore", category=FutureWarning)
api = krakenex.API(key=CONFIG["API_KEY"], secret=CONFIG["API_SECRET"])
k = KrakenAPI(api)

# --- Helper Functions ---
def get_minimum_order_size():
    """Fetch minimum order size for the trading pair."""
    try:
        pair_info = k.get_tradable_asset_pairs(CONFIG["TRADING_PAIR"])
        return float(pair_info["ordermin"][0]), None
    except Exception as e:
        return None, f"Failed to fetch minimum order size: {str(e)}"

def get_ohlc_data():
    """Fetch OHLC data and calculate RSI and EMA."""
    try:
        ohlc, _ = k.get_ohlc_data(
            CONFIG["TRADING_PAIR"], interval=1440, ascending=True
        )
        ohlc["close"] = ohlc["close"].astype(float)
        ohlc["rsi"] = RSIIndicator(ohlc["close"], CONFIG["RSI_WINDOW"]).rsi()
        ohlc["ema"] = EMAIndicator(ohlc["close"], CONFIG["EMA_WINDOW"]).ema_indicator()
        return ohlc, None
    except Exception as e:
        return None, f"Data fetch error: {str(e)}"

def get_current_price():
    """Get real-time price for the trading pair."""
    try:
        ticker = k.get_ticker(CONFIG["TRADING_PAIR"])
        return float(ticker["c"][0]), None
    except Exception as e:
        return None, f"Price fetch error: {str(e)}"

def get_balances():
    """Get current USD and BTC balances."""
    try:
        balance = k.get_account_balance()
        usd = float(balance.loc["ZUSD"]["vol"]) if "ZUSD" in balance.index else 0.0
        btc = float(balance.loc["XXBT"]["vol"]) if "XXBT" in balance.index else 0.0
        return usd, btc, None
    except Exception as e:
        return 0.0, 0.0, f"Balance fetch error: {str(e)}"

def execute_order(order_type, amount):
    """Execute a market order with validation."""
    try:
        min_order_size, err = get_minimum_order_size()
        if err:
            return False, err
        if amount < min_order_size:
            return False, f"Order size {amount:.8f} below minimum {min_order_size}"
        
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
        return False, f"Order execution error: {str(e)}"

# --- Trading Strategy ---
def buy_strategy(current_rsi, current_price, ema_value, usd_balance):
    """Determine buy amount based on RSI and EMA."""
    if current_price < ema_value:
        return 0.0, "Price below EMA - no buy"
    for level in sorted(BUY_LEVELS, key=lambda x: x["rsi"]):
        if current_rsi <= level["rsi"]:
            buy_amount = usd_balance * level["percentage"] * (1 - CONFIG["TAKER_FEE"])
            return buy_amount, f"RSI {current_rsi:.2f} ≤ {level['rsi']} (Level {BUY_LEVELS.index(level)+1})"
    return 0.0, "No buy conditions met"

def sell_strategy(current_rsi, current_price, ema_value, btc_balance):
    """Determine sell amount based on RSI."""
    for level in sorted(SELL_LEVELS, key=lambda x: x["rsi"], reverse=True):
        if current_rsi >= level["rsi"]:
            sell_amount = btc_balance * level["percentage"]
            return sell_amount, f"RSI {current_rsi:.2f} ≥ {level['rsi']} (Level {SELL_LEVELS.index(level)+1})"
    return 0.0, "No sell conditions met"

# --- Main Loop ---
def main():
    """Main trading bot loop."""
    logger.info("Starting Kraken BTC Trading Bot")
    print("Starting Kraken BTC Trading Bot... (Logs saved to kraken_trading_bot.log)")
    
    # Check for valid API credentials
    if not CONFIG["API_KEY"] or not CONFIG["API_SECRET"]:
        print("Error: API key and secret must be provided in CONFIG")
        logger.error("Missing API key or secret")
        return

    while True:
        try:
            # Fetch market data
            ohlc, err = get_ohlc_data()
            if err:
                print(f"Error: {err}")
                logger.error(err)
                time.sleep(CONFIG["SLEEP_INTERVAL"])
                continue

            price, price_err = get_current_price()
            usd, btc, balance_err = get_balances()
            if price_err or balance_err:
                err_msg = price_err or balance_err
                print(f"Error: {err_msg}")
                logger.error(err_msg)
                time.sleep(30)
                continue

            # Get latest indicators
            current_rsi = round(ohlc["rsi"].iloc[-1], 2)
            current_ema = round(ohlc["ema"].iloc[-1], 2)

            # Log market status
            timestamp = datetime.now(timezone(CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M:%S")
            status = f"[{timestamp}] Price: ${price:.2f} | RSI: {current_rsi:.2f} | EMA: ${current_ema:.2f} | USD: ${usd:.2f} | BTC: {btc:.6f}"
            print(status)
            logger.info(status)

            # Execute buy strategy
            if usd > CONFIG["MIN_USD_BALANCE"]:
                buy_amount, buy_reason = buy_strategy(current_rsi, price, current_ema, usd)
                if buy_amount > 0:
                    btc_amount = buy_amount / price
                    success, message = execute_order("buy", btc_amount)
                    log_msg = f"Buy: {buy_reason} | Amount: ${buy_amount:.2f} ({btc_amount:.6f} BTC) | {message}"
                    print(log_msg)
                    logger.info(log_msg)
                else:
                    print(f"Buy: {buy_reason}")
                    logger.info(f"Buy: {buy_reason}")

            # Execute sell strategy
            if btc > CONFIG["MIN_BTC_BALANCE"]:
                sell_amount, sell_reason = sell_strategy(current_rsi, price, current_ema, btc)
                if sell_amount > 0:
                    success, message = execute_order("sell", sell_amount)
                    log_msg = f"Sell: {sell_reason} | Amount: {sell_amount:.6f} BTC | {message}"
                    print(log_msg)
                    logger.info(log_msg)
                else:
                    print(f"Sell: {sell_reason}")
                    logger.info(f"Sell: {sell_reason}")

            # Sleep to avoid API rate limits
            time.sleep(CONFIG["SLEEP_INTERVAL"])

        except KeyboardInterrupt:
            print("Bot stopped by user")
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            logger.error(f"Unexpected error: {str(e)}")
            time.sleep(30)

if __name__ == "__main__":
    main()
