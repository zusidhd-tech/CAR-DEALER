import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import app


class LocalUITests(unittest.TestCase):
    def test_search_http_history_and_origin(self):
        listing = {"identity": "CLC:123", "vin": "CLC:123", "listing_id": "123", "year": 2020,
                   "make": "Toyota", "model": "Corolla", "trim": "LE", "price": 15000,
                   "miles": 50000, "dealer": "Dealer", "city": "Chicago", "url": "https://www.clcauto.com/en/car/123"}
        with tempfile.TemporaryDirectory() as temp, patch.object(app, "DATABASE", Path(temp) / "history.sqlite3"), \
             patch.object(app.search_clcauto, "search", return_value=([listing], False)):
            server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/") as response:
                    self.assertIn("CAR SCOUT", response.read().decode("utf-8"))
                body = json.dumps({"location": "Chicago", "pages": 1}).encode()
                request = Request(base + "/api/search", data=body, headers={"Content-Type": "application/json", "Origin": base})
                with urlopen(request) as response:
                    result = json.load(response)
                self.assertEqual(result["cars"][0]["price"], 15000)
                with urlopen(base + "/api/history?id=123") as response:
                    self.assertEqual(json.load(response)["history"][0]["price"], 15000)
                request = Request(base + "/api/search", data=body, headers={"Content-Type": "application/json", "Origin": "https://example.com"})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_rejects_invalid_search(self):
        with self.assertRaises(ValueError):
            app.search_listings({"location": "Chicago", "pages": 11})


if __name__ == "__main__":
    unittest.main()
