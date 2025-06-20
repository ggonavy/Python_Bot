from flask import Flask, request, jsonify
import requests
import pandas as pd
import os

# === CONFIG ===
THREECOMMAS_WEBHOOK_URL = "https://api.3commas.io/signal_bots/webhooks/YOUR_WEBHOOK_ID_HERE"
PAIR = "BTC_USD"
POSITION = "long"
RSI_BUY_THRESHOLD = 30

app = Flask(__name__)

def fetch_btc_data(days=100):
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days={days}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        prices = response.json()["prices"]
        df = pd.DataFrame(prices, columns=["timestamp", "price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print("❌ Error fetching data from CoinGecko:", e)
        return None

def compute_rsi(df, period=14):
    delta = df["price"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    df["rsi"] = rsi
    return df

def send_buy_signal():
    payload = {
        "pair": PAIR,
        "position": POSITION
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(THREECOMMAS_WEBHOOK_URL, headers=headers, json=payload)
    print("✅ 3Commas Signal Sent | Status:", response.status_code)
    print("📦 Response:", response.text)

def check_and_trade():
    df = fetch_btc_data()
    if df is not None:
        df = compute_rsi(df)
        latest_rsi = df["rsi"].iloc[-1]
        print("📊 Latest RSI:", latest_rsi)
        if latest_rsi < RSI_BUY_THRESHOLD:
            print("🚀 RSI below threshold — firing BUY signal.")
            send_buy_signal()
        else:
            print("🧘 RSI not low enough. No signal.")

@app.route('/signal', methods=['POST'])
def receive_signal():
    data = request.json
    action = data.get("action")
    print(f"📩 Signal received: {data}")
    if action == "buy":
        send_buy_signal()
    return jsonify({"status": "received", "action": action})

if __name__ == '__main__':
    check_and_trade()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
