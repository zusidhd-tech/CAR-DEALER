"""Search CLCAuto's public listings without credentials."""
import argparse
import csv
import json
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from search_cars import compare_market, open_database, record_prices

URL = "https://www.clcauto.com/api/v1/cars"
COLUMNS = ("listing_id", "year", "make", "model", "trim", "price", "miles", "dealer", "city", "url",
           "previous_price", "price_drop", "price_drop_percent", "market_median", "comparable_count",
           "market_difference", "market_difference_percent", "market_status")


def parse_args():
    p = argparse.ArgumentParser(description="Search public CLCAuto dealer listings by location.")
    p.add_argument("--location", default="Chicago", help="City or location text, not a radius (default Chicago)")
    p.add_argument("--make", default="", help="Optional make")
    p.add_argument("--model", default="", help="Optional model")
    p.add_argument("--max-price", type=int, default=18000)
    p.add_argument("--max-miles", type=int, default=90000)
    p.add_argument("--pages", type=int, default=5, help="Maximum pages of 100 listings")
    p.add_argument("--output", default="chicago_clcauto.csv")
    p.add_argument("--database", default="car_history.sqlite3")
    args = p.parse_args()
    if args.max_price <= 0 or args.max_miles <= 0 or not 1 <= args.pages <= 10:
        p.error("price and miles must be positive; pages must be between 1 and 10")
    return args


def fetch(params):
    request = Request(URL + "?" + urlencode(params), headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"CLCAuto returned HTTP {exc.code} (rate limit or search parameters).") from None
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"CLCAuto request failed ({type(exc).__name__}).") from None


def normalize(item):
    seller, location = item.get("seller") or {}, item.get("location") or {}
    if seller.get("account_type") != "dealer" or item.get("currency") != "USD" or item.get("mileage_unit") != "mi":
        return None
    price, listing_id = item.get("price"), item.get("id")
    if not listing_id or isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        return None
    identity = "CLC:" + str(listing_id).upper()
    return {"identity": identity, "vin": identity, "listing_id": listing_id,
            "year": item.get("year"), "make": item.get("make") or "", "model": item.get("model") or "",
            "trim": item.get("trim") or "", "price": price, "miles": item.get("mileage"),
            "dealer": seller.get("username") or "", "city": location.get("name") or "", "url": item.get("url") or ""}


def search(args):
    params = {"location": args.location, "limit": 100, "lang": "en"}
    if args.make:
        params["make"] = args.make
    if args.model:
        params["model"] = args.model
    cars = {}
    cursor = None
    for page in range(args.pages):
        data = fetch({**params, **({"cursor": cursor} if cursor else {})})
        if not isinstance(data.get("data"), list):
            raise RuntimeError("Unexpected CLCAuto response; no data list.")
        for item in data["data"]:
            car = normalize(item)
            if car:
                cars[car["identity"]] = car
        cursor = data.get("next_cursor")
        if not cursor:
            break
        if page + 1 < args.pages:
            time.sleep(3.2)  # Stay below the anonymous limit of 20 requests/minute.
    return list(cars.values()), bool(cursor)


def main():
    args = parse_args()
    market, incomplete = search(args)
    targets = [car for car in market if car["price"] <= args.max_price and
               isinstance(car["miles"], (int, float)) and 0 <= car["miles"] <= args.max_miles]
    for car in targets:
        compare_market(car, market, incomplete)
    with open_database(args.database) as db:
        record_prices(db, targets)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(targets, key=lambda c: c["price"]))
    print(f"Found {len(targets)} matching dealer listings from {len(market)} priced dealer listings in {args.location}.")
    print(f"Saved {args.output}." + (" Market sample is incomplete; increase --pages." if incomplete else ""))
    drops = [car for car in targets if car["price_drop"] != ""]
    print(f"Price drops since last observation: {len(drops)}")
    for car in drops:
        print(f"  {car['url']}  ${car['previous_price']:,.2f} -> ${car['price']:,.2f} (-${car['price_drop']:,.2f})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

