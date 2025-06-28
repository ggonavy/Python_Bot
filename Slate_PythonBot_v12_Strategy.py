import krakenex
from pykrakenapi import KrakenAPI

api = krakenex.API()
api.key = "haDXxKlf3s04IL8OZsBy5j+kn7ZTS8LjnkwZvHjpmL+0sYZj8IfwxniM"
api.secret = "MvohzPBpHaG0S3vxrMtldcnGFoa+9cXLvJ8IxrwwOduSDaLgxPxG2YK/9cRQCEOnYoSmR22ZzUJr4CPIXDh19Q=="
k = KrakenAPI(api)

balances = k.get_account_balance()
print("Balances:", balances)
