from market.prediction_journal import PredictionJournal


def sample_setup():
    return {
        "session_date": "2026-09-21", "created_at": "2026-09-18T17:30:00-07:00",
        "bias": "Bullish", "probability": 65, "risk_score": 65,
        "signals": {"market": {"change_percent": 0.4}}, "reasons": ["ES rising"],
        "catalysts": ["Fed speech"], "confirmation": ["VIX lower"],
        "invalidation": ["ES below -0.5%"],
    }


def test_save_review_and_statistics(tmp_path):
    journal = PredictionJournal(tmp_path / "journal.db")
    saved = journal.save_setup(sample_setup())
    assert saved["bias"] == "Bullish"
    reviewed = journal.review(saved["session_date"], {}, 0.75)
    assert reviewed["actual_outcome"] == "Bullish"
    assert reviewed["direction_correct"] is True
    assert journal.statistics()["accuracy"] == 100.0


def test_review_uses_mixed_band(tmp_path):
    journal = PredictionJournal(tmp_path / "journal.db")
    setup = sample_setup()
    setup["bias"] = "Mixed"
    journal.save_setup(setup)
    reviewed = journal.review(setup["session_date"], {}, 0.1, invalidated=True)
    assert reviewed["actual_outcome"] == "Mixed"
    assert reviewed["invalidated"] is True
