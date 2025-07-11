import os
import time
import ccxt
import pandas as pd
import logging
from flask import Flask, jsonify
from ta.momentum import RSIIndicator
from threading import Thread
import hmac
import hashlib
import base64

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler('coinbase_bot.log'),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)

# Flask app for Render health checks
app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

# Coinbase API setup
def init_exchange():
    try:
        api_key = os.getenv('COINBASE_API_KEY')
        api_secret = os.getenv('COINBASE_API_SECRET')
        passphrase = os.getenv('COINBASE_PASSPHRASE')
        if not all([api_key, api_secret, passphrase]):
            logger.error("Missing API credentials")
            raise ValueError("API credentials not set")
        exchange = ccxt.coinbase({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'rateLimit': 100
        })
        # Override sign method for Coinbase API authentication
        def custom_sign(self, path, api='public', method='GET', params={}, headers=None, body=None):
            request = '/' + path
            timestamp = str(int(time.time()))
            message = timestamp + method + request + (body or '')
            signature = hmac.new(
                self.encode(self.secret),
                self.encode(message),
                hashlib.sha256
            ).digest()
            signature
