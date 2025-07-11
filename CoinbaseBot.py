import os
import ccxt
import logging
from flask import Flask

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def init_exchange():
    logger.debug("Initializing Coinbase exchange")
    exchange = ccxt.coinbase({
        'apiKey': os.getenv('COINBASE_API_KEY'),
        'secret': os.getenv('COINBASE_API_SECRET'),
    })
    exchange.urls['api'] = {
        'v2': 'https://api.coinbase.com/v2/',
        'public': 'https://api.coinbase.com/v2/',
    }
    logger.debug(f"Exchange URLs: {exchange.urls}")
    return exchange

def custom_sign(self, path, api='public', method='GET', params={}, headers=None, body=None):
    request = path
    base_url = self.urls['api'][api] if isinstance(self.urls['api'][api], str) else self.urls['api'][api][0]
    return {
        'url': base_url + request,
        'method': method,
        'body': body,
        'headers': headers
    }

@app.route('/health')
def health():
    return {"status": "healthy"}

@app.route('/test')
def test_exchange():
    try:
        exchange = init_exchange()
        exchange.load_markets()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
