import krakenex
try:
    from pykrakenapi import KrakenAPI
except ImportError:
    logger.error("pykrakenapi import failed. Ensure it's installed correctly.")
    exit(1)
import pandas as pd
import numpy as np
import backtrader as bt
import time
import os
import logging
from flask import Flask
import threading

# Setup logging for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('slate_bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Flask app for health check
app = Flask(__name__)

@app.route('/health')
def health():
    return 'OK', 200

class SlateBot:
    def __init__(self, main_key, main_secret, hedge_key=None, hedge_secret=None):
        """Initialize bot with main and hedge Kraken API credentials."""
        self.k_main = krakenex.API(key=main_key, secret=main_secret)
        self.kapi_main = KrakenAPI(self.k_main)
        self.k_hedge = None
        self.kapi_hedge = None
        if hedge_key and hedge_secret:
            self.k_hedge = krakenex.API(key=hedge_key, secret=hedge_secret)
            self.kapi_hedge = KrakenAPI(self.k_hedge)
        self.main_pair = 'XBTUSD'
        self.hedge_pair = 'ETHUSD'
        self.interval = 5  # 5-minute candles
        self.rsi_periods = 14
        self.ema_periods = 12
        self.candles_to_fetch = 50
        self.last_candle_time = 0
        self.buy_ladder = [50, 45, 40, 35]
        self.sell_ladder = [70, 75, 80, 85]
        self.base_trade_size = 0.005
        self.ladder_multipliers = [1, 1.5, 2, 3]
        self.max_retries = 3
        self.retry_delay = 5
        self.stop_loss_percent = 0.05  # 5% stop-loss
        self.open_orders = {}  # Track open orders for stop-loss

    def get_ohlc_data(self, kapi, pair):
        """Fetch OHLC data for the specified pair, limited to 50 candlesticks."""
        for attempt in range(self.max_retries):
            try:
                since = int(time.time()) - (self.candles_to_fetch * self.interval * 60 * 1.5)
                ohlc, _ = kapi.get_ohlc_data(pair, interval=self.interval, since=since, ascending=True)
                ohlc = ohlc.tail(self.candles_to_fetch)
                logger.info(f"Retrieved {len(ohlc)} candlesticks for {pair}")
                if len(ohlc) < self.candles_to_fetch:
                    logger.warning(f"Only {len(ohlc)} candlesticks for {pair}, needed {self.candles_to_fetch}")
                return ohlc
            except Exception as e:
                logger.error(f"Error fetching OHLC for {pair} (attempt {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    return None
        return None

    def get_rsi_and_ema(self, ohlc_data):
        """Calculate RSI and EMA from OHLC data using backtrader."""
        if ohlc_data is None or len(ohlc_data) < max(self.rsi_periods, self.ema_periods):
            logger.error(f"Not enough data: {len(ohlc_data)} candlesticks available")
            return None, None
        class RSIStrategy(bt.Strategy):
            params = (('rsi_period', 14), ('ema_period', 12))
            def __init__(self):
                self.rsi = bt.indicators.RSI_SMA(self.data.close, period=self.params.rsi_period)
                self.ema = bt.indicators.EMA(self.data.close, period=self.params.ema_period)
                self.last_rsi = None
                self.last_ema = None

            def next(self):
                self.last_rsi = self.rsi[0]
                self.last_ema = self.ema[0]

        data = bt.feeds.PandasData(
            dataname=ohlc_data,
            open='open',
            high='high',
            low='low',
            close='close',
            volume='volume'
        )
        cerebro = bt.Cerebro()
        cerebro.addstrategy(RSIStrategy, rsi_period=self.rsi_periods, ema_period=self.ema_periods)
        cerebro.adddata(data)
        cerebro.run()
        strategy = cerebro.runstrats[0][0]
        rsi = strategy.last_rsi
        ema = strategy.last_ema
        if rsi is None or ema is None:
            logger.error("RSI or EMA value not set in strategy")
            return None, None
        return rsi, ema

    def get_current_price(self, kapi, pair):
        """Fetch current price for stop-loss checks."""
        try:
            ticker = kapi.get_ticker_information(pair)
            return float(ticker['c'].iloc[0])  # Last trade price
        except Exception as e:
            logger.error(f"Error fetching price for {pair}: {e}")
            return None

    def place_order(self, kapi, pair, side, volume, buy_price=None):
        """Place a market order on Kraken and track for stop-loss."""
        try:
            order = kapi.add_standard_order(
                pair=pair,
                type=side,
                ordertype='market',
                volume=volume
            )
            logger.info(f"Placed {side} order for {volume} {pair}: {order}")
            if side == 'buy' and buy_price:
                self.open_orders[order['txid'][0]] = {'pair': pair, 'buy_price': buy_price, 'volume': volume}
            return order
        except Exception as e:
            logger.error(f"Error placing {side} order for {pair}: {e}")
            return None

    def check_stop_loss(self, kapi, pair):
        """Check open orders for stop-loss triggers."""
        current_price = self.get_current_price(kapi, pair)
        if current_price is None:
            return
        for order_id, order_info in list(self.open_orders.items()):
            if order_info['pair'] == pair:
                buy_price = order_info['buy_price']
                if current_price <= buy_price * (1 - self.stop_loss_percent):
                    logger.info(f"Stop-loss triggered for {pair} at {current_price}, selling {order_info['volume']}")
                    self.place_order(kapi, pair, 'sell', order_info['volume'])
                    del self.open_orders[order_id]

    def get_trade_action(self, rsi, ema, current_price, pair):
        """Determine trade action based on RSI and EMA."""
        if rsi is None or ema is None or current_price is None:
            return None, 0
        if pair == self.main_pair:
            for i, rsi_level in enumerate(self.buy_ladder):
                if rsi <= rsi_level and current_price < ema:  # Buy when RSI low and price below EMA
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'buy', volume
            for i, rsi_level in enumerate(self.sell_ladder):
                if rsi >= rsi_level and current_price > ema:  # Sell when RSI high and price above EMA
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'sell', volume
        elif pair == self.hedge_pair:
            for i, rsi_level in enumerate(self.buy_ladder):
                if rsi <= rsi_level and current_price < ema:  # Sell ETH when RSI low
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'sell', volume
            for i, rsi_level in enumerate(self.sell_ladder):
                if rsi >= rsi_level and current_price > ema:  # Buy ETH when RSI high
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'buy', volume
        return None, 0

    def execute_trades(self):
        """Execute trades for main and hedge accounts based on RSI and EMA."""
        ohlc_main = self.get_ohlc_data(self.kapi_main, self.main_pair)
        rsi_main, ema_main = self.get_rsi_and_ema(ohlc_main)
        if rsi_main is not None and ema_main is not None:
            logger.info(f"RSI for {self.main_pair}: {rsi_main:.2f}, EMA: {ema_main:.2f}")
            current_price = self.get_current_price(self.kapi_main, self.main_pair)
            if current_price:
                action, volume = self.get_trade_action(rsi_main, ema_main, current_price, self.main_pair)
                if action and volume > 0:
                    self.place_order(self.kapi_main, self.main_pair, action, volume, buy_price=current_price if action == 'buy' else None)
                    if action == 'buy':
                        self.check_stop_loss(self.kapi_main, self.main_pair)
                if self.kapi_hedge:
                    ohlc_hedge = self.get_ohlc_data(self.kapi_hedge, self.hedge_pair)
                    rsi_hedge, ema_hedge = self.get_rsi_and_ema(ohlc_hedge)
                    if rsi_hedge is not None and ema_hedge is not None:
                        logger.info(f"RSI for {self.hedge_pair}: {rsi_hedge:.2f}, EMA: {ema_hedge:.2f}")
                        hedge_price = self.get_current_price(self.kapi_hedge, self.hedge_pair)
                        if hedge_price:
                            hedge_action, hedge_volume = self.get_trade_action(rsi_hedge, ema_hedge, hedge_price, self.hedge_pair)
                            if hedge_action and hedge_volume > 0:
                                self.place_order(self.kapi_hedge, self.hedge_pair, hedge_action, hedge_volume, buy_price=hedge_price if hedge_action == 'buy' else None)
                                if hedge_action == 'buy':
                                    self.check_stop_loss(self.kapi_hedge, self.hedge_pair)
            else:
                logger.info(f"No trade for {self.main_pair}: RSI {rsi_main:.2f}, EMA {ema_main:.2f}")
        else:
            logger.info(f"No RSI/EMA calculated for {self.main_pair}")

    def run(self):
        """Main bot loop."""
        logger.info("Starting SlateBot...")
        while True:
            try:
                current_time = int(time.time())
                if current_time - self.last_candle_time >= self.interval * 60:
                    self.execute_trades()
                    self.last_candle_time = current_time
                time.sleep(60)
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(60)

def start_flask():
    """Run Flask server in a separate thread."""
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))

if __name__ == "__main__":
    # Load main account credentials from environment variables
    main_key = os.getenv("KRAKEN_API_KEY")
    main_secret = os.getenv("KRAKEN_API_SECRET")
    
    # Load hedge account credentials from secret files
    try:
        with open('/etc/secrets/KRAKEN_API_KEY_HEDGE', 'r') as f:
            hedge_key = f.read().strip()
        with open('/etc/secrets/KRAKEN_API_SECRET_HEDGE', 'r') as f:
            hedge_secret = f.read().strip()
    except Exception as e:
        logger.error(f"Error reading hedge secret files: {e}")
        hedge_key = None
        hedge_secret = None
    
    if not main_key or not main_secret:
        logger.error("Missing main Kraken API credentials")
        exit(1)
    
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    bot = SlateBot(main_key, main_secret, hedge_key, hedge_secret)
    bot.run()
