import sqlite3
import unittest
from unittest.mock import patch

import search_cars as app


def car(vin, price, year=2020, miles=50000, trim="LE"):
    return {"identity": vin, "vin": vin, "price": price, "year": year,
            "miles": miles, "trim": trim, "make": "Toyota", "model": "Corolla",
            "dealer": "Dealer", "city": "Chicago", "url": ""}


class CarSearchTests(unittest.TestCase):
    def test_history_first_observation_drop_and_increase(self):
        db = app.open_database(":memory:")
        first = car("VIN1", 20000)
        app.record_prices(db, [first])
        self.assertEqual(first["previous_price"], "")
        second = car("VIN1", 18000)
        app.record_prices(db, [second])
        self.assertEqual((second["previous_price"], second["price_drop"], second["price_drop_percent"]), (20000, 2000, 10))
        third = car("VIN1", 19000)
        app.record_prices(db, [third])
        self.assertEqual(third["previous_price"], 18000)
        self.assertEqual(third["price_drop"], "")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 3)
        db.close()

    def test_median_excludes_target_and_noncomparable_cars(self):
        target = car("TARGET", 15000)
        market = [target] + [car(str(i), p) for i, p in enumerate([17000, 18000, 19000, 20000, 21000])]
        market += [car("wrong-trim", 1000, trim="SE"), car("wrong-miles", 1000, miles=90000)]
        app.compare_market(target, market, False)
        self.assertEqual(target["comparable_count"], 5)
        self.assertEqual(target["market_median"], 19000)
        self.assertEqual(target["market_difference"], -4000)
        self.assertEqual(target["market_status"], "below_median")
        app.compare_market(target, market, True)
        self.assertEqual(target["market_status"], "sample_incomplete")

    def test_missing_data_and_small_sample_do_not_produce_estimate(self):
        target = car("TARGET", 15000, trim="")
        market = [car(str(i), 18000) for i in range(8)]
        app.compare_market(target, market, False)
        self.assertEqual(target["market_status"], "insufficient_comparables")
        self.assertEqual(target["market_median"], "")

    def test_pagination_marks_partial_sample(self):
        with patch.object(app, "fetch", return_value={"num_found": 100, "listings": []}):
            _, _, incomplete = app.search({}, 1)
        self.assertTrue(incomplete)


if __name__ == "__main__":
    unittest.main()
