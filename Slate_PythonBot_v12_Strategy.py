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
from collections import deque

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
        self.kapi_main = KrakenAPI(self.k_main, tier=2)  # Kraken Pro tier (~50 calls/min)
        self.k_hedge = None
        self.kapi_hedge = None
        if hedge_key and hedge_secret:
            self.k_hedge = krakenex.API(key=hedge_key, secret=hedge_secret)
            self.kapi_hedge = KrakenAPI(self.k_hedge, tier=2)  # Kraken Pro tier
        self.main_pair = 'XBTUSD'
        self.hedge_pair = 'ETHUSD'
        self.interval = 5  # 5-minute candles
        self.rsi_periods = 14
        self.ema_periods = 12
        self.candles_to_fetch = 50
        self.last_candle_time = 0
        self.buy_ladder = [43, 38, 33, 28]
        self.sell_ladder = [70, 75, 80, 85]
        self.base_trade_size = 0.005
        self.ladder_multipliers = [1, 1.5, 2, 3]
        self.max_retries = 3
        self.retry_delay = 5
        self.stop_loss_percent = 0.05  # 5% stop-loss
        self.ema_tolerance = 0.03  # Allow price within 3% of EMA
        self.open_orders = {}  # Track open orders for stop-loss
        self.missed_signals = deque(maxlen=10)  # Queue for missed signals (max 10)
        self.ohlc_cache = {}  # Cache OHLC data
        self.ohlc_cache_time = {}  # Cache timestamps
        self.price_cache = {}  # Cache price data
        self.price_cache_time = {}  # Cache price timestamps
        self.api_call_count = 0  # Track API calls
        self.api_call_window = 60  # 60-second window for rate limiting
        self.api_call_timestamp = time.time()

    def manage_rate_limit(self):
        """Manage Kraken API rate limits (~50 calls/minute for Pro tier)."""
        current_time = time.time()
        if current_time - self.api_call_timestamp >= self.api_call_window:
            self.api_call_count = 0  # Reset counter after 60 seconds
            self.api_call_timestamp = current_time
        self.api_call_count += 1
        if self.api_call_count >= 45:  # Buffer below 50 calls/minute
            sleep_time = max(0, self.api_call_window - (current_time - self.api_call_timestamp))
            logger.warning(f"Approaching rate limit (count={self.api_call_count}). Sleeping for {sleep_time:.2f} seconds.")
            time.sleep(sleep_time)
            self.api_call_count = 0
            self.api_call_timestamp = time.time()

    def get_ohlc_data(self, kapi, pair):
        """Fetch OHLC data for the specified pair, limited to 50 candlesticks, with caching."""
        current_time = time.time()
        if pair in self.ohlc_cache and current_time - self.ohlc_cache_time.get(pair, 0) < 300:  # Cache for 5 minutes
            logger.info(f"Using cached OHLC data for {pair}")
            return self.ohlc_cache[pair]
        for attempt in range(self.max_retries):
            try:
                self.manage_rate_limit()
                since = int(time.time()) - (self.candles_to_fetch * self.interval * 60 * 1.5)
                ohlc, _ = kapi.get_ohlc_data(pair, interval=self.interval, since=since, ascending=True)
                ohlc = ohlc.tail(self.candles_to_fetch)
                logger.info(f"Retrieved {len(ohlc)} candlesticks for {pair}")
                if len(ohlc) < self.candles_to_fetch:
                    logger.warning(f"Only {len(ohlc)} candlesticks for {pair}, needed {self.candles_to_fetch}")
                self.ohlc_cache[pair] = ohlc
                self.ohlc_cache_time[pair] = current_time
                return ohlc
            except Exception as e:
                if "EGeneral:Temporary lockout" in str(e):
                    sleep_time = self.retry_delay * (2 ** attempt)  # Exponential backoff: 5s, 10s, 20s
                    logger.warning(f"Rate limit exceeded for {pair}. Sleeping for {sleep_time} seconds.")
                    time.sleep(sleep_time)
                else:
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

    def get_account_balance(self, kapi, pair):
        """Fetch available fiat (USD/ZUSD/USDT) or asset balance (XXBT/XETH) from Kraken."""
        for attempt in range(self.max_retries):
            try:
                self.manage_rate_limit()
                balance = kapi.get_account_balance()
                logger.info(f"Raw balance response for {pair}: {balance}")
                fiat_balance = float(balance.get('ZUSD', balance.get('USD', balance.get('USDT', 0))))
                asset_key = 'XXBT' if pair == 'XBTUSD' else 'XETH'
                asset_balance = float(balance.get(asset_key, 0))
                logger.info(f"Available fiat balance: ${fiat_balance:.2f}, asset balance: {asset_balance:.6f} {'BTC' if pair == 'XBTUSD' else 'ETH'}")
                if fiat_balance < 500 and pair == self.main_pair:
                    logger.warning(f"Low fiat balance: ${fiat_balance:.2f}. Top up Kraken account for {pair} trades.")
                if asset_balance < 0.2 and pair == self.hedge_pair:
                    logger.warning(f"Low asset balance: {asset_balance:.6f} ETH. Top up Kraken hedge account.")
                return fiat_balance, asset_balance
            except Exception as e:
                if "EGeneral:Temporary lockout" in str(e):
                    sleep_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Rate limit exceeded for balance fetch. Sleeping for {sleep_time} seconds.")
                    time.sleep(sleep_time)
                else:
                    logger.error(f"Error fetching balance for {pair} (attempt {attempt+1}/{self.max_retries}): {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                    else:
                        logger.error("Failed to fetch balance after retries. Check Kraken API key permissions.")
                        return 0, 0
        return 0, 0

    def get_current_price(self, kapi, pair):
        """Fetch current price for stop-loss and trade checks, with caching."""
        current_time = time.time()
        if pair in self.price_cache and current_time - self.price_cache_time.get(pair, 0) < 60:  # Cache for 60 seconds
            logger.info(f"Using cached price for {pair}: {self.price_cache[pair]:.2f}")
            return self.price_cache[pair]
        for attempt in range(self.max_retries):
            try:
                self.manage_rate_limit()
                ticker = kapi.get_ticker_information(pair)
                price = ticker['c'].iloc[0]
                if isinstance(price, list):
                    price = float(price[0])  # Handle nested list
                else:
                    price = float(price)
                self.price_cache[pair] = price
                self.price_cache_time[pair] = current_time
                logger.info(f"Current price for {pair}: {price:.2f}")
                return price
            except Exception as e:
                if "EGeneral:Temporary lockout" in str(e):
                    sleep_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Rate limit exceeded for price fetch. Sleeping for {sleep_time} seconds.")
                    time.sleep(sleep_time)
                else:
                    logger.error(f"Error fetching price for {pair} (attempt {attempt+1}/{self.max_retries}): {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                    else:
                        return None
        return None

    def place_order(self, kapi, pair, side, volume, buy_price=None):
        """Place a market order on Kraken and track for stop-loss."""
        try:
            self.manage_rate_limit()
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
                    logger.info(f"Stop-loss triggered for {pair} at {current_price:.2f}, selling {order_info['volume']}")
                    self.place_order(kapi, pair, 'sell', order_info['volume'])
                    del self.open_orders[order_id]

    def get_trade_action(self, rsi, ema, current_price, pair, fiat_balance=0, asset_balance=0):
        """Determine trade action based on RSI and EMA."""
        if rsi is None or ema is None or current_price is None:
            logger.info(f"No trade for {pair}: RSI {rsi}, EMA {ema}, Current Price {current_price}")
            self.missed_signals.append((pair, rsi, ema, current_price, time.time()))
            return None, 0
        logger.info(f"Checking trade for {pair}: RSI {rsi:.2f}, EMA {ema:.2f}, Current Price {current_price:.2f}")
        if pair == self.main_pair:
            for i, rsi_level in enumerate(self.buy_ladder):
                if rsi <= rsi_level and current_price <= ema * (1 + self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    if fiat_balance >= volume * current_price:
                        logger.info(f"Buy signal for {pair}: RSI {rsi:.2f} <= {rsi_level}, Price {current_price:.2f} <= EMA {ema:.2f} * {1 + self.ema_tolerance}, Volume {volume:.6f}")
                        return 'buy', volume
                    else:
                        logger.warning(f"Insufficient fiat balance (${fiat_balance:.2f}) for buy order of {volume} {pair} at {current_price:.2f}")
                        self.missed_signals.append((pair, rsi, ema, current_price, time.time()))
                        return None, 0
            for i, rsi_level in enumerate(self.sell_ladder):
                if rsi >= rsi_level and current_price >= ema * (1 - self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    if asset_balance >= volume:
                        logger.info(f"Sell signal for {pair}: RSI {rsi:.2f} >= {rsi_level}, Price {current_price:.2f} >= EMA {ema:.2f} * {1 - self.ema_tolerance}, Volume {volume:.6f}")
                        return 'sell', volume
                    else:
                        logger.warning(f"Insufficient asset balance ({asset_balance:.6f}) for sell order of {volume} {pair}")
                        self.missed_signals.append((pair, rsi, ema, current_price, time.time()))
                        return None, 0
        elif pair == self.hedge_pair:
            for i, rsi_level in enumerate(self.buy_ladder):
                if rsi <= rsi_level and current_price <= ema * (1 + self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    logger.info(f"Sell signal for {pair}: RSI {rsi:.2f} <= {rsi_level}, Price {current_price:.2f} <= EMA {ema:.2f} * {1 + self.ema_tolerance}, Volume {volume:.6f}")
                    return 'sell', volume
            for i, rsi_level in enumerate(self.sell_ladder):
                if rsi >= rsi_level and current_price >= ema * (1 - self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    logger.info(f"Buy signal for {pair}: RSI {rsi:.2f} >= {rsi_level}, Price {current_price:.2f} >= EMA {ema:.2f} * {1 - self.ema_tolerance}, Volume {volume:.6f}")
                    return 'buy', volume
        logger.info(f"No trade signal for {pair}: RSI {rsi:.2f}, EMA {ema:.2f}, Current Price {current_price:.2f}")
        return None, 0

    def retry_missed_signals(self):
        """Retry missed trade signals from the queue."""
        current_time = time.time()
        retry_signals = deque()
        while self.missed_signals:
            pair, rsi, ema, current_price, signal_time = self.missed_signals.popleft()
            if current_time - signal_time > 3600:  # Skip signals older than 1 hour
                continue
            for i, rsi_level in enumerate(self.buy_ladder if pair == self.main_pair else self.sell_ladder):
                if pair == self.main_pair and rsi <= rsi_level and current_price <= ema * (1 + self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    fiat_balance, _ = self.get_account_balance(self.kapi_main, pair)
                    if fiat_balance >= volume * current_price:
                        logger.info(f"Retrying missed buy signal for {pair}: RSI {rsi:.2f} <= {rsi_level}, Price {current_price:.2f} <= EMA {ema:.2f} * {1 + self.ema_tolerance}")
                        return 'buy', volume, pair
                elif pair == self.main_pair and rsi >= self.sell_ladder[i] and current_price >= ema * (1 - self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    _, asset_balance = self.get_account_balance(self.kapi_main, pair)
                    if asset_balance >= volume:
                        logger.info(f"Retrying missed sell signal for {pair}: RSI {rsi:.2f} >= {rsi_level}, Price {current_price:.2f} >= EMA {ema:.2f} * {1 - self.ema_tolerance}")
                        return 'sell', volume, pair
                elif pair == self.hedge_pair and rsi <= rsi_level and current_price <= ema * (1 + self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    logger.info(f"Retrying missed sell signal for {pair}: RSI {rsi:.2f} <= {rsi_level}, Price {current_price:.2f} <= EMA {ema:.2f} * {1 + self.ema_tolerance}")
                    return 'sell', volume, pair
                elif pair == self.hedge_pair and rsi >= self.sell_ladder[i] and current_price >= ema * (1 - self.ema_tolerance):
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    logger.info(f"Retrying missed buy signal for {pair}: RSI {rsi:.2f} >= {rsi_level}, Price {current_price:.2f} >= EMA {ema:.2f} * {1 - self.ema_tolerance}")
                    return 'buy', volume, pair
            retry_signals.append((pair, rsi, ema, current_price, signal_time))  # Re-queue if still valid
        self.missed_signals = retry_signals
        return None, 0, None

    def execute_trades(self):
        """Execute trades for main and hedge accounts based on RSI and EMA."""
        # Retry missed signals
        action, volume, pair = self.retry_missed_signals()
        if action and volume > 0:
            kapi = self.kapi_main if pair == self.main_pair else self.kapi_hedge
            self.place_order(kapi, pair, action, volume, buy_price=self.get_current_price(kapi, pair) if action == 'buy' else None)
            if action == 'buy':
                self.check_stop_loss(kapi, pair)
            return

        # Regular trade execution
        ohlc_main = self.get_ohlc_data(self.kapi_main, self.main_pair)
        rsi_main, ema_main = self.get_rsi_and_ema(ohlc_main)
        if rsi_main is not None and ema_main is not None:
            logger.info(f"RSI for {self.main_pair}: {rsi_main:.2f}, EMA: {ema_main:.2f}")
            fiat_balance, asset_balance = self.get_account_balance(self.kapi_main, self.main_pair)
            if fiat_balance < 500:
                logger.warning(f"Low fiat balance: ${fiat_balance:.2f}. Top up Kraken account for {self.main_pair} trades.")
            current_price = self.get_current_price(self.kapi_main, self.main_pair)
            if current_price:
                action, volume = self.get_trade_action(rsi_main, ema_main, current_price, self.main_pair, fiat_balance, asset_balance)
                if action and volume > 0:
                    self.place_order(self.kapi_main, self.main_pair, action, volume, buy_price=current_price if action == 'buy' else None)
                    if action == 'buy':
                        self.check_stop_loss(self.kapi_main, self.main_pair)
                if self.kapi_hedge:
                    ohlc_hedge = self.get_ohlc_data(self.kapi_hedge, self.hedge_pair)
                    rsi_hedge, ema_hedge = self.get_rsi_and_ema(ohlc_hedge)
                    if rsi_hedge is not None and ema_hedge is not None:
                        logger.info(f"RSI for {self.hedge_pair}: {rsi_hedge:.2f}, EMA: {ema_hedge:.2f}")
                        hedge_fiat_balance, hedge_asset_balance = self.get_account_balance(self.kapi_hedge, self.hedge_pair)
                        if hedge_fiat_balance < 500 and hedge_asset_balance < 0.2:
                            logger.warning(f"Low balance in hedge account: ${hedge_fiat_balance:.2f}, {hedge_asset_balance:.6f} ETH. Top up Kraken hedge account.")
                        hedge_price = self.get_current_price(self.kapi_hedge, self.hedge_pair)
                        if hedge_price:
                            hedge_action, hedge_volume = self.get_trade_action(rsi_hedge, ema_hedge, hedge_price, self.hedge_pair, hedge_fiat_balance, hedge_asset_balance)
                            if hedge_action and hedge_volume > 0:
                                self.place_order(self.kapi_hedge, self.hedge_pair, hedge_action, hedge_volume, buy_price=hedge_price if hedge_action == 'buy' else None)
                                if hedge_action == 'buy':
                                    self.check_stop_loss(self.kapi_hedge, self.hedge_pair)
            else:
                logger.info(f"No trade for {self.main_pair}: RSI {rsi_main:.2f}, EMA {ema_main:.2f}, Price fetch failed")
                self.missed_signals.append((self.main_pair, rsi_main, ema_main, None, time.time()))
        else:
            logger.info(f"No RSI/EMA calculated for {self.main_pair}")

    def run(self):
        """Main bot loop."""
        logger.info("Starting SlateBot...")
        while True:
            try:
                current_time = time.time()
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
