import time
import requests
import pandas as pd
import ta
import krakenex
from datetime import datetime
from pytz import timezone

# === CONFIG ===
API_KEY = 'haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM'
API_SECRET = 'MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=='
PAIR = 'XBTUSD'  # Kraken uses XBT instead of BTC
ASSET = 'XXBT'  # Kraken asset code for BTC
CURRENCY = 'ZUSD'  # Kraken code for USD
INTERVAL = 60  # 1 hour candles
RSI_PERIOD = 14

BUY_TIERS = [(47, 0.10), (42, 0.20), (37, 0.30), (32, 0.40)]  # RSI level, % of fiat
SELL_TIERS = [(73, 0.40), (77, 0.30), (81, 0.20), (85, 0.10)]  # RSI level, % of BTC

NO_BUY_THRESHOLD = 27  # Below this, no auto-buy (manual DCA only)
REBUY_LIMIT = 47  # Must be ≤ this to restart buy ladder after full sell

bot_state = {
    "buy_index": 0,
    "sell_index": 0,
    "active_trade": False
}

k = krakenex.API()
k.key = API_KEY
k.secret = API_SECRET

def log(msg):
    now = datetime.now(timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def fetch_ohlcv():
    url = 'https://api.kraken.com/0/public/OHLC'
    params = {'pair': PAIR, 'interval': INTERVAL}
    r = requests.get(url, params=params)
    df = pd.DataFrame(r.json()['result'][PAIR], columns=[
        'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
    df['close'] = df['close'].astype(float)
    return df

def get_rsi(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], RSI_PERIOD).rsi()
    return df['rsi'].iloc[-1]

def get_balance(asset):
    bal = k.query_private('Balance')['result']
    return float(bal.get(asset, 0.0))

def get_price():
    res = k.query_public('Ticker', {'pair': PAIR})
    return float(res['result'][list(res['result'].keys())[0]]['c'][0])

def place_order(type_, volume):
    order = {
        'pair': PAIR,
        'type': type_,
        'ordertype': 'market',
        'volume': str(volume)
    }
    response = k.query_private('AddOrder', order)
    log(f"{type_.upper()} ORDER: {response}")
    return response

def trade_logic():
    df = fetch_ohlcv()
    rsi = get_rsi(df)
    price = get_price()
    fiat_balance = get_balance(CURRENCY)
    btc_balance = get_balance(ASSET)

    log(f"RSI: {rsi:.2f} | BTC: {btc_balance:.6f} | USD: ${fiat_balance:.2f}")

    # SELL LOGIC
    if btc_balance > 0 and bot_state['sell_index'] < len(SELL_TIERS):
        level, percent = SELL_TIERS[bot_state['sell_index']]
        if rsi >= level:
            sell_amt = btc_balance * percent
            if sell_amt > 0.0001:
                place_order('sell', sell_amt)
                bot_state['sell_index'] += 1
                if bot_state['sell_index'] == len(SELL_TIERS):
                    log("Fully sold out. Awaiting RSI ≤ 47 to reactivate buy.")
                    bot_state['active_trade'] = False
            return

    # BLOCK BUYING IF INACTIVE AND RSI > 47
    if not bot_state['active_trade'] and rsi > REBUY_LIMIT:
        log("Bot inactive. RSI > 47. Waiting...")
        return
    if not bot_state['active_trade']:
        bot_state['buy_index'] = 0
        bot_state['sell_index'] = 0
        bot_state['active_trade'] = True

    # BUY LOGIC
    if fiat_balance > 5 and bot_state['buy_index'] < len(BUY_TIERS):
        level, percent = BUY_TIERS[bot_state['buy_index']]
        if rsi <= level and rsi >= NO_BUY_THRESHOLD:
            usd_to_spend = fiat_balance * percent
            btc_to_buy = usd_to_spend / price
            if btc_to_buy > 0.0001:
                place_order('buy', btc_to_buy)
                bot_state['buy_index'] += 1
            return

    if rsi < NO_BUY_THRESHOLD:
        log("RSI too low. Manual DCA zone.")

def run_bot():
    while True:
        try:
            trade_logic()
        except Exception as e:
            log(f"Error: {e}")
        time.sleep(60)  # check every 1 min

if __name__ == '__main__':
    log("SlateBot v12 (Kraken Direct) Starting...")
    run_bot()
