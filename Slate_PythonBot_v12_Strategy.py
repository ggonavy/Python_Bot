import os
import time
import pandas as pd
import krakenex
from pykrakenapi import KrakenAPI
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from flask import Flask

app = Flask(__name__)

# Kraken API setup
k = krakenex.API(key=os.getenv('KRAKEN_API_KEY'), secret=os.getenv('KRAKEN_API_SECRET'))
kraken = KrakenAPI(k)

# Trading parameters
PAIR = 'XXBTZUSD'
INTERVAL = 15  # 15-minute candles
SLEEP_INTERVAL = 3  # seconds
BUY_LADDER = [47, 42, 37, 32]
SELL_LADDER = [73, 77, 81, 85]
POSITION_SIZE = 0.001  # BTC per trade (~$109 at $109K)
RSI_PERIOD = 14
EMA_PERIOD = 26
ATR_PERIOD = 14

def get_ohlc(pair=PAIR, interval=INTERVAL):
    """Fetch OHLC data from Kraken."""
    try:
        ohlc, _ = kraken.get_ohlc_data(pair, interval=interval, ascending=True, since=int(time.time() - 7200))
        ohlc = ohlc.dropna()
        if len(ohlc) < RSI_PERIOD + 1:
            print(f"Error: Only {len(ohlc)} candles, need {RSI_PERIOD + 1}")
            return None
        print(f"OHLC timestamp: {ohlc.index[-1]} | Last close: {ohlc['close'].iloc[-1]:.2f} | Candles: {len(ohlc)}")
        return ohlc[-50:]
    except Exception as e:
        print(f"OHLC fetch error: {e}")
        return None

def get_rsi(ohlc, period=RSI_PERIOD):
    """Calculate RSI."""
    try:
        close = ohlc['close'].copy()
        if len(close) < period:
            print(f"Error: Only {len(close)} closes, need {period}")
            return None
        rsi = RSIIndicator(close, window=period, fillna=False).rsi()
        rsi_value = rsi.iloc[-1]
        if pd.isna(rsi_value):
            print("Error: RSI is NaN")
            return None
        print(f"Raw close prices (last 5): {[f'{x:.2f}' for x in close[-5:]]}")
        print(f"Calculated RSI: {rsi_value:.2f}")
        return rsi_value
    except Exception as e:
        print(f"RSI error: {e}")
        return None

def get_ema(ohlc, period=EMA_PERIOD):
    """Calculate EMA."""
    try:
        close = ohlc['close']
        ema = EMAIndicator(close, window=period).ema_indicator()
        return ema.iloc[-1]
    except Exception as e:
        print(f"EMA error: {e}")
        return None

def get_atr(ohlc, period=ATR_PERIOD):
    """Calculate ATR."""
    try:
        atr = AverageTrueRange(ohlc['high'], ohlc['low'], ohlc['close'], window=period)
        return atr.average_true_range().iloc[-1]
    except Exception as e:
        print(f"ATR error: {e}")
        return None

def execute_trade(side, volume, price):
    """Execute trade on Kraken."""
    try:
        order = kraken.add_standard_order(
            pair=PAIR, type=side, ordertype='market', volume=volume
        )
        print(f"{side.capitalize()} order placed: {order} at ~${price:.2f}")
        return True
    except Exception as e:
        print(f"Trade error: {e}")
        return False

def check_trades(ohlc, balance):
    """Check for buy/sell opportunities."""
    rsi = get_rsi(ohlc)
    price = ohlc['close'].iloc[-1]
    btc_balance = balance.get('XXBT', 0)
    usd_balance = balance.get('ZUSD', 0)

    if rsi is None:
        print("Skipping trade check: Invalid RSI")
        return False

    print(f"Checking trade: RSI {rsi:.2f}, BTC {btc_balance:.6f}, USD {usd_balance:.2f}")

    # Buy logic
    for level in BUY_LADDER:
        if rsi <= level and usd_balance > price * POSITION_SIZE * 1.01:  # 1% buffer
            print(f"Buy triggered: RSI {rsi:.2f} <= {level}, Price: ${price:.2f}")
            return execute_trade('buy', POSITION_SIZE, price)

    # Sell logic
    for level in SELL_LADDER:
        if rsi >= level and btc_balance >= POSITION_SIZE:
            print(f"Sell triggered: RSI {rsi:.2f} >= {level}, Price: ${price:.2f}")
            return execute_trade('sell', POSITION_SIZE, price)

    return False

@app.route('/')
def status():
    return "Slate_PythonBot_v12_Strategy is running!"

def main():
    print("Starting Slate_PythonBot_v12_Strategy...")
    while True:
        try:
            ohlc = get_ohlc()
            if ohlc is None:
                print("Retrying OHLC fetch...")
                time.sleep(SLEEP_INTERVAL)
                continue

            price = ohlc['close'].iloc[-1]
            rsi = get_rsi(ohlc)
            ema = get_ema(ohlc)
            atr = get_atr(ohlc)

            if any(x is None for x in [rsi, ema, atr]):
                print("Skipping loop: Invalid indicator values")
                time.sleep(SLEEP_INTERVAL)
                continue

            balance = kraken.get_balance()
            print(f"Price: ${price:.2f} | RSI: {rsi:.2f} | EMA: ${ema:.2f} | ATR: {atr:.4f}")
            check_trades(ohlc, balance)

        except Exception as e:
            print(f"Main loop error: {e}")
        
        time.sleep(SLEEP_INTERVAL)

if __name__ == '__main__':
    main()
