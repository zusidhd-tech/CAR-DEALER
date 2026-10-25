"""Local web interface for the public CLCAuto search."""
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import search_autodev
import search_clcauto
from search_cars import compare_market, open_database, record_prices

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "car_history.sqlite3"


def search_listings(data):
    location = str(data.get("location", "Chicago")).strip()
    make = str(data.get("make", "")).strip()
    model = str(data.get("model", "")).strip()
    if not location or any(len(value) > 80 for value in (location, make, model)):
        raise ValueError("请填写不超过 80 个字符的城市、品牌和车型。")
    try:
        max_price = int(data.get("max_price", 18000))
        max_miles = int(data.get("max_miles", 90000))
        pages = int(data.get("pages", 5))
        distance = int(data.get("distance", 50))
    except (ValueError, TypeError):
        raise ValueError("价格、里程、距离和页数必须是整数。") from None
    zip_code = str(data.get("zip", "60601")).strip()
    if not (zip_code.isdigit() and len(zip_code) == 5):
        raise ValueError("ZIP code 必须是 5 位数字。")
    if not (1 <= max_price <= 10000000 and 1 <= max_miles <= 10000000 and
            1 <= pages <= 10 and 1 <= distance <= 500):
        raise ValueError("价格、里程和距离必须大于零，页数必须在 1 到 10 之间。")
    args = SimpleNamespace(location=location, make=make, model=model, pages=pages,
                           zip=zip_code, distance=distance,
                           max_price=max_price, max_miles=max_miles)
    clc_market, clc_incomplete = search_clcauto.search(args)
    clc_cars = [car for car in clc_market if car["price"] <= max_price and
            isinstance(car["miles"], (int, float)) and not isinstance(car["miles"], bool)
            and 0 <= car["miles"] <= max_miles]
    for car in clc_cars:
        car["source"] = "CLCAuto"
        car["image_url"] = ""
    warnings = []
    try:
        auto_cars, auto_total, auto_incomplete = search_autodev.search(args)
    except RuntimeError as exc:
        auto_cars, auto_total, auto_incomplete = [], None, False
        warnings.append(str(exc))
    cars = list(auto_cars)
    seen_vins = {car["vin"] for car in auto_cars if len(car.get("vin", "")) == 17}
    cars.extend(car for car in clc_cars if car.get("vin") not in seen_vins)
    market = list(auto_cars) + list(clc_market)
    incomplete = clc_incomplete or auto_incomplete
    for car in cars:
        compare_market(car, market, incomplete)
        car["history_id"] = car["vin"]
    db = open_database(DATABASE)
    try:
        record_prices(db, cars)
    finally:
        db.close()
    return {"cars": sorted(cars, key=lambda c: c["price"]), "market_count": len(market),
            "incomplete": incomplete, "warnings": warnings,
            "sources": {"Auto.dev": len(auto_cars), "CLCAuto": len(clc_cars)},
            "auto_total": auto_total}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond(200, (ROOT / "ui.html").read_bytes(), "text/html; charset=utf-8")
        elif parsed.path == "/api/history":
            history_id = parse_qs(parsed.query).get("id", [""])[0].strip().upper()
            if len(history_id) > 100 or not history_id:
                self.respond(400, {"error": "无效的车源 ID。"})
                return
            try:
                db = open_database(DATABASE)
                try:
                    rows = db.execute("SELECT observed_at, price FROM observations WHERE vin = ? ORDER BY id DESC LIMIT 100", (history_id,)).fetchall()
                finally:
                    db.close()
                self.respond(200, {"history": [{"date": date, "price": price} for date, price in rows]})
            except sqlite3.Error:
                self.respond(500, {"error": "无法读取价格历史。"})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/api/search":
            self.respond(404, {"error": "Not found"})
            return
        # Only this app's own page may initiate a search and write observations.
        origin = self.headers.get("Origin", "")
        if origin != f"http://127.0.0.1:{self.server.server_port}":
            self.respond(403, {"error": "请求来源无效。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError("请求格式无效。")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效。")
            self.respond(200, search_listings(data))
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except (RuntimeError, OSError, sqlite3.Error):
            self.respond(502, {"error": "无法获取车源或保存记录，请检查网络并稍后重试。"})


def main():
    parser = argparse.ArgumentParser(description="Run the local car search UI")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Open http://127.0.0.1:{server.server_port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

