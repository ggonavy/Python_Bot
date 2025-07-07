import cbpro
import pandas as pd
import time
import os
from datetime import datetime

# Load API credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')
api_passphrase = os.getenv('COINBASE_PASSPHRASE')

# Initialize REST client
client = cbpro.AuthenticatedClient(api_key, api_secret, api_passphrase)

# Trading parameters
PAIR = 'BTC-USD'
RSI_PERIOD = 14
BUY_RSI = [47, 42, 37, 32]
SELL_RSI = [73, 77, 81, 85]
SLEEP_INTERVAL = 60  # seconds
TRADE_AMOUNT = 0.01675  # ~1/10th of 0.1675 BTC
PRICE_TOLERANCE = 0.005  # 0.5% price slippage for limit orders

# Logging
def log(message):
    print(f"{datetime.now()}: {message}")

# Get historical data for RSI
def get_rsi(pair, period=RSI_PERIOD):
    candles = client.get_product_historic_rates(pair, granularity=300)  # 5-min candles
    df = pd.DataFrame(candles, columns=['time', 'low', 'high', 'open', 'close', 'volume'])
    df['close'] = df['close'].astype(float)
    df = df.sort_values('time', ascending=True)
    deltas = df['close'].diff()
    gains = deltas.where(deltas > 0, 0)
    losses = -deltas.where(deltas < 0, 0)
    avg_gain = gains.rolling(window=period).mean().iloc[-1]
    avg_loss = losses.rolling(window=period).mean().iloc[-1]
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
    rsi = 100 - (100 / (1 + rs))
    return rsi, df['close'].iloc[-1]

# WebSocket for real-time price
class PriceFeed(cbpro.WebsocketClient):
    def __init__(self):
        super().__init__(products=[PAIR], channels=['ticker'])
        self.latest_price = None

    def on_message(self, msg):
        if msg['type'] == 'ticker' and msg['product_id'] == PAIR:
            self.latest_price = float(msg['price'])
            log(f"WebSocket Price: ${self.latest_price:.2f}")

    def get_price(self):
        return self.latest_price

# Main trading loop
def main():
    price_feed = PriceFeed()
    price_feed.start()

    while True:
        try:
            # Get RSI and price
            rsi, _ = get_rsi(PAIR)
            price = price_feed.get_price()
            if not price:
                log("Waiting for WebSocket price...")
                time.sleep(5)
                continue
            log(f"Price: ${price:.2f} | RSI: {rsi:.2f}")

            # Get balances
            accounts = client.get_accounts()
            btc_balance = float(next(acc for acc in accounts if acc['currency'] == 'BTC')['available'])
            usd_balance = float(next(acc for acc in accounts if acc['currency'] == 'USD')['available'])
            log(f"BTC: {btc_balance:.6f} | USD: ${usd_balance:.2f}")

            # Buy logic (limit order)
            for rsi_level in BUY_RSI:
                if rsi <= rsi_level and usd_balance >= price * TRADE_AMOUNT:
                    buy_price = price * (1 - PRICE_TOLERANCE)
                    order = client.place_limit_order(
                        product_id=PAIR,
                        side='buy',
                        size=TRADE_AMOUNT,
                        price=buy_price,
                        time_in_force='GTC'
                    )
                    log(f"Buy {TRADE_AMOUNT} BTC at ${buy_price:.2f} (RSI: {rsi:.2f}) | Order: {order['id']}")
                    break

            # Sell logic (limit order)
            for rsi_level in SELL_RSI:
                if rsi >= rsi_level and btc_balance >= TRADE_AMOUNT:
                    sell_price = price * (1 + PRICE_TOLERANCE)
                    order = client.place_limit_order(
                        product_id=PAIR,
                        side='sell',
                        size=TRADE_AMOUNT,
                        price=sell_price,
                        time_in_force='GTC'
                    )
                    log(f"Sell {TRADE_AMOUNT} BTC at ${sell_price:.2f} (RSI: {rsi:.2f}) | Order: {order['id']}")
                    break

        except Exception as e:
            log(f"Error: {str(e)}")
            time.sleep(5)  # Retry after delay

        time.sleep(SLEEP_INTERVAL)

# Run bot
if __name__ == '__main__':
    main()
