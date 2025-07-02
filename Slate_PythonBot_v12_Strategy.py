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
MAX_EXPOSURE = 0.7
BASE_HEDGE_RATIO = 0.5
HEDGE_MAX_DURATION = 3600  # 1 hour in seconds
LOG_FILE = 'trade_log.txt'
CYCLE_INTERVAL = 30  # Seconds
MIN_USD_BALANCE = 100  # Minimum USD balance required
HEALTH_CHECK_INTERVAL = 300  # Log health check every 5 minutes

def get_ohlc_data(pair):
    if not pair:
        return None
    try:
        ohlc, _ = k.get_ohlc_data(pair, interval=INTERVAL, ascending=True)
        time.sleep(1)  # API rate limit
        return ohlc
    except Exception as e:
        log_trade(f"Error fetching OHLC data for {pair}: {str(e)}")
        return None

def calculate_indicators(btc_df, hedge_df):
    btc_df['RSI'] = RSIIndicator(btc_df['close'], RSI_PERIOD).rsi()
    btc_df['EMA'] = EMAIndicator(btc_df['close'], EMA_PERIOD).ema_indicator()
    btc_df['ATR'] = AverageTrueRange(btc_df['high'], btc_df['low'], btc_df['close'], ATR_PERIOD).average_true_range()
    if hedge_df is not None:
        corr = btc_df['close'].pct_change().rolling(20).corr(hedge_df['close'].pct_change())
        btc_df['Hedge_Ratio'] = np.where(corr < 0.7, BASE_HEDGE_RATIO * 0.6, BASE_HEDGE_RATIO)
    else:
        btc_df['Hedge_Ratio'] = 0
    return btc_df, hedge_df

def log_trade(message):
    with open(LOG_FILE, 'a') as f:
        timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"{timestamp} | {message}\n")
    print(f"{timestamp} | {message}")

def execute_trade(pair, side, price, volume):
    if not pair or volume == 0:
        return None
    try:
        order = k.add_order(pair, side, 'market', volume, price=price)
        log_trade(f"Executed {side} order on {pair}: Price: ${price:.2f}, Volume: {volume:.6f}")
        time.sleep(1)
        return order
    except Exception as e:
        log_trade(f"Error executing {side} order on {pair}: {str(e)}")
        return None

async def main():
    # Health check
    log_trade("Bot starting: Verifying API connectivity and account status")
    try:
        server_time = k.get_server_time()
        log_trade(f"Kraken API connected: Server time {server_time[1]}")  # Tuple index 1 for RFC1123 time
    except Exception as e:
        log_trade(f"Error connecting to Kraken API: {str(e)}")
        raise ValueError("Failed to connect to Kraken API. Check API key permissions or Kraken status.")

    # Try multiple USD currency codes
    usd_codes = ['ZUSD', 'USD', 'USDT']
    portfolio_value = None
    balance = None
    try:
        balance = k.get_account_balance()
        log_trade(f"Available balances: {balance.index.tolist()}")
        for code in usd_codes:
            if code in balance.index:
                portfolio_value = float(balance.loc[code].iloc[0])
                log_trade(f"Portfolio balance found: {code} = ${portfolio_value:.2f}")
                break
        if portfolio_value is None or portfolio_value < MIN_USD_BALANCE:
            log_trade(f"Error: No sufficient USD balance found in {usd_codes}. Available balances: {balance.index.tolist()}. Minimum ${MIN_USD_BALANCE} required.")
            raise ValueError(f"No sufficient USD balance found in {usd_codes}. Ensure account has at least ${MIN_USD_BALANCE} in USD, USDT, or equivalent.")
    except Exception as e:
        log_trade(f"Error fetching portfolio balance: {str(e)}. Available balances: {balance.index.tolist() if balance is not None else 'None'}")
        raise ValueError("Failed to fetch portfolio balance. Check API key permissions, Kraken status, or account funding.")

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
            # Periodic health check (every 5 minutes)
            if time.time() - last_health_check >= HEALTH_CHECK_INTERVAL:
                log_trade("Health check: Bot running, checking API connectivity")
                try:
                    server_time = k.get_server_time()
                    log_trade(f"Health check: Kraken API connected, Server time {server_time[1]}")
                    balance = k.get_account_balance()
                    log_trade(f"Health check: Available balances: {balance.index.tolist()}")
                except Exception as e:
                    log_trade(f"Health check: Error connecting to Kraken API: {str(e)}")
                last_health_check = time.time()

            # Fetch data
            btc_df = get_ohlc_data(BTC_PAIR)
            hedge_df = get_ohlc_data(HEDGE_PAIR) if HEDGE_PAIR else None
            if btc_df is None or (HEDGE_PAIR and hedge_df is None):
                log_trade("Failed to fetch market data, retrying...")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue
            
            btc_df, hedge_df = calculate_indicators(btc_df, hedge_df)
            
            # Current values
            btc_price = btc_df['close'].iloc[-1]
            rsi = btc_df['RSI'].iloc[-1]
            ema = btc_df['EMA'].iloc[-1]
            atr = btc_df['ATR'].iloc[-1]
            hedge_ratio = btc_df['Hedge_Ratio'].iloc[-1]
            hedge_name = HEDGE_PAIR.split('Z')[0] if HEDGE_PAIR else 'None'
            current_time = time.time()

            # Log state
            log_trade(f"Price: ${btc_price:.2f} | RSI: {rsi:.1f} | EMA: ${ema:.2f} | ATR: {atr:.2f} | Stage: {trade_state['stage']} | Hedge: {hedge_ratio:.2f}x {hedge_name}")

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
            btc_exposure = float(k.get_account_balance()['XXBT'].iloc[0]) * btc_price
            if btc_exposure / portfolio_value > MAX_EXPOSURE:
                log_trade(f"No trade: Max exposure reached (BTC: ${btc_exposure:.2f}, Limit: ${portfolio_value * MAX_EXPOSURE:.2f})")
                await asyncio.sleep(CYCLE_INTERVAL)
                continue

            # Check hedge duration
            if HEDGE_PAIR and trade_state['hedge_volume'] > 0 and (current_time - trade_state['hedge_start_time']) > HEDGE_MAX_DURATION:
                execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, trade_state['hedge_volume'])
                trade_state['hedge_volume'] = 0
                trade_state['hedge_start_time'] = 0
                log_trade("Closed hedge due to max duration")

            # Buy logic
            if btc_price > ema and 30 < rsi < 70:  # Stagnant/trending market
                if trade_state['stage'] == 0 and rsi < RSI_BUY_THRESHOLDS[0]:
                    # First buy: 20%
                    btc_volume = (FIRST_BUY_PCT * portfolio_value) / btc_price
                    hedge_volume = btc_volume * hedge_ratio
                    execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
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
                
                elif trade_state['stage'] == 1 and (rsi < RSI_BUY_THRESHOLDS[1] or btc_price < trade_state['entry_price'] * (1 - DIP_THRESHOLDS[0])):
                    # Second buy: 30% of remaining
                    remaining_value = portfolio_value - (trade_state['btc_volume'] * trade_state['avg_entry'])
                    btc_volume = (SECOND_BUY_PCT * remaining_value) / btc_price
                    hedge_volume = btc_volume * hedge_ratio
                    execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                    total_btc = trade_state['btc_volume'] + btc_volume
                    trade_state['avg_entry'] = (trade_state['avg_entry'] * trade_state['btc_volume'] + btc_price * btc_volume) / total_btc
                    trade_state['stage'] = 2
                    trade_state['btc_volume'] = total_btc
                    trade_state['hedge_volume'] += hedge_volume
                    trade_state['hedge_start_time'] = time.time()
                
                elif trade_state['stage'] == 2 and (rsi <= RSI_BUY_THRESHOLDS[2] or btc_price < trade_state['entry_price'] * (1 - DIP_THRESHOLDS[1])):
                    # All-in buy
                    remaining_value = portfolio_value - (trade_state['btc_volume'] * trade_state['avg_entry'])
                    btc_volume = remaining_value / btc_price
                    hedge_volume = btc_volume * hedge_ratio
                    execute_trade(BTC_PAIR, 'buy', btc_price, btc_volume)
                    execute_trade(HEDGE_PAIR, 'sell', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                    total_btc = trade_state['btc_volume'] + btc_volume
                    trade_state['avg_entry'] = (trade_state['avg_entry'] * trade_state['btc_volume'] + btc_price * btc_volume) / total_btc
                    trade_state['stage'] = 3
                    trade_state['btc_volume'] = total_btc
                    trade_state['hedge_volume'] += hedge_volume
                    trade_state['hedge_start_time'] = time.time()

            # Sell logic
            if trade_state['stage'] > 0:
                if rsi > RSI_SELL_THRESHOLDS[0] and trade_state['sell_stage'] == 0:
                    # First sell: 20%
                    btc_volume = FIRST_SELL_PCT * trade_state['btc_volume']
                    hedge_volume = btc_volume * hedge_ratio
                    execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                    trade_state['btc_volume'] -= btc_volume
                    trade_state['hedge_volume'] -= hedge_volume
                    trade_state['sell_stage'] = 1
                
                elif rsi > RSI_SELL_THRESHOLDS[1] and trade_state['sell_stage'] == 1:
                    # Second sell: 30% of remaining
                    btc_volume = SECOND_SELL_PCT * trade_state['btc_volume']
                    hedge_volume = btc_volume * hedge_ratio
                    execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                    trade_state['btc_volume'] -= btc_volume
                    trade_state['hedge_volume'] -= hedge_volume
                    trade_state['sell_stage'] = 2
                
                elif (rsi >= RSI_SELL_THRESHOLDS[2] or btc_price < ema or btc_price < trade_state['avg_entry'] * (1 - 0.8 * atr / btc_price) or btc_price > trade_state['avg_entry'] * 1.012) and trade_state['btc_volume'] > 0:
                    # Sell all
                    btc_volume = trade_state['btc_volume']
                    hedge_volume = trade_state['hedge_volume']
                    execute_trade(BTC_PAIR, 'sell', btc_price, btc_volume)
                    execute_trade(HEDGE_PAIR, 'buy', hedge_df['close'].iloc[-1] if hedge_df is not None else 0, hedge_volume)
                    trade_state = {
                        'stage': 0,
                        'entry_price': 0,
                        'btc_volume': 0,
                        'avg_entry': 0,
                        'hedge_volume': 0,
                        'hedge_start_time': 0,
                        'sell_stage': 0
                    }

            await asyncio.sleep(CYCLE_INTERVAL)
        except Exception as e:
            log_trade(f"Error in main loop: {str(e)}")
            await asyncio.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
