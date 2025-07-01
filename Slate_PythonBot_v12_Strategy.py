import warnings
import time
import krakenex
from datetime import datetime
from pytz import timezone
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

# --- Configuration ---
API_KEY = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"    # Replace with Kraken API key
API_SECRET = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="  # Replace with Kraken API secret
PAIR = "XBTUSD"             # Trading pair
INITIAL_FIAT = 1000         # Starting USD balance
EMA_WINDOW = 20             # 20-day EMA for trend confirmation
RSI_WINDOW = 14             # 14-day RSI
TIMEZONE = 'US/Eastern'     # Timezone for timestamps

# --- Setup ---
warnings.simplefilter(action='ignore', category=FutureWarning)
api = krakenex.API()
api.key = API_KEY
api.secret = API_SECRET
k = KrakenAPI(api)

# --- Trading Levels ---
BUY_LEVELS = [
    {'rsi': 45, 'percentage': 0.20},  # Initial accumulation
    {'rsi': 38, 'percentage': 0.30},  # Aggressive buying
    {'rsi': 30, 'percentage': 1.00}   # Full allocation
]

SELL_LEVELS = [
    {'rsi': 65, 'percentage': 0.20},  # Initial profit taking
    {'rsi': 72, 'percentage': 0.30},  # Aggressive selling
    {'rsi': 80, 'percentage': 1.00}   # Full exit
]

# --- Helper Functions ---
def get_ohlc_data():
    """Fetch OHLC data with EMA calculation"""
    try:
        ohlc, last = k.get_ohlc_data(
            PAIR, 
            interval=1440,  # Daily candles
            ascending=True
        )
        ohlc['close'] = ohlc['close'].astype(float)
        
        # Calculate indicators
        ohlc['rsi'] = RSIIndicator(ohlc['close'], RSI_WINDOW).rsi()
        ohlc['ema'] = EMAIndicator(ohlc['close'], EMA_WINDOW).ema_indicator()
        
        return ohlc, None
    except Exception as e:
        return None, f"Data fetch error: {str(e)}"

def get_current_price():
    """Get real-time BTC price"""
    try:
        ticker = k.get_ticker(PAIR)
        return float(ticker['c'][0]), None  # 'c' = last closed price
    except Exception as e:
        return None, f"Price error: {str(e)}"

def get_balances():
    """Get current account balances"""
    try:
        balance = k.get_account_balance()
        usd = float(balance.loc['ZUSD']['vol']) if 'ZUSD' in balance.index else 0
        btc = float(balance.loc['XXBT']['vol']) if 'XXBT' in balance.index else 0
        return usd, btc, None
    except Exception as e:
        return 0, 0, f"Balance error: {str(e)}"

def execute_order(order_type, amount):
    """Execute market order with risk checks"""
    try:
        if amount <= 0.0001:  # Kraken minimum order size
            return False, "Order below minimum size"
            
        response = k.query_private('AddOrder', {
            'pair': PAIR,
            'type': order_type,
            'ordertype': 'market',
            'volume': str(round(amount, 8))
        })
        
        if response['error']:
            return False, response['error']
        return True, "Order executed"
    except Exception as e:
        return False, str(e)

# --- Trading Logic ---
def buy_strategy(current_rsi, current_price, ema_value, usd_balance):
    """Dynamic buy decision engine"""
    if current_price < ema_value:
        return 0, "Price below EMA - no buy"
        
    for level in sorted(BUY_LEVELS, key=lambda x: x['rsi']):
        if current_rsi <= level['rsi']:
            buy_amount = usd_balance * level['percentage']
            return buy_amount, f"RSI {current_rsi} ≤ {level['rsi']} (Level {BUY_LEVELS.index(level)+1})"
    
    return 0, "No buy conditions met"

def sell_strategy(current_rsi, current_price, ema_value, btc_balance):
    """Dynamic sell decision engine"""
    if current_price > ema_value:
        return 0, "Price above EMA - no sell"
        
    for level in sorted(SELL_LEVELS, key=lambda x: x['rsi'], reverse=True):
        if current_rsi >= level['rsi']:
            sell_amount = btc_balance * level['percentage']
            return sell_amount, f"RSI {current_rsi} ≥ {level['rsi']} (Level {SELL_LEVELS.index(level)+1})"
    
    return 0, "No sell conditions met"

# --- Main Loop ---
print("Starting Advanced BTC Trading Bot...")
while True:
    try:
        # Get market data
        ohlc, err = get_ohlc_data()
        if err:
            print(f"Data Error: {err}")
            time.sleep(60)
            continue
            
        price, price_err = get_current_price()
        usd, btc, balance_err = get_balances()
        
        if price_err or balance_err:
            print(f"Error: {price_err or balance_err}")
            time.sleep(30)
            continue
            
        # Get latest indicators
        current_rsi = round(ohlc['rsi'].iloc[-1], 2)
        current_ema = round(ohlc['ema'].iloc[-1], 2)
        
        # Generate trading signal
        timestamp = datetime.now(timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] Price: ${price} | RSI: {current_rsi} | EMA: {current_ema}")
        print(f"USD: ${usd:.2f} | BTC: {btc:.6f}")
        
        # Execute trades
        if usd > 10:  # Minimum USD balance for buys
            buy_amount, buy_reason = buy_strategy(current_rsi, price, current_ema, usd)
            if buy_amount
