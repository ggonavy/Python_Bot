import os
import time
import krakenex
from pykrakenapi import KrakenAPI
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange
import asyncio
import sys
from datetime import datetime
import pytz
import warnings
from flask import Flask
import threading
import logging

# Suppress FutureWarnings
warnings.filterwarnings('ignore', category=FutureWarning)

# Flask app for Web Service
app = Flask(__name__)

@app.route('/')
def home():
    return 'Kraken Trading Bot is running!'

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

# Initialize Kraken API
api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_API_SECRET')

if not api_key or not api_secret:
    error_msg = "KRAKEN_API_KEY or KRAKEN_API_SECRET not set in environment variables."
    timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    with open('trade_log.txt', 'a') as f:
        f.write(f"{timestamp} | {error_msg}\n")
        f.flush()
    print(f"{timestamp} | {error_msg}", file=sys.stderr)
    raise ValueError(error_msg)

api = krakenex.API(key=api_key, secret=api_secret)
k = KrakenAPI(api)

# Configuration
BTC_PAIR = 'XXBTZUSD'
HEDGE_PAIR = 'XETHZUSD'
INTERVAL = 60
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
STOP_LOSS_PCT = 0.03
MAX_EXPOSURE = 0.85
BASE_HEDGE_RATIO = 0.5
HEDGE_MAX_DURATION = 3600
LOG_FILE = 'trade_log.txt'
CYCLE_INTERVAL = 30
MIN_USD_BALANCE = 100
HEALTH_CHECK_INTERVAL = 1200
DEBUG_MODE = True
API_RATE_LIMIT_SLEEP = 9
MIN_BTC_VOLUME = 0.0001
ATR_MULTIPLIER = 1.0

def log_trade(message):
    timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f"{timestamp} | {message}\n")
        f.flush()
    print(f"{timestamp} | {message}")
    print(f"{timestamp} | {message}", file=sys.stderr)

def get_ohlc_data(pair):
    if not pair:
        log_trade(f"No trade: Invalid pair ({pair})")
        return None
    for attempt in range(3):
        try:
            ohlc, _ = k.get_ohlc_data(pair, interval=INTERVAL, ascending=True)
            log_trade(f"Successfully fetched OHLC data for {pair}, rows: {len(ohlc)}")
            time.sleep(API_RATE_LIMIT_SLEEP)
            return ohlc
        except Exception as e:
            log_trade(f"Error fetching OHLC data for {pair} (attempt {attempt+1}/3): {str(e)}")
            time.sleep(API_RATE_LIMIT_SLEEP)
    log_trade(f"Failed to fetch OHLC data for {pair} after 3 attempts")
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
            log_trade("Error: Invalid or NaN values detected in OHLC data")
            return None, None

        btc_df['RSI'] = RSIIndicator(btc_df['close'], RSI_PERIOD).rsi()
        btc_df['EMA'] = EMAIndicator(btc_df['close'], EMA_PERIOD).ema_indicator()
        btc_df['ATR'] = AverageTrueRange(btc_df['high'], btc_df['low'], btc_df['close'], ATR_PERIOD).average_true_range()
        btc_df['MACD'] = MACD(btc_df['close'], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL).macd()
        btc_df['MACD_Signal'] = MACD(btc_df['close'], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL).macd_signal()
        if hedge_df is not None:
            corr = btc_df['close'].pct_change().rolling(20).corr(hedge_df['close'].pct_change())
            btc_df['Hedge_Ratio'] = np.where(corr < 0.7, BASE_HEDGE_RATIO * 0.6, BASE_HEDGE_RATIO)
        else:
            btc_df['Hedge_Ratio'] = 0
        log_trade("Indicators calculated: RSI, EMA, ATR, MACD, Hedge Ratio")
        return btc_df, hedge_df
    except Exception as e:
        log_trade(f"Error calculating indicators: {str(e)}")
        return None, None

def execute_trade(pair, side, price, volume):
    if not pair or volume < MIN_BTC_VOLUME:
        log_trade(f"No trade executed: Invalid pair ({pair}) or volume ({volume:.6f}) below minimum ({MIN_BTC_VOLUME})")
        return None
    for attempt in range(3):
        try:
            order = k.add_order(pair, side, 'market', volume, price=price)
            log_trade(f"Executed {side} order on {pair}: Price: ${price:.2f}, Volume: {volume:.6f}")
            time.sleep(API_RATE_LIMIT_SLEEP)
            return order
        except Exception as e:
            log_trade(f"Error executing {side} order on {pair} (attempt {attempt+1}/3): {str(e)}")
            time.sleep(API_RATE_LIMIT_SLEEP)
    log_trade(f"Failed to execute {side} order on {pair} after 3 attempts")
    return None

async def main():
    log_trade("Bot starting: Initializing Kraken API and account status")
    try:
        server_time = k.get_server_time()
        log_trade(f"Kraken API connected: Server time {server_time[1]}")
    except Exception as e:
        log_trade(f"Error connecting to Kraken API: {str(e)}")
        raise ValueError("Failed to connect to Kraken API.")

    usd_codes = ['ZUSD', 'USD', 'USDT']
    btc_codes = ['XXBT', 'XBT', 'BTC']
    fiat_balance = None
    btc_balance = 0
    balance = None
    try:
        balance = k.get_account_balance()
        log_trade(f"Available balances: {balance.index.tolist()}")
        for code in usd_codes:
            if code in balance.index:
                fiat_balance = float(balance.loc[code].iloc[0])
                log_trade(f"Portfolio balance found: {code} = ${fiat_balance:.2f}")
                break
        if fiat_balance is None or fiat_balance < MIN_USD_BALANCE:
            log_trade(f"Error: No sufficient USD balance found in {usd_codes}. Minimum ${MIN_USD_BALANCE} required.")
            raise ValueError(f"No sufficient USD balance found in {usd_codes}.")
    except Exception as e:
        log_trade(f"Error fetching portfolio balance: {str(e)}")
        raise ValueError("Failed to fetch portfolio balance.")

    for code in btc_codes:
        try:
            btc_balance = float(balance.loc[code].iloc[0])
            log_trade(f"BTC balance found: {code} = ${btc_balance:.6f} BTC")
            break
        except KeyError:
            continue
    if btc_balance == 0:
        log_trade("No BTC balance found, assuming fiat-only start.")

    btc_price = 106535
    portfolio_value = fiat_balance + (btc_balance * btc_price)
    log_trade(f"Initial portfolio value: ${portfolio_value:.2f} (Fiat: ${fiat_balance:.2f}, BTC: {btc_balance:.6f})")

    trade_state = {
        'stage': 0,
        'entry_price': 0,
        'btc_volume': 0,
        'avg_entry': 0,
        'hedge_volume': 0,
        'hedge_start_time': 0,
        'sell_stage': 0
    }
    last_health_check = time.time()

    while True:
        try:
            if time.time() - last_health_check >= HEALTH_CHECK_INTERVAL:
                log_trade("Health check: Bot running, checking API connectivity")
                try:
                    server_time = k.get_server_time()
                    log_trade(f"Health check: Kraken API connected, Server time {server_time[1]}")
                    balance = k.get_account_balance()
                    btc_balance = 0
                    for code in btc_codes:
                        try:
                            btc_balance = float(balance.loc[code].iloc[0])
                            break
                        except KeyError:
                            continue
                    for code in usd_codes:
                        if code in balance.index:
                            fiat_balance = float(balance.loc[code].iloc[0])
                            break
                    portfolio_value = fiat_balance + (btc_balance * btc_price)
                    log_trade(f"Health check: Updated portfolio value: ${portfolio_value:.2f}")
                except Exception as e:
                    log_trade(f"Health check: Error connecting to Kraken API: {str(e)}")
                last_health_check = time.time()

            if DEBUG_MODE:
                log_trade("Debug: Starting trade cycle")

            btc_df = get_ohlc_data(BTC_PAIR)
            hedge_df = get_ohlc_data(HEDGE_PAIR) if HEDGE_PAIR else None
            if btc_df is None or (HEDGE_PAIR and hedge_df is None):
                log_trade("Failed to fetch market data, retrying...")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            btc_df, hedge_df = calculate_indicators(btc_df, hedge_df)
            if btc_df is None or (HEDGE_PAIR and hedge_df is None):
                log_trade("Failed to calculate indicators, retrying...")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            btc_price = btc_df['close'].iloc[-1]
            rsi = btc_df['RSI'].iloc[-1]
            ema = btc_df['EMA'].iloc[-1]
            atr = btc_df['ATR'].iloc[-1]
            macd = btc_df['MACD'].iloc[-1]
            macd_signal = btc_df['MACD_Signal'].iloc[-1]
            hedge_ratio = btc_df['Hedge_Ratio'].iloc[-1]
            hedge_name = HEDGE_PAIR.split('Z')[0] if HEDGE_PAIR else 'None'
            current_time = time.time()

            portfolio_value = fiat_balance + (btc_balance * btc_price)
            log_trade(f"Updated portfolio value: ${portfolio_value:.2f} (Fiat: ${fiat_balance:.2f}, BTC: {btc_balance:.6f})")
            log_trade(f"Price: ${btc_price:.2f} | RSI: {rsi:.1f} | EMA: ${ema:.2f} | ATR: ${atr:.2f} | MACD: {macd:.2f} | MACD Signal: {macd_signal:.2f} | Stage: {trade_state['stage']} | Hedge: {hedge_ratio:.2f}x {hedge_name}")

            if not (30 < rsi < 70):
                log_trade(f"No trade: RSI ({rsi:.1f}) outside 30-70 range")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue
            if not (btc_price > ema):
                log_trade(f"No trade: Price (${btc_price:.2f}) below EMA (${ema:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue
            if not (macd > macd_signal):
                log_trade(f"No trade: MACD ({macd:.2f}) below MACD Signal ({macd_signal:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            atr_pct = atr / btc_price
            buy_pct = FIRST_BUY_PCT if atr_pct <= 0.005 else max(FIRST_BUY_PCT * (1 - ATR_MULTIPLIER * (atr_pct - 0.005)), 0.1)

            buy_value = buy_pct * portfolio_value
            if fiat_balance < buy_value:
                log_trade(f"Warning: Insufficient USD balance (${fiat_balance:.2f}) for full buy (${buy_value:.2f})")
                btc_volume = max(fiat_balance / btc_price, MIN_BTC_VOLUME)
                buy_value = btc_volume * btc_price
                log_trade(f"Adjusting to available fiat: Attempting buy with BTC volume={btc_volume:.6f}")
            else:
                btc_volume = max((buy_pct * portfolio_value) / btc_price, MIN_BTC_VOLUME)

            if btc_price > ema and 30 < rsi < 70 and macd > macd_signal:
                log_trade(f"Checking buy conditions: RSI={rsi:.1f}, MACD={macd:.2f}, Stage={trade_state['stage']}")
                if trade_state['stage'] == 0 and rsi <= RSI_BUY_THRESHOLDS[0]:
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting buy: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        trade_state = {
                            'stage': 1,
                            'entry_price': btc_price,
                            'btc_volume': btc_volume,
                            'avg_entry': btc_price,
                            'hedge_volume': hedge_volume,
                            'hedge_start_time': time.time(),
                            'sell_stage': 0
                        }
                        fiat_balance -= btc_volume * btc_price
                        btc_balance += btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")

                elif trade_state['stage'] == 1 and (rsi <= RSI_BUY_THRESHOLDS[1] or btc_price < trade_state['entry_price'] * (1 - DIP_THRESHOLDS[0])):
                    remaining_value = portfolio_value - (trade_state['btc_volume'] * trade_state['avg_entry'])
                    buy_value = SECOND_BUY_PCT * remaining_value
                    if fiat_balance < buy_value:
                        btc_volume = max(fiat_balance / btc_price, MIN_BTC_VOLUME)
                        buy_value = btc_volume * btc_price
                    else:
                        btc_volume = max((SECOND_BUY_PCT * remaining_value) / btc_price, MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting buy: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        total_btc = trade_state['btc_volume'] + btc_volume
                        trade_state['avg_entry'] = (trade_state['avg_entry'] * trade_state['btc_volume'] + btc_price * btc_volume) / total_btc
                        trade_state['stage'] = 2
                        trade_state['btc_volume'] = total_btc
                        trade_state['hedge_volume'] = trade_state['hedge_volume'] + hedge_volume
                        trade_state['hedge_start_time'] = time.time()
                        fiat_balance -= btc_volume * btc_price
                        btc_balance += btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")

                elif trade_state['stage'] == 2 and (rsi <= RSI_BUY_THRESHOLDS[2] or btc_price < trade_state['entry_price'] * (1 - DIP_THRESHOLDS[1])):
                    remaining_value = portfolio_value - (trade_state['btc_volume'] * trade_state['avg_entry'])
                    buy_value = remaining_value
                    if fiat_balance < buy_value:
                        btc_volume = max(fiat_balance / btc_price, MIN_BTC_VOLUME)
                        buy_value = btc_volume * btc_price
                    else:
                        btc_volume = max(remaining_value / btc_price, MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting buy: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        total_btc = trade_state['btc_volume'] + btc_volume
                        trade_state['avg_entry'] = (trade_state['avg_entry'] * trade_state['btc_volume'] + btc_price * btc_volume) / total_btc
                        trade_state['stage'] = 3
                        trade_state['btc_volume'] = total_btc
                        trade_state['hedge_volume'] = trade_state['hedge_volume'] + hedge_volume
                        trade_state['hedge_start_time'] = time.time()
                        fiat_balance -= btc_volume * btc_price
                        btc_balance += btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")

            if trade_state['stage'] > 0:
                log_trade(f"Checking sell conditions: RSI={rsi:.1f}, MACD={macd:.2f}, Stage={trade_state['sell_stage']}")
                if btc_price < trade_state['avg_entry'] * (1 - STOP_LOSS_PCT):
                    btc_volume = max(trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = trade_state['hedge_volume']
                    log_trade(f"Stop-loss triggered: Price (${btc_price:.2f}) < {STOP_LOSS_PCT*100}% below avg entry")
                    order = execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        fiat_balance += btc_volume * btc_price
                        btc_balance -= btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")
                        trade_state = {
                            'stage': 0,
                            'entry_price': 0,
                            'btc_volume': 0,
                            'avg_entry': 0,
                            'hedge_volume': 0,
                            'hedge_start_time': 0,
                            'sell_stage': 0
                        }
                elif rsi > RSI_SELL_THRESHOLDS[0] and trade_state['sell_stage'] == 0 and macd < macd_signal:
                    btc_volume = max(FIRST_SELL_PCT * trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting sell: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        trade_state['btc_volume'] = trade_state['btc_volume'] - btc_volume
                        trade_state['hedge_volume'] = trade_state['hedge_volume'] - hedge_volume
                        trade_state['sell_stage'] = 1
                        fiat_balance += btc_volume * btc_price
                        btc_balance -= btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")

                elif rsi > RSI_SELL_THRESHOLDS[1] and trade_state['sell_stage'] == 1 and macd < macd_signal:
                    btc_volume = max(SECOND_SELL_PCT * trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting sell: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        trade_state['btc_volume'] = trade_state['btc_volume'] - btc_volume
                        trade_state['hedge_volume'] = trade_state['hedge_volume'] - hedge_volume
                        trade_state['sell_stage'] = 2
                        fiat_balance += btc_volume * btc_price
                        btc_balance -= btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")

                elif (rsi >= RSI_SELL_THRESHOLDS[2] or btc_price < ema or btc_price > trade_state['avg_entry'] * 1.012) and trade_state['btc_volume'] > 0 and macd < macd_signal:
                    btc_volume = max(trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = trade_state['hedge_volume']
                    log_trade(f"Attempting sell: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        fiat_balance += btc_volume * btc_price
                        btc_balance -= btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")
                        trade_state = {
                            'stage': 0,
                            'entry_price': 0,
                            'btc_volume': 0,
                            'avg_entry': 0,
                            'hedge_volume': 0,
                            'hedge_start_time': 0,
                            'sell_stage': 0
                        }

            if DEBUG_MODE:
                log_trade("Debug: Trade cycle completed")

            await asyncio.sleep(CYCLE_INTERVAL)
        except Exception as e:
            log_trade(f"Error in main loop: {str(e)}")
            await asyncio.sleep(CYCLE_INTERVAL)

def start_bot():
    asyncio.run(main())

if __name__ == "__main__":
    # Start trading loop in a separate thread
    threading.Thread(target=start_bot, daemon=True).start()
    # Run Flask app
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
