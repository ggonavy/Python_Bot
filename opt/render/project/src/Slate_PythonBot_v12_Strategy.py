import krakenex
from pykrakenapi import KrakenAPI
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange
import asyncio
import time
import os
import sys
from datetime import datetime
import pytz
import warnings

# Suppress all FutureWarnings, including 'T' deprecation
warnings.filterwarnings('ignore', category=FutureWarning)

# Initialize Kraken API with nonce window
api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_API_SECRET')
hedge_api_key = os.getenv('KRAKEN_API_KEY_HEDGE', api_key)  # Fallback to main key
hedge_api_secret = os.getenv('KRAKEN_API_SECRET_HEDGE', api_secret)

if not api_key or not api_secret:
    error_msg = "KRAKEN_API_KEY or KRAKEN_API_SECRET not set. Configure in Render dashboard."
    with open('trade_log.txt', 'a') as f:
        timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"{timestamp} | {error_msg}\n")
        f.flush()
    print(f"{timestamp} | {error_msg}", file=sys.stderr)
    raise ValueError(error_msg)

api = krakenex.API(key=api_key, secret=api_secret)
api.nonce_window = 10000  # Avoid invalid nonce errors
k = KrakenAPI(api)
hedge_api = krakenex.API(key=hedge_api_key, secret=hedge_api_secret)
hedge_api.nonce_window = 10000
k_hedge = KrakenAPI(hedge_api)

# Configuration
BTC_PAIR = 'XXBTZUSD'
HEDGE_PAIR = 'XETHZUSD'
INTERVAL = 60  # 1-minute candles
RSI_PERIOD = 14
EMA_PERIOD = 15
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_BUY_THRESHOLDS = [45, 38, 30]
RSI_SELL_THRESHOLDS = [65, 72, 80]
DIP_THRESHOLDS = [0.003, 0.006]
FIRST_BUY_PCT = 0.2
SECOND_BUY_PCT = 0.3
FIRST_SELL_PCT = 0.2
SECOND_SELL_PCT = 0.3
STOP_LOSS_BASE_PCT = 0.03
MIN_PROFIT_PCT = 0.012  # 1.2% min profit for sells
MAX_EXPOSURE = 0.85
BASE_HEDGE_RATIO = 0.5
HEDGE_MAX_DURATION = 3600
LOG_FILE = 'trade_log.txt'
CYCLE_INTERVAL = 345600  # 96 hours to avoid rate limits
MIN_USD_BALANCE = 100
HEALTH_CHECK_INTERVAL = 86400  # 24 hours
DEBUG_MODE = True
API_RATE_LIMIT_SLEEP = 345600  # 96 hours
MIN_BTC_VOLUME = 0.0001
ATR_MULTIPLIER = 1.0
MIN_CANDLES = 15
RATE_LIMIT_WINDOW = 900  # 15-minute window for tracking API calls
RATE_LIMIT_MAX_CALLS = 15  # Max calls per minute
rate_limit_tracker = {'BTC': 0, 'ETH': 0, 'last_reset': time.time()}

def log_trade(message):
    timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f"{timestamp} | {message}\n")
        f.flush()
    print(f"{timestamp} | {message}")
    print(f"{timestamp} | {message}", file=sys.stderr)

def check_rate_limit(pair):
    current_time = time.time()
    if current_time - rate_limit_tracker['last_reset'] > RATE_LIMIT_WINDOW:
        rate_limit_tracker['BTC'] = 0
        rate_limit_tracker['ETH'] = 0
        rate_limit_tracker['last_reset'] = current_time
    if pair == BTC_PAIR and rate_limit_tracker['BTC'] >= RATE_LIMIT_MAX_CALLS:
        log_trade(f"Rate limit exceeded for {pair}. Waiting...")
        return False
    if pair == HEDGE_PAIR and rate_limit_tracker['ETH'] >= RATE_LIMIT_MAX_CALLS:
        log_trade(f"Rate limit exceeded for {pair}. Waiting...")
        return False
    return True

def increment_rate_limit(pair):
    if pair == BTC_PAIR:
        rate_limit_tracker['BTC'] += 1
    elif pair == HEDGE_PAIR:
        rate_limit_tracker['ETH'] += 1

def get_ohlc_data(pair, api_client, retries=300, backoff_factor=8):
    if not pair:
        log_trade(f"No trade: Invalid pair ({pair})")
        return None
    if not check_rate_limit(pair):
        time.sleep(API_RATE_LIMIT_SLEEP)
        return None
    for attempt in range(retries):
        try:
            ohlc, _ = api_client.get_ohlc_data(pair, interval=INTERVAL, ascending=True, count=300)
            if len(ohlc) < MIN_CANDLES:
                log_trade(f"Error: Only {len(ohlc)} candles for {pair}, need {MIN_CANDLES}")
                time.sleep(API_RATE_LIMIT_SLEEP * (backoff_factor ** attempt))
                continue
            log_trade(f"Fetched OHLC for {pair}, rows: {len(ohlc)}")
            increment_rate_limit(pair)
            time.sleep(API_RATE_LIMIT_SLEEP)
            return ohlc
        except Exception as e:
            if 'EGeneral:Too many requests' in str(e):
                log_trade(f"Rate limit hit for {pair} (attempt {attempt+1}/{retries}): {str(e)}")
                time.sleep(API_RATE_LIMIT_SLEEP * (backoff_factor ** attempt))
            else:
                log_trade(f"Error fetching OHLC for {pair} (attempt {attempt+1}/{retries}): {str(e)}")
                time.sleep(API_RATE_LIMIT_SLEEP * (backoff_factor ** attempt))
    log_trade(f"Failed to fetch OHLC for {pair} after {retries} attempts")
    return None

def calculate_indicators(btc_df, hedge_df):
    try:
        if hedge_df is not None:
            min_length = min(len(btc_df), len(hedge_df))
            btc_df = btc_df.iloc[-min_length:].reset_index(drop=True).copy()
            hedge_df = hedge_df.iloc[-min_length:].reset_index(drop=True).copy()
            log_trade(f"Aligned DataFrames: BTC rows={len(btc_df)}, Hedge rows={len(hedge_df)}")
        else:
            btc_df = btc_df.reset_index(drop=True).copy()

        if btc_df['close'].isna().any() or btc_df['close'].eq(0).any() or (hedge_df is not None and (hedge_df['close'].isna().any() or hedge_df['close'].eq(0).any())):
            log_trade("Error: Invalid or NaN values in OHLC data")
            return None, None

        btc_df['RSI'] = RSIIndicator(btc_df['close'], RSI_PERIOD).rsi()
        btc_df['EMA'] = EMAIndicator(btc_df['close'], EMA_PERIOD).ema_indicator()
        btc_df['ATR'] = AverageTrueRange(btc_df['high'], btc_df['low'], btc_df['close'], ATR_PERIOD).average_true_range()
        btc_df['MACD'] = MACD(btc_df['close'], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL).macd()
        btc_df['MACD_Signal'] = MACD(btc_df['close'], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL).macd_signal()
        if hedge_df is not None:
            corr = btc_df['close'].pct_change().rolling(20).corr(hedge_df['close'].pct_change())
            btc_df['Hedge_Ratio'] = np.where(corr < 0.7, BASE_HEDGE_RATIO * 0.6, BASE_HEDGE_RATIO * (1 + (1 - corr) * 0.2))
        else:
            btc_df['Hedge_Ratio'] = 0
        log_trade("Indicators calculated: RSI, EMA, ATR, MACD, Hedge Ratio")
        return btc_df, hedge_df
    except Exception as e:
        log_trade(f"Error calculating indicators: {str(e)}")
        return None, None

def confirm_order(order, pair, side, volume, api_client):
    if not check_rate_limit(pair):
        time.sleep(API_RATE_LIMIT_SLEEP)
        return False
    try:
        order_id = order['descr']['order']
        time.sleep(API_RATE_LIMIT_SLEEP)
        orders = api_client.query_orders_info(order_id)
        if orders[order_id]['status'] == 'closed':
            log_trade(f"Order confirmed: {side} {volume:.6f} on {pair}")
            increment_rate_limit(pair)
            return True
        else:
            log_trade(f"Order not closed: {side} {volume:.6f} on {pair}, status: {orders[order_id]['status']}")
            return False
    except Exception as e:
        log_trade(f"Error confirming order on {pair}: {str(e)}")
        return False

def execute_trade(pair, side, price, volume, api_client, retries=300):
    if not pair or volume < MIN_BTC_VOLUME:
        log_trade(f"No trade: Invalid pair ({pair}) or volume ({volume:.6f}) < {MIN_BTC_VOLUME}")
        return None
    if not check_rate_limit(pair):
        time.sleep(API_RATE_LIMIT_SLEEP)
