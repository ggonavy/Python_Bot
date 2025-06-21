from flask import Flask, request, jsonify
import ccxt
import pandas as pd

app = Flask(__name__)

# === Kraken API Setup ===
kraken = ccxt.kraken({
    'apiKey': 'YOUR_KRAKEN_API_KEY',
    'secret': 'YOUR_KRAKEN_API_SECRET',
})
symbol = 'BTC/USD'
timeframe = '2h'  # Use 2-hour timeframe

# === RSI Parameters ===
buy_rsi = 43
sell_rsi = 73
rsi_period = 14

def get_rsi(df, period):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def fetch_latest_data():
    ohlcv = kraken.fetch_ohlcv(symbol, timeframe)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['rsi'] = get_rsi(df, rsi_period)
    return df

@app.route('/signal', methods=['POST'])
def signal_handler():
    df = fetch_latest_data()
    current_rsi = df['rsi'].iloc[-1]

    if current_rsi < buy_rsi:
        action = 'buy'
        print(f'RSI {current_rsi:.2f} < {buy_rsi} → BUY SIGNAL')
    elif current_rsi > sell_rsi:
        action = 'sell'
        print(f'RSI {current_rsi:.2f} > {sell_rsi} → SELL SIGNAL')
    else:
        action = 'hold'
        print(f'RSI {current_rsi:.2f} → HOLD')

    return jsonify({
        'status': 'ok',
        'rsi': current_rsi,
        'action': action
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
