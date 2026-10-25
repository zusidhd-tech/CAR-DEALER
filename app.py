"""Local web interface for the public CLCAuto search."""
import argparse
import json
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import search_autodev
import search_clcauto
import valuation
from search_cars import open_database, record_prices

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "car_history.sqlite3"


def year_in_range(car, min_year, max_year):
    try:
        year = int(car.get("year"))
    except (TypeError, ValueError):
        return min_year is None and max_year is None
    return ((min_year is None or year >= min_year) and
            (max_year is None or year <= max_year))


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
        min_year = int(data["min_year"]) if str(data.get("min_year", "")).strip() else None
        max_year = int(data["max_year"]) if str(data.get("max_year", "")).strip() else None
    except (ValueError, TypeError):
        raise ValueError("年份、价格、里程、距离和页数必须是整数。") from None
    zip_code = str(data.get("zip", "60601")).strip()
    if not (zip_code.isdigit() and len(zip_code) == 5):
        raise ValueError("ZIP code 必须是 5 位数字。")
    if not (1 <= max_price <= 10000000 and 1 <= max_miles <= 10000000 and
            1 <= pages <= 10 and 1 <= distance <= 500):
        raise ValueError("价格、里程和距离必须大于零，页数必须在 1 到 10 之间。")
    latest_year = date.today().year + 1
    if ((min_year is not None and not 1886 <= min_year <= latest_year) or
            (max_year is not None and not 1886 <= max_year <= latest_year)):
        raise ValueError(f"年份必须在 1886 到 {latest_year} 之间。")
    if min_year is not None and max_year is not None and min_year > max_year:
        raise ValueError("最低年份不能晚于最高年份。")
    args = SimpleNamespace(location=location, make=make, model=model, pages=pages,
                           zip=zip_code, distance=distance,
                           max_price=max_price, max_miles=max_miles,
                           min_year=min_year, max_year=max_year,
                           latest_year=latest_year)
    clc_market, clc_incomplete = search_clcauto.search(args)
    clc_market = [car for car in clc_market if year_in_range(car, min_year, max_year)]
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
    benchmarks, benchmark_info = valuation.load_data()
    if benchmark_info["warning"]:
        warnings.append(benchmark_info["warning"])
    for car in cars:
        valuation.assess(car, market, benchmarks)
        car["history_id"] = car["vin"]
    db = open_database(DATABASE)
    try:
        record_prices(db, cars)
    finally:
        db.close()
    return {"cars": sorted(cars, key=lambda c: c["price"]), "market_count": len(market),
            "incomplete": incomplete, "warnings": warnings,
            "sources": {"Auto.dev": len(auto_cars), "CLCAuto": len(clc_cars)},
            "auto_total": auto_total, "benchmark": benchmark_info}


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
        if self.path not in ("/api/search", "/api/forcar"):
            self.respond(404, {"error": "Not found"})
            return
        # Only this app's own page may initiate a search and write observations.
        origin = self.headers.get("Origin", "")
        if origin != f"http://127.0.0.1:{self.server.server_port}":
            self.respond(403, {"error": "请求来源无效。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.path == "/api/forcar":
                if not 0 < length <= valuation.MAX_BYTES or self.headers.get_content_type() != "text/csv":
                    raise ValueError("请选择不超过 5 MB 的 CSV 文件。")
                count = valuation.save_csv(self.rfile.read(length))
                self.respond(200, {"rows": count})
                return
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

