
import yfinance as yf
import pandas as pd
import numpy as np
import datetime

# Strategy parameters
buy_rsi_levels = [47, 42, 37, 32]
buy_allocations = [0.10, 0.20, 0.30, 0.40]
sell_rsi_levels = [73, 77, 81, 85]
sell_allocations = [0.40, 0.30, 0.20, 0.10]

# RSI calculation
def compute_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# Downsample data
def resample_data(df, freq):
    return df['Close'].resample(freq).last().dropna()

# Strategy simulation
def simulate_bot_strategy(price_series):
    usd = 100000
    btc = 0
    in_trade = False
    buy_flags = [False]*4
    sell_flags = [False]*4
    rsi = compute_rsi(price_series)

    for i in range(len(price_series)):
        price = price_series.iloc[i]
        if np.isnan(rsi.iloc[i]):
            continue
        rsi_val = rsi.iloc[i]

        # Buy logic
        if not in_trade:
            for j, level in enumerate(buy_rsi_levels):
                if not buy_flags[j] and rsi_val <= level:
                    allocation = buy_allocations[j]
                    buy_amt = (usd * allocation) / price
                    btc += buy_amt
                    usd -= buy_amt * price
                    buy_flags[j] = True
                    in_trade = True
                    break

        # Sell logic
        elif in_trade and btc > 0:
            for k, level in enumerate(sell_rsi_levels):
                if not sell_flags[k] and rsi_val >= level:
                    allocation = sell_allocations[k]
                    sell_amt = btc * allocation
                    btc -= sell_amt
                    usd += sell_amt * price
                    sell_flags[k] = True
                    break

        # Reset logic
        if btc < 0.00001:
            in_trade = False
            buy_flags = [False]*4
            sell_flags = [False]*4

    final_value = usd + btc * price_series.iloc[-1]
    return final_value

# Main
def run_simulation():
    start_date = "2020-01-01"
    end_date = datetime.datetime.now().strftime("%Y-%m-%d")
    btc_data = yf.download("BTC-USD", start=start_date, end=end_date, interval='15m')

    btc_data.index = pd.to_datetime(btc_data.index)
    btc_2h = resample_data(btc_data, '2H')
    btc_1h = resample_data(btc_data, '1H')
    btc_30m = resample_data(btc_data, '30T')

    result_2h = simulate_bot_strategy(btc_2h)
    result_1h = simulate_bot_strategy(btc_1h)
    result_30m = simulate_bot_strategy(btc_30m)

    print("Slate v12 Strategy Backtest Results:")
    print(f"2H Final Value: ${result_2h:,.2f}")
    print(f"1H Final Value: ${result_1h:,.2f}")
    print(f"30min Final Value: ${result_30m:,.2f}")

if __name__ == '__main__':
    run_simulation()
