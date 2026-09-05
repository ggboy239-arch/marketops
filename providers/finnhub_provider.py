import os
import requests
from dotenv import load_dotenv

load_dotenv()


class FinnhubProvider:

    def __init__(self):

        self.api_key = os.getenv("FINNHUB_API_KEY")

        self.base_url = "https://finnhub.io/api/v1"

    def get_quote(self, symbol):

        url = (
            f"{self.base_url}/quote"
            f"?symbol={symbol}"
            f"&token={self.api_key}"
        )

        response = requests.get(url)

        return response.json()