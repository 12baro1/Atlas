import unittest

from orderbook_engine import OrderBookEngine


class OrderBookEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = OrderBookEngine()

    def test_long_support_from_near_bid_imbalance(self):
        book = {"bids": [[100, 100], [99.95, 80]], "asks": [[100.05, 10], [100.10, 10]]}
        state = self.engine.analyze(book, "LONG")
        self.assertTrue(state["active"])
        self.assertTrue(state["supportive"])
        self.assertTrue(state["market_entry_allowed"])
        self.assertEqual(state["limit_entry_candidate"], 100)

    def test_far_depth_does_not_dominate_near_book(self):
        book = {
            "bids": [[100, 10], [99.99, 10], [90, 100000]],
            "asks": [[100.01, 10], [100.02, 10], [110, 100000]],
        }
        state = self.engine.analyze(book, "LONG")
        self.assertAlmostEqual(state["imbalance"], 0.0, places=2)

    def test_strong_opposing_book_blocks_entry(self):
        book = {"bids": [[100, 10]], "asks": [[100.01, 100], [100.02, 100]]}
        state = self.engine.analyze(book, "LONG")
        self.assertTrue(state["opposing"])
        self.assertFalse(state["market_entry_allowed"])

    def test_missing_book_is_neutral(self):
        state = self.engine.analyze(None, "LONG")
        self.assertFalse(state["active"])
        self.assertTrue(state["market_entry_allowed"])

    def test_crossed_book_is_ignored(self):
        state = self.engine.analyze({"bids": [[101, 10]], "asks": [[100, 10]]}, "LONG")
        self.assertFalse(state["active"])

    def test_stale_book_is_ignored(self):
        state = self.engine.analyze(
            {"timestamp": 1000, "bids": [[100, 10]], "asks": [[100.01, 10]]},
            "LONG",
            now_ms=20000,
        )
        self.assertFalse(state["active"])

    def test_invalid_numeric_levels_are_ignored(self):
        state = self.engine.analyze(
            {"bids": [[100, float("nan")], [100, 10]], "asks": [[100.01, 10]]},
            "LONG",
        )
        self.assertTrue(state["active"])
        self.assertGreater(state["bid_notional"], 0)


if __name__ == "__main__":
    unittest.main()
