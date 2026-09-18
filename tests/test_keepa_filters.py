from market.amazon_leads_engine import AmazonLeadsEngine


def test_default_sourcing_profile(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("AMAZON_LEADS_"):
            monkeypatch.delenv(key, raising=False)
    engine = AmazonLeadsEngine()
    selection = engine._selection("30")
    assert engine.min_roi == 40
    assert selection["current_SALES_lte"] == 150000
    assert selection["salesRankDrops30_gte"] == 10
    assert selection["current_COUNT_NEW_gte"] == 3


def test_max_buy_uses_target_roi(monkeypatch):
    monkeypatch.setenv("AMAZON_LEADS_MIN_ROI", "40")
    engine = AmazonLeadsEngine()
    lead = type("Lead", (), {"exit_price": 50.0})()
    assert engine.max_buy_price(lead) == 27.14
