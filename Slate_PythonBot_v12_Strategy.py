import krakenex
from pykrakenapi import KrakenAPI

api = krakenex.API()
api.key = "YOUR_API_KEY"
api.secret = "YOUR_API_SECRET"
k = KrakenAPI(api)

balances = k.get_account_balance()
print("Balances:", balances)
