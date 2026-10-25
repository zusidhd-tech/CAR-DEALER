"""Search dealer listings, track observed prices, and compare local asking prices."""
import argparse
import csv
import json
import os
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.marketcheck.com/v2/search/car/active"
COLUMNS = ("vin", "year", "make", "model", "trim", "price", "miles", "dealer", "city", "url",
           "previous_price", "price_drop", "price_drop_percent", "market_median", "comparable_count",
           "market_difference", "market_difference_percent", "market_status")


def parse_args():
    parser = argparse.ArgumentParser(description="Find used dealer cars and track their prices.")
    parser.add_argument("--zip", default="60601", help="ZIP code (default: 60601)")
    parser.add_argument("--radius", type=int, default=50, help="Search radius in miles")
    parser.add_argument("--make", default="Toyota")
    parser.add_argument("--model", default="Corolla")
    parser.add_argument("--max-price", type=int, default=18000)
    parser.add_argument("--max-miles", type=int, default=90000)
    parser.add_argument("--pages", type=int, default=5, help="Maximum pages for each search (50 listings per page)")
    parser.add_argument("--output", default="chicago_cars.csv")
    parser.add_argument("--database", default="car_history.sqlite3", help="Local price history database")
    parser.add_argument("--history", metavar="VIN", help="Show saved observations for a VIN without searching")
    args = parser.parse_args()
    if args.radius <= 0 or args.max_price < 1000 or args.max_miles <= 0 or args.pages <= 0:
        parser.error("radius, max-miles and pages must be positive; max-price must be at least 1000")
    return args


def fetch(params):
    request = Request(API_URL + "?" + urlencode(params), headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"MarketCheck returned HTTP {exc.code}; check your key, plan and parameters.") from None
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"Could not retrieve a valid response ({type(exc).__name__}).") from None


def normalize(item):
    price = item.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        return None
    build, dealer = item.get("build") or {}, item.get("dealer") or {}
    identity = item.get("vin") or item.get("id")
    if not identity:
        return None
    return {"identity": str(identity), "vin": str(item.get("vin") or "").strip().upper(),
            "year": build.get("year"), "make": build.get("make") or "", "model": build.get("model") or "",
            "trim": build.get("trim") or "", "price": price, "miles": item.get("miles"),
            "dealer": dealer.get("name") or "", "city": dealer.get("city") or "", "url": item.get("vdp_url") or ""}


def search(params, pages):
    cars = {}
    total = 0
    retrieved = 0
    for page in range(pages):
        start = page * 50
        data = fetch({**params, "start": start})
        listings = data.get("listings") or []
        total = data.get("num_found", 0)
        retrieved += len(listings)
        for item in listings:
            car = normalize(item)
            if car and (car["identity"] not in cars or car["price"] < cars[car["identity"]]["price"]):
                cars[car["identity"]] = car
        if not listings or start + len(listings) >= total:
            break
        if page + 1 < pages:
            time.sleep(0.5)
    return list(cars.values()), total, retrieved < total


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if 0 <= result < 10**9 else None
    except (ValueError, TypeError):
        return None


def comparable(car, other):
    if car["identity"] == other["identity"]:
        return False
    # Missing trim, year or miles cannot support a reliable comparison.
    trim = str(car["trim"]).strip().casefold()
    if not trim or trim != str(other["trim"]).strip().casefold():
        return False
    if any(str(car[k]).strip().casefold() != str(other[k]).strip().casefold() or not car[k]
           for k in ("make", "model")):
        return False
    year, other_year, miles, other_miles = map(number, (car["year"], other["year"], car["miles"], other["miles"]))
    return (all(v is not None for v in (year, other_year, miles, other_miles))
            and abs(year - other_year) <= 1 and abs(miles - other_miles) <= 15000)


def compare_market(car, market, incomplete):
    prices = [other["price"] for other in market if comparable(car, other)]
    car.update(market_median="", comparable_count=len(prices), market_difference="",
               market_difference_percent="", market_status="insufficient_comparables")
    if len(prices) < 5:
        return
    median = statistics.median(prices)
    difference = car["price"] - median
    car.update(market_median=round(median, 2), market_difference=round(difference, 2),
               market_difference_percent=round(100 * difference / median, 2),
               market_status=("sample_incomplete" if incomplete else
                              "below_median" if difference < 0 else "above_median" if difference > 0 else "at_median"))


def open_database(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, vin TEXT NOT NULL, "
               "observed_at TEXT NOT NULL, price REAL NOT NULL, dealer TEXT, url TEXT)")
    db.execute("CREATE INDEX IF NOT EXISTS observations_vin_id ON observations(vin, id)")
    return db


def record_prices(db, cars):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db:
        for car in cars:
            car.update(previous_price="", price_drop="", price_drop_percent="")
            if not car["vin"]:
                continue
            row = db.execute("SELECT price FROM observations WHERE vin = ? ORDER BY id DESC LIMIT 1", (car["vin"],)).fetchone()
            if row:
                previous = row[0]
                car["previous_price"] = previous
                if car["price"] < previous:
                    drop = previous - car["price"]
                    car["price_drop"] = round(drop, 2)
                    car["price_drop_percent"] = round(100 * drop / previous, 2)
            db.execute("INSERT INTO observations(vin, observed_at, price, dealer, url) VALUES (?, ?, ?, ?, ?)",
                       (car["vin"], now, car["price"], car["dealer"], car["url"]))


def main():
    args = parse_args()
    if args.history:
        if not os.path.isfile(args.database):
            print("History database does not exist yet.", file=sys.stderr)
            return 1
        with open_database(args.database) as db:
            rows = db.execute("SELECT observed_at, price, dealer, url FROM observations WHERE vin = ? ORDER BY id", (args.history.strip().upper(),)).fetchall()
        if not rows:
            print("No observations found for this VIN.")
        for observed, price, dealer, url in rows:
            print(f"{observed}  ${price:,.2f}  {dealer or ''}  {url or ''}")
        return 0
    key = os.environ.get("MARKETCHECK_API_KEY")
    if not key:
        print("Set MARKETCHECK_API_KEY first. See README.md.", file=sys.stderr)
        return 1
    base = {"api_key": key, "zip": args.zip, "radius": args.radius, "car_type": "used",
            "make": args.make, "model": args.model, "rows": 50, "append_api_key": "false"}
    targets, total, target_incomplete = search({**base, "price_range": f"1000-{args.max_price}",
                                                 "miles_range": f"0-{args.max_miles}"}, args.pages)
    market, market_total, market_incomplete = search(base, args.pages) if targets else ([], 0, False)
    for car in targets:
        compare_market(car, market, market_incomplete)
    with open_database(args.database) as db:
        record_prices(db, targets)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(targets, key=lambda car: car["price"]))
    print(f"Saved {len(targets)} listings to {args.output}; API reports {total} target matches.")
    print(f"Market sample: {len(market)} unique listings of {market_total} matches" + (" (incomplete)." if market_incomplete else "."))
    if target_incomplete:
        print("Target results are incomplete; increase --pages if your plan permits.")
    drops = [car for car in targets if car["price_drop"] != ""]
    print(f"Price drops since previous observation: {len(drops)}")
    for car in drops:
        print(f"  {car['vin']}: ${car['previous_price']:,.2f} -> ${car['price']:,.2f} (-${car['price_drop']:,.2f}, {car['price_drop_percent']:.2f}%) {car['url']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
