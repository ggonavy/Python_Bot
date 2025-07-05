import krakenex
try:
    from pykrakenapi import KrakenAPI
except ImportError:
    logger.error("pykrakenapi import failed. Ensure it's installed correctly.")
    exit(1)
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
import time
import os
import logging

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
        self.interval = 15
        self.rsi_periods = 14
        self.candles_to_fetch = 20
        self.last_candle_time = 0
        self.buy_ladder = [47, 42, 37, 32]
        self.sell_ladder = [73, 77, 81, 85]
        self.base_trade_size = 0.001
        self.ladder_multipliers = [1, 1.5, 2, 3]

    def get_ohlc_data(self, kapi, pair):
        """Fetch OHLC data for the specified pair."""
        try:
            ohlc, _ = kapi.get_ohlc_data(pair, interval=self.interval, ascending=True)
            logger.info(f"Retrieved {len(ohlc)} candlesticks for {pair}")
            if len(ohlc) < self.candles_to_fetch:
                logger.warning(f"Only {len(ohlc)} candlesticks for {pair}, needed {self.candles_to_fetch}")
            return ohlc.tail(self.candles_to_fetch)
        except Exception as e:
            logger.error(f"Error fetching OHLC for {pair}: {e}")
            return None

    def get_rsi(self, ohlc_data):
        """Calculate RSI from OHLC data."""
        if ohlc_data is None or len(ohlc_data) < self.rsi_periods:
            logger.error(f"Not enough data: {len(ohlc_data)} candlesticks available")
            return None
        close = ohlc_data['close']
        rsi = RSIIndicator(close, window=self.rsi_periods).rsi()
        return rsi.iloc[-1]

    def place_order(self, kapi, pair, side, volume):
        """Place a market order on Kraken."""
        try:
            order = kapi.add_standard_order(
                pair=pair,
                type=side,
                ordertype='market',
                volume=volume
            )
            logger.info(f"Placed {side} order for {volume} {pair}: {order}")
            return order
        except Exception as e:
            logger.error(f"Error placing {side} order for {pair}: {e}")
            return None

    def get_trade_action(self, rsi, pair):
        """Determine trade action based on RSI ladders."""
        if pair == self.main_pair:
            for i, rsi_level in enumerate(self.buy_ladder):
                if rsi <= rsi_level:
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'buy', volume
            for i, rsi_level in enumerate(self.sell_ladder):
                if rsi >= rsi_level:
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'sell', volume
        elif pair == self.hedge_pair:
            for i, rsi_level in enumerate(self.buy_ladder):
                if rsi <= rsi_level:
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'sell', volume
            for i, rsi_level in enumerate(self.sell_ladder):
                if rsi >= rsi_level:
                    volume = self.base_trade_size * self.ladder_multipliers[i]
                    return 'buy', volume
        return None, 0

    def execute_trades(self):
        """Execute trades for main and hedge accounts based on RSI."""
        ohlc_main = self.get_ohlc_data(self.kapi_main, self.main_pair)
        rsi_main = self.get_rsi(ohlc_main)
        if rsi_main:
            logger.info(f"RSI for {self.main_pair}: {rsi_main:.2f}")
            action, volume = self.get_trade_action(rsi_main, self.main_pair)
            if action and volume > 0:
                self.place_order(self.kapi_main, self.main_pair, action, volume)
                if self.kapi_hedge:
                    ohlc_hedge = self.get_ohlc_data(self.kapi_hedge, self.hedge_pair)
                    rsi_hedge = self.get_rsi(ohlc_hedge)
                    if rsi_hedge:
                        logger.info(f"RSI for {self.hedge_pair}: {rsi_hedge:.2f}")
                        hedge_action, hedge_volume = self.get_trade_action(rsi_hedge, self.hedge_pair)
                        if hedge_action and hedge_volume > 0:
                            self.place_order(self.kapi_hedge, self.hedge_pair, hedge_action, hedge_volume)
            else:
                logger.info(f"No trade for {self.main_pair}: RSI {rsi_main:.2f}")

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

if __name__ == "__main__":
    main_key = os.getenv("KRAKEN_API_KEY")
    main_secret = os.getenv("KRAKEN_API_SECRET")
    hedge_key = os.getenv("KRAKEN_API_KEY_HEDGE")
    hedge_secret = os.getenv("KRAKEN_API_SECRET_HEDGE")
    
    if not main_key or not main_secret:
        logger.error("Missing main Kraken API credentials")
        exit(1)
    
    bot = SlateBot(main_key, main_secret, hedge_key, hedge_secret)
    bot.run()
