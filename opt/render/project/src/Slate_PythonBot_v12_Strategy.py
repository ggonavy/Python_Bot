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

# Initialize Kraken API
api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_API_SECRET')

if not api_key or not api_secret:
    error_msg = "KRAKEN_API_KEY or KRAKEN_API_SECRET not set. Configure in Render dashboard."
    with open('trade_log.txt', 'a') as f:
        timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"{timestamp} | {error_msg}\n")
        f.flush()
    print(f"{timestamp} | {error_msg}", file=sys.stderr)
    raise ValueError(error_msg)

api = krakenex.API(key=api_key, secret=api_secret)
k = KrakenAPI(api)

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
CYCLE_INTERVAL = 600  # Increased to reduce API calls
MIN_USD_BALANCE = 100
HEALTH_CHECK_INTERVAL = 86400  # 24 hours
DEBUG_MODE = True
API_RATE_LIMIT_SLEEP = 600  # Increased for rate limits
MIN_BTC_VOLUME = 0.0001
ATR_MULTIPLIER = 1.0
MIN_CANDLES = 15

def log_trade(message):
    timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f"{timestamp} | {message}\n")
        f.flush()
    print(f"{timestamp} | {message}")
    print(f"{timestamp} | {message}", file=sys.stderr)

def get_ohlc_data(pair, retries=7, backoff_factor=5):
    if not pair:
        log_trade(f"No trade: Invalid pair ({pair})")
        return None
    for attempt in range(retries):
        try:
            ohlc, _ = k.get_ohlc_data(pair, interval=INTERVAL, ascending=True, count=300)
            if len(ohlc) < MIN_CANDLES:
                log_trade(f"Error: Only {len(ohlc)} candles for {pair}, need {MIN_CANDLES}")
                time.sleep(API_RATE_LIMIT_SLEEP * (backoff_factor ** attempt))
                continue
            log_trade(f"Fetched OHLC for {pair}, rows: {len(ohlc)}")
            time.sleep(API_RATE_LIMIT_SLEEP)
            return ohlc
        except Exception as e:
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

def confirm_order(order, pair, side, volume):
    try:
        order_id = order['descr']['order']
        time.sleep(API_RATE_LIMIT_SLEEP)
        orders = k.query_orders_info(order_id)
        if orders[order_id]['status'] == 'closed':
            log_trade(f"Order confirmed: {side} {volume:.6f} on {pair}")
            return True
        else:
            log_trade(f"Order not closed: {side} {volume:.6f} on {pair}, status: {orders[order_id]['status']}")
            return False
    except Exception as e:
        log_trade(f"Error confirming order on {pair}: {str(e)}")
        return False

def execute_trade(pair, side, price, volume, retries=7):
    if not pair or volume < MIN_BTC_VOLUME:
        log_trade(f"No trade: Invalid pair ({pair}) or volume ({volume:.6f}) < {MIN_BTC_VOLUME}")
        return None
    for attempt in range(retries):
        try:
            order = k.add_order(pair, side, 'market', volume, price=price)
            if confirm_order(order, pair, side, volume):
                log_trade(f"Executed {side} order on {pair}: Price: ${price:.2f}, Volume: {volume:.6f}")
                time.sleep(API_RATE_LIMIT_SLEEP)
                return order
            else:
                log_trade(f"Order failed to close on {pair}, retrying...")
        except Exception as e:
            log_trade(f"Error executing {side} order on {pair} (attempt {attempt+1}/{retries}): {str(e)}")
        time.sleep(API_RATE_LIMIT_SLEEP * (2 ** attempt))
    log_trade(f"Failed to execute {side} order on {pair} after {retries} attempts")
    return None

async def main():
    log_trade("Bot starting: Initializing Kraken API")
    try:
        server_time = k.get_server_time()
        log_trade(f"Kraken API connected: Server time {server_time[1]}")
    except Exception as e:
        log_trade(f"Error connecting to Kraken API: {str(e)}")
        raise ValueError("Failed to connect to Kraken API")

    usd_codes = ['ZUSD', 'USD', 'USDT']
    btc_codes = ['XXBT', 'XBT', 'BTC']
    eth_codes = ['XETH', 'ETH']
    fiat_balance = None
    btc_balance = 0
    eth_balance = 0
    balance = None
    try:
        balance = k.get_account_balance()
        log_trade(f"Available balances: {balance.index.tolist()}")
        for code in usd_codes:
            if code in balance.index:
                fiat_balance = float(balance.loc[code].iloc[0])
                log_trade(f"Fiat balance: {code} = ${fiat_balance:.2f}")
                break
        if fiat_balance is None or fiat_balance < MIN_USD_BALANCE:
            log_trade(f"Error: Insufficient USD balance in {usd_codes}. Min ${MIN_USD_BALANCE} required.")
            raise ValueError(f"Insufficient USD balance")
        for code in btc_codes:
            try:
                btc_balance = float(balance.loc[code].iloc[0])
                log_trade(f"BTC balance: {code} = ${btc_balance:.6f} BTC")
                break
            except KeyError:
                continue
        for code in eth_codes:
            try:
                eth_balance = float(balance.loc[code].iloc[0])
                log_trade(f"ETH balance: {code} = ${eth_balance:.6f} ETH")
                break
            except KeyError:
                continue
    except Exception as e:
        log_trade(f"Error fetching balance: {str(e)}")
        raise ValueError("Failed to fetch balance")

    btc_price = 109296.00  # From latest log
    eth_price = 3500  # Approx ETH price
    portfolio_value = fiat_balance + (btc_balance * btc_price) + (eth_balance * eth_price)
    log_trade(f"Portfolio: ${portfolio_value:.2f} (Fiat: ${fiat_balance:.2f}, BTC: {btc_balance:.6f}, ETH: {eth_balance:.6f})")

    trade_state = {
        'stage': 0,
        'entry_price': 0,
        'btc_volume': 0,
        'avg_entry': 0,
        'hedge_volume': 0,
        'hedge_start_time': 0,
        'sell_stage': 0
    }
    last_ohlc_fetch = {'BTC': None, 'ETH': None, 'BTC_time': 0, 'ETH_time': 0}
    cache_duration = 14400  # Cache OHLC for 240 minutes
    last_health_check = time.time()

    while True:
        try:
            if time.time() - last_health_check >= HEALTH_CHECK_INTERVAL:
                log_trade("Health check: Bot running")
                try:
                    server_time = k.get_server_time()
                    log_trade(f"Health check: Kraken API connected")
                    balance = k.get_account_balance()
                    fiat_balance = None
                    btc_balance = 0
                    eth_balance = 0
                    for code in usd_codes:
                        if code in balance.index:
                            fiat_balance = float(balance.loc[code].iloc[0])
                            break
                    for code in btc_codes:
                        try:
                            btc_balance = float(balance.loc[code].iloc[0])
                            break
                        except KeyError:
                            continue
                    for code in eth_codes:
                        try:
                            eth_balance = float(balance.loc[code].iloc[0])
                            break
                        except KeyError:
                            continue
                    portfolio_value = fiat_balance + (btc_balance * btc_price) + (eth_balance * eth_price)
                    log_trade(f"Health check: Portfolio: ${portfolio_value:.2f}")
                except Exception as e:
                    log_trade(f"Health check: Error: {str(e)}")
                last_health_check = time.time()

            if DEBUG_MODE:
                log_trade("Debug: Starting trade cycle")

            current_time = time.time()
            btc_df = last_ohlc_fetch['BTC'] if current_time - last_ohlc_fetch['BTC_time'] < cache_duration else get_ohlc_data(BTC_PAIR)
            if btc_df is not None:
                last_ohlc_fetch['BTC'] = btc_df
                last_ohlc_fetch['BTC_time'] = current_time
            hedge_df = last_ohlc_fetch['ETH'] if current_time - last_ohlc_fetch['ETH_time'] < cache_duration else get_ohlc_data(HEDGE_PAIR) if HEDGE_PAIR else None
            if hedge_df is not None:
                last_ohlc_fetch['ETH'] = hedge_df
                last_ohlc_fetch['ETH_time'] = current_time

            if btc_df is None or (HEDGE_PAIR and hedge_df is None):
                log_trade("Failed to fetch market data")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            btc_df, hedge_df = calculate_indicators(btc_df, hedge_df)
            if btc_df is None or (HEDGE_PAIR and hedge_df is None):
                log_trade("Failed to calculate indicators")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            btc_price = btc_df['close'].iloc[-1]
            rsi = btc_df['RSI'].iloc[-1]
            ema = btc_df['EMA'].iloc[-1]
            atr = btc_df['ATR'].iloc[-1]
            macd = btc_df['MACD'].iloc[-1]
            macd_signal = btc_df['MACD_Signal'].iloc[-1]
            hedge_ratio = btc_df['Hedge_Ratio'].iloc[-1]
            current_time = time.time()

            portfolio_value = fiat_balance + (btc_balance * btc_price) + (eth_balance * eth_price)
            btc_exposure = (btc_balance * btc_price) / portfolio_value if portfolio_value > 0 else 0
            log_trade(f"Portfolio: ${portfolio_value:.2f} | BTC Exposure: {btc_exposure:.2%}")
            log_trade(f"BTC Price: ${btc_price:.2f} | RSI: {rsi:.1f} | EMA: ${ema:.2f} | ATR: ${atr:.2f} | MACD: {macd:.2f} | Signal: {macd_signal:.2f} | Hedge Ratio: {hedge_ratio:.2f}")

            atr_pct = atr / btc_price
            stop_loss_pct = STOP_LOSS_BASE_PCT * (1 + ATR_MULTIPLIER * atr_pct)

            if not (30 < rsi < 70):
                log_trade(f"No trade: RSI ({rsi:.1f}) outside 30-70")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue
            if not (btc_price > ema):
                log_trade(f"No trade: Price (${btc_price:.2f}) < EMA (${ema:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue
            if not (macd > macd_signal):
                log_trade(f"No trade: MACD ({macd:.2f}) < Signal ({macd_signal:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            buy_pct = FIRST_BUY_PCT
            if atr_pct > 0.005:
                buy_pct = FIRST_BUY_PCT * (1 - ATR_MULTIPLIER * (atr_pct - 0.005))
                buy_pct = max(buy_pct, 0.1)

            buy_value = buy_pct * portfolio_value
            if btc_exposure > MAX_EXPOSURE:
                log_trade(f"No buy: BTC exposure ({btc_exposure:.2%}) > {MAX_EXPOSURE*100}%")
                await asyncio
