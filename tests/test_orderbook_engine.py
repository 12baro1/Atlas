import unittest

from orderbook_engine import OrderBookEngine


class OrderBookEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = OrderBookEngine()

    def test_long_support_from_bid_imbalance(self):
        book = {"bids": [[100, 100], [99.9, 80]], "asks": [[100.1, 10], [100.2, 10]]}
        state = self.engine.analyze(book, "LONG")
        self.assertTrue(state["active"])
        self.assertTrue(state["supportive"])
        self.assertTrue(state["market_entry_allowed"])

    def test_strong_opposing_book_blocks_entry(self):
        book = {"bids": [[100, 10]], "asks": [[100.1, 100], [100.2, 100]]}
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


if __name__ == "__main__":
    unittest.main()
