import krakenex
from pykrakenapi import KrakenAPI
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
import asyncio
import aiohttp
import time
import os
import sys
from datetime import datetime
import pytz
import warnings

# Suppress FutureWarnings from pykrakenapi and pandas
warnings.filterwarnings('ignore', category=FutureWarning)

# Initialize Kraken API
api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_API_SECRET')

# Verify API credentials
if not api_key or not api_secret:
    error_msg = "KRAKEN_API_KEY or KRAKEN_API_SECRET not set in environment variables. Please configure in Render dashboard."
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
HEDGE_PAIR = 'XETHZUSD'  # Options: 'XETHZUSD', 'XBCHZUSD', or '' for no hedging
INTERVAL = 60  # 1-minute candles
RSI_PERIOD = 14
EMA_PERIOD = 15
ATR_PERIOD = 14
RSI_BUY_THRESHOLDS = [45, 38, 30]  # First, second, all-in
RSI_SELL_THRESHOLDS = [65, 72, 80]  # First, second, all
DIP_THRESHOLDS = [0.003, 0.006]  # 0.3%, 0.6% dips
FIRST_BUY_PCT = 0.2
SECOND_BUY_PCT = 0.3
FIRST_SELL_PCT = 0.2
SECOND_SELL_PCT = 0.3
STOP_LOSS_PCT = 0.03  # 3% stop-loss for aggressive trading
MAX_EXPOSURE = 0.85  # Adjusted for 84% BTC exposure
BASE_HEDGE_RATIO = 0.5
HEDGE_MAX_DURATION = 3600  # 1 hour in seconds
LOG_FILE = 'trade_log.txt'
CYCLE_INTERVAL = 30  # Seconds
MIN_USD_BALANCE = 100  # Minimum USD balance required
HEALTH_CHECK_INTERVAL = 1200  # 20 minutes to reduce API calls
DEBUG_MODE = True  # Enable debug logging
API_RATE_LIMIT_SLEEP = 9  # Increased to avoid public call frequency exceeded
MIN_BTC_VOLUME = 0.0001  # Minimum BTC trade volume per Kraken requirements

def log_trade(message):
    timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f"{timestamp} | {message}\n")
        f.flush()  # Force write to file
    print(f"{timestamp} | {message}")
    print(f"{timestamp} | {message}", file=sys.stderr)  # Fallback to stderr for Render

def get_ohlc_data(pair):
    if not pair:
        log_trade(f"No trade: Invalid pair ({pair})")
        return None
    for attempt in range(3):  # Retry up to 3 times
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
        # Align DataFrames by trimming to shortest length and resetting index
        if hedge_df is not None:
            min_length = min(len(btc_df), len(hedge_df))
            btc_df = btc_df.iloc[-min_length:].reset_index(drop=True).copy()
            hedge_df = hedge_df.iloc[-min_length:].reset_index(drop=True).copy()
            log_trade(f"Aligned DataFrames: BTC rows={len(btc_df)}, Hedge rows={len(hedge_df)}")
        else:
            btc_df = btc_df.reset_index(drop=True).copy()

        # Validate data before indicators
        if btc_df['close'].isna().any() or btc_df['close'].eq(0).any() or (hedge_df is not None and (hedge_df['close'].isna().any() or hedge_df['close'].eq(0).any())):
            log_trade("Error: Invalid or NaN values detected in OHLC data")
            return None, None

        btc_df['RSI'] = RSIIndicator(btc_df['close'], RSI_PERIOD).rsi()
        btc_df['EMA'] = EMAIndicator(btc_df['close'], EMA_PERIOD).ema_indicator()
        btc_df['ATR'] = AverageTrueRange(btc_df['high'], btc_df['low'], btc_df['close'], ATR_PERIOD).average_true_range()
        if hedge_df is not None:
            corr = btc_df['close'].pct_change().rolling(20).corr(hedge_df['close'].pct_change())
            btc_df['Hedge_Ratio'] = np.where(corr < 0.7, BASE_HEDGE_RATIO * 0.6, BASE_HEDGE_RATIO)
        else:
            btc_df['Hedge_Ratio'] = 0
        log_trade("Indicators calculated: RSI, EMA, ATR, Hedge Ratio")
        return btc_df, hedge_df
    except Exception as e:
        log_trade(f"Error calculating indicators: {str(e)}")
        return None, None

def execute_trade(pair, side, price, volume):
    if not pair or volume < MIN_BTC_VOLUME:
        log_trade(f"No trade executed: Invalid pair ({pair}) or volume ({volume:.6f}) below minimum ({MIN_BTC_VOLUME})")
        return None
    for attempt in range(3):  # Retry up to 3 times
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
    # Initial log to confirm bot start
    log_trade("Bot starting: Initializing Kraken API and account status")

    # Health check
    try:
        server_time = k.get_server_time()
        log_trade(f"Kraken API connected: Server time {server_time[1]}")
    except Exception as e:
        log_trade(f"Error connecting to Kraken API: {str(e)}")
        raise ValueError("Failed to connect to Kraken API. Check API key permissions or Kraken status.")

    # Try multiple USD currency codes
    usd_codes = ['ZUSD', 'USD', 'USDT']
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
            log_trade(f"Error: No sufficient USD balance found in {usd_codes}. Available balances: {balance.index.tolist()}. Minimum ${MIN_USD_BALANCE} required.")
            raise ValueError(f"No sufficient USD balance found in {usd_codes}. Ensure account has at least ${MIN_USD_BALANCE} in USD, USDT, or equivalent.")
    except Exception as e:
        log_trade(f"Error fetching portfolio balance: {str(e)}. Available balances: {balance.index.tolist() if balance is not None else 'None'}")
        raise ValueError("Failed to fetch portfolio balance. Check API key permissions, Kraken status, or account funding.")

    # Check BTC balance
    btc_codes = ['XXBT', 'XBT', 'BTC']
    for code in btc_codes:
        try:
            btc_balance = float(balance.loc[code].iloc[0])
            log_trade(f"BTC balance found: {code} = {btc_balance:.6f} BTC")
            break
        except KeyError:
            continue
    if btc_balance == 0:
        log_trade("Warning: No BTC balance found, assuming 0. Please check Kraken account for BTC availability (may be locked in open orders, long positions, or sub-account).")

    # Calculate total portfolio value
    btc_price = 106200  # Approximate from logs; will be updated in loop
    portfolio_value = fiat_balance + (btc_balance * btc_price)
    log_trade(f"Initial portfolio value: ${portfolio_value:.2f} (Fiat: ${fiat_balance:.2f}, BTC: {btc_balance:.6f} @ ${btc_price:.2f})")

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
            # Periodic health check (every 20 minutes)
            if time.time() - last_health_check >= HEALTH_CHECK_INTERVAL:
                log_trade("Health check: Bot running, checking API connectivity")
                try:
                    server_time = k.get_server_time()
                    log_trade(f"Health check: Kraken API connected, Server time {server_time[1]}")
                    balance = k.get_account_balance()
                    log_trade(f"Health check: Available balances: {balance.index.tolist()}")
                    btc_balance = 0
                    for code in btc_codes:
                        try:
                            btc_balance = float(balance.loc[code].iloc[0])
                            log_trade(f"Health check: BTC balance found: {code} = {btc_balance:.6f} BTC")
                            break
                        except KeyError:
                            continue
                    if btc_balance == 0:
                        log_trade("Health check: Warning: No BTC balance found, assuming 0.")
                    for code in usd_codes:
                        if code in balance.index:
                            fiat_balance = float(balance.loc[code].iloc[0])
                            log_trade(f"Health check: Portfolio balance found: {code} = ${fiat_balance:.2f}")
                            break
                    portfolio_value = fiat_balance + (btc_balance * btc_price)
                    log_trade(f"Health check: Updated portfolio value: ${portfolio_value:.2f}")
                except Exception as e:
                    log_trade(f"Health check: Error connecting to Kraken API: {str(e)}")
                last_health_check = time.time()

            # Debug mode: Log loop start
            if DEBUG_MODE:
                log_trade("Debug: Starting trade cycle")

            # Fetch data
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
            
            # Current values
            btc_price = btc_df['close'].iloc[-1]
            rsi = btc_df['RSI'].iloc[-1]
            ema = btc_df['EMA'].iloc[-1]
            atr = btc_df['ATR'].iloc[-1]
            hedge_ratio = btc_df['Hedge_Ratio'].iloc[-1]
            hedge_name = HEDGE_PAIR.split('Z')[0] if HEDGE_PAIR else 'None'
            current_time = time.time()

            # Update portfolio value with current BTC price
            portfolio_value = fiat_balance + (btc_balance * btc_price)
            log_trade(f"Updated portfolio value: ${portfolio_value:.2f} (Fiat: ${fiat_balance:.2f}, BTC: {btc_balance:.6f} @ ${btc_price:.2f})")

            # Log state
            log_trade(f"Price: ${btc_price:.2f} | RSI: {rsi:.1f} | EMA: ${ema:.2f} | ATR: ${atr:.2f} | Stage: {trade_state['stage']} | Hedge: {hedge_ratio:.2f}x {hedge_name}")

            # Check if trading conditions are met
            if not (30 < rsi < 70):
                log_trade(f"No trade: RSI ({rsi:.1f}) outside 30-70 range")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue
            if not (btc_price > ema):
                log_trade(f"No trade: Price (${btc_price:.2f}) below EMA (${ema:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            # Check exposure
            btc_exposure = btc_balance * btc_price
            exposure_limit = portfolio_value * MAX_EXPOSURE
            if btc_exposure > exposure_limit:
                log_trade(f"No trade: Max exposure reached (BTC: ${btc_exposure:.2f}, Limit: ${exposure_limit:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            # Check available funds for buy
            buy_value = FIRST_BUY_PCT * portfolio_value
            if fiat_balance < buy_value:
                log_trade(f"No trade: Insufficient USD balance (${fiat_balance:.2f}) for buy (${buy_value:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            # Buy logic
            if btc_price > ema and 30 < rsi < 70:  # Stagnant/trending market
                log_trade(f"Checking buy conditions: RSI={rsi:.1f}, Stage={trade_state['stage']}")
                if trade_state['stage'] == 0 and rsi <= RSI_BUY_THRESHOLDS[0]:
                    # First buy: 20%
                    btc_volume = max((FIRST_BUY_PCT * portfolio_value) / btc_price, MIN_BTC_VOLUME)
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
                        fiat_balance -= btc_volume * btc_price  # Update fiat balance
                        btc_balance += btc_volume  # Update BTC balance
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")
                
                elif trade_state['stage'] == 1 and (rsi <= RSI_BUY_THRESHOLDS[1] or btc_price < trade_state['entry_price'] * (1 - DIP_THRESHOLDS[0])):
                    # Second buy: 30% of remaining
                    remaining_value = portfolio_value - (trade_state['btc_volume'] * trade_state['avg_entry'])
                    btc_volume = max((SECOND_BUY_PCT * remaining_value) / btc_price, MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    buy_value = btc_volume * btc_price
                    if fiat_balance < buy_value:
                        log_trade(f"No trade: Insufficient USD balance (${fiat_balance:.2f}) for buy (${buy_value:.2f})")
                        await asyncio.sleep(CYCLE_INTERVAL)
                        continue
                    log_trade(f"Attempting buy: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        total_btc = trade_state['btc_volume'] + btc_volume
                        trade_state['avg_entry'] = (trade_state['avg_entry'] * trade_state['btc_volume'] + btc_price * btc_volume) / total_btc
                        trade_state['stage'] = 2
                        trade_state['btc_volume'] = total_btc
                        trade_state['hedge_volume'] += hedge_volume
                        trade_state['hedge_start_time'] = time.time()
                        fiat_balance -= btc_volume * btc_price
                        btc_balance += btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")
                
                elif trade_state['stage'] == 2 and (rsi <= RSI_BUY_THRESHOLDS[2] or btc_price < trade_state['entry_price'] * (1 - DIP_THRESHOLDS[1])):
                    # All-in buy
                    remaining_value = portfolio_value - (trade_state['btc_volume'] * trade_state['avg_entry'])
                    btc_volume = max(remaining_value / btc_price, MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    buy_value = btc_volume * btc_price
                    if fiat_balance < buy_value:
                        log_trade(f"No trade: Insufficient USD balance (${fiat_balance:.2f}) for buy (${buy_value:.2f})")
                        await asyncio.sleep(CYCLE_INTERVAL)
                        continue
                    log_trade(f"Attempting buy: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        total_btc = trade_state['btc_volume'] + btc_volume
                        trade_state['avg_entry'] = (trade_state['avg_entry'] * trade_state['btc_volume'] + btc_price * btc_volume) / total_btc
                        trade_state['stage'] = 3
                        trade_state['btc_volume'] = total_btc
                        trade_state['hedge_volume'] += hedge_volume
                        trade_state['hedge_start_time'] = time.time()
                        fiat_balance -= btc_volume * btc_price
                        btc_balance += btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")

            # Sell logic with stop-loss
            if trade_state['stage'] > 0:
                log_trade(f"Checking sell conditions: RSI={rsi:.1f}, Stage={trade_state['sell_stage']}")
                if btc_price < trade_state['avg_entry'] * (1 - STOP_LOSS_PCT):
                    # Stop-loss: Sell all
                    btc_volume = max(trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = trade_state['hedge_volume']
                    log_trade(f"Stop-loss triggered: Price (${btc_price:.2f}) < {STOP_LOSS_PCT*100}% below avg entry (${trade_state['avg_entry']:.2f})")
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
                elif rsi > RSI_SELL_THRESHOLDS[0] and trade_state['sell_stage'] == 0:
                    # First sell: 20%
                    btc_volume = max(FIRST_SELL_PCT * trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting sell: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        trade_state['btc_volume'] -= btc_volume
                        trade_state['hedge_volume'] -= hedge_volume
                        trade_state['sell_stage'] = 1
                        fiat_balance += btc_volume * btc_price
                        btc_balance -= btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")
                
                elif rsi > RSI_SELL_THRESHOLDS[1] and trade_state['sell_stage'] == 1:
                    # Second sell: 30% of remaining
                    btc_volume = max(SECOND_SELL_PCT * trade_state['btc_volume'], MIN_BTC_VOLUME)
                    hedge_volume = btc_volume * hedge_ratio
                    log_trade(f"Attempting sell: BTC volume={btc_volume:.6f}, Hedge volume={hedge_volume:.6f}")
                    order = execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    if order:
                        execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                        trade_state['btc_volume'] -= btc_volume
                        trade_state['hedge_volume'] -= hedge_volume
                        trade_state['sell_stage'] = 2
                        fiat_balance += btc_volume * btc_price
                        btc_balance -= btc_volume
                        log_trade(f"Balance updated: Fiat=${fiat_balance:.2f}, BTC={btc_balance:.6f}")
                
                elif (rsi >= RSI_SELL_THRESHOLDS[2] or btc_price < ema or btc_price > trade_state['avg_entry'] * 1.012) and trade_state['btc_volume'] > 0:
                    # Sell all
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

            # Debug mode: Log loop end
            if DEBUG_MODE:
                log_trade("Debug: Trade cycle completed")

            await asyncio.sleep(CYCLE_INTERVAL)
        except Exception as e:
            log_trade(f"Error in main loop: {str(e)}")
            await asyncio.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    log_trade("Bot initialized: Entering main loop")
    asyncio.run(main())
