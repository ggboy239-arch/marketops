import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import requests


AMAZON = 0
NEW = 1
SALES = 3
COUNT_NEW = 11
BUY_BOX_SHIPPING = 18


@dataclass
class StorefrontProduct:
    asin: str
    title: str
    brand: str
    image_url: str | None
    price: float | None
    rank: int | None
    sellers: int | None
    amazon_in_stock: bool | None

    @property
    def amazon_url(self):
        return f"https://www.amazon.com/dp/{self.asin}"

    @property
    def keepa_url(self):
        return f"https://keepa.com/#!product/1-{self.asin}"


class StorefrontEngine:
    """Read public Amazon storefront inventory through Keepa without judging ROI."""

    API = "https://api.keepa.com"
    # Amazon merchant IDs are longer than 10-character ASINs.
    SELLER_ID = re.compile(r"^[A-Z0-9]{12,20}$", re.I)

    def __init__(self):
        self.key = os.getenv("KEEPA_API_KEY", "").strip()
        self.timeout = int(os.getenv("KEEPA_TIMEOUT_SECONDS", "25"))
        self.batch_size = max(1, min(20, int(os.getenv("STOREFRONT_PRODUCTS_PER_SCAN", "20"))))

    def resolve_seller_id(self, value):
        raw = unquote(str(value or "").strip().strip("<>"))
        if self.SELLER_ID.fullmatch(raw):
            return raw.upper()
        if not raw.startswith(("http://", "https://")):
            raise ValueError("Enter an Amazon storefront URL or seller ID.")
        parsed = urlparse(raw)
        if "amazon." not in parsed.netloc.lower():
            raise ValueError("That is not an Amazon storefront URL.")
        query = parse_qs(parsed.query)
        for key in ("seller", "me", "merchant", "merchantId", "sellerId"):
            candidate = (query.get(key) or [""])[0].strip()
            if self.SELLER_ID.fullmatch(candidate):
                return candidate.upper()
        response = requests.get(
            raw,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarketOps/1.0)"},
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        patterns = (
            r'[?&](?:seller|me)=([A-Z0-9]{12,20})',
            r'"(?:merchantId|sellerId)"\s*:\s*"([A-Z0-9]{12,20})"',
            r'(?:merchantId|sellerId)=([A-Z0-9]{12,20})',
        )
        text = response.url + "\n" + response.text
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1).upper()
        raise ValueError(
            "I could not find the seller ID in that storefront link. Open the seller profile and copy a link containing `seller=` or `me=`, or paste the seller ID."
        )

    def storefront(self, seller_id):
        if not self.key:
            raise RuntimeError("KEEPA_API_KEY is missing")
        payload = self._get("/seller", seller=seller_id, storefront=1)
        sellers = payload.get("sellers") or {}
        seller = sellers.get(seller_id) or sellers.get(seller_id.upper())
        if seller is None and len(sellers) == 1:
            seller = next(iter(sellers.values()))
        if not isinstance(seller, dict):
            raise RuntimeError("Keepa did not return that Amazon seller. Check the seller ID and marketplace.")
        asins = []
        for asin in seller.get("asinList") or []:
            asin = str(asin).upper()
            if re.fullmatch(r"[A-Z0-9]{10}", asin) and asin not in asins:
                asins.append(asin)
        name = str(seller.get("sellerName") or seller.get("businessName") or seller_id)
        return name[:150], asins

    def products(self, asins):
        chosen = list(asins)[: self.batch_size]
        if not chosen:
            return []
        payload = self._get("/product", asin=",".join(chosen), stats=90, history=0, buybox=0)
        return [self._product(item) for item in payload.get("products") or [] if item.get("asin")]

    def _product(self, item):
        stats = item.get("stats") or {}
        current = stats.get("current") or []
        amazon_raw = self._at(current, AMAZON)
        amazon_in_stock = amazon_raw > 0 if isinstance(amazon_raw, (int, float)) else None
        price = self._price(self._at(current, BUY_BOX_SHIPPING)) or self._price(self._at(current, NEW))
        images = str(item.get("imagesCSV") or "").split(",")
        image = f"https://m.media-amazon.com/images/I/{images[0]}" if images and images[0] else None
        return StorefrontProduct(
            asin=str(item.get("asin")), title=str(item.get("title") or "Untitled Amazon product")[:250],
            brand=str(item.get("brand") or "Brand not listed")[:100], image_url=image, price=price,
            rank=self._positive(self._at(current, SALES)), sellers=self._positive(self._at(current, COUNT_NEW)),
            amazon_in_stock=amazon_in_stock,
        )

    def _get(self, path, **params):
        params.update({"key": self.key, "domain": 1})
        response = requests.get(self.API + path, params=params, timeout=self.timeout)
        if not response.ok:
            detail = response.text.strip()[:500]
            if response.status_code == 429:
                try:
                    info = response.json()
                    left = int(info.get("tokensLeft", 0)); rate = max(1, int(info.get("refillRate", 1)))
                    refill_ms = int(info.get("refillIn", 0))
                    minutes = max(1, round(max(0, -left) / rate + refill_ms / 60000 + 0.5))
                    raise RuntimeError(f"Keepa tokens are refilling. Retry in about {minutes} minute(s).")
                except RuntimeError:
                    raise
                except Exception:
                    pass
            raise RuntimeError(f"Keepa HTTP {response.status_code}: {detail or 'request rejected'}")
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"Keepa: {data['error']}")
        return data

    @staticmethod
    def _at(values, index):
        return values[index] if isinstance(values, list) and len(values) > index else None

    @staticmethod
    def _price(value):
        return round(value / 100, 2) if isinstance(value, (int, float)) and value > 0 else None

    @staticmethod
    def _positive(value):
        return int(value) if isinstance(value, (int, float)) and value >= 0 else None
