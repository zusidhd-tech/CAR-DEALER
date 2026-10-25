"""Search active dealer listings around a ZIP code with MarketCheck."""

import argparse
import csv
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

API_URL = "https://api.marketcheck.com/v2/search/car/active"
COLUMNS = ("vin", "year", "make", "model", "trim", "price", "miles",
           "dealer", "city", "url")


def parse_args():
    parser = argparse.ArgumentParser(description="Find used dealer cars near a ZIP code.")
    parser.add_argument("--zip", default="60601", help="ZIP code (default: 60601)")
    parser.add_argument("--radius", type=int, default=50, help="Search radius in miles")
    parser.add_argument("--make", default="Toyota")
    parser.add_argument("--model", default="Corolla")
    parser.add_argument("--max-price", type=int, default=18000)
    parser.add_argument("--max-miles", type=int, default=90000)
    parser.add_argument("--pages", type=int, default=5, help="Maximum pages, 50 listings per page")
    parser.add_argument("--output", default="chicago_cars.csv")
    args = parser.parse_args()
    if args.radius <= 0 or args.max_price <= 0 or args.max_miles <= 0 or args.pages <= 0:
        parser.error("radius, max-price, max-miles and pages must be positive")
    return args


def fetch(params):
    request = Request(API_URL + "?" + urlencode(params), headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        # The URL contains the API key, so do not print the exception or request.
        raise RuntimeError(f"MarketCheck returned HTTP {exc.code}; check your key, plan and search parameters.") from None
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"Could not retrieve a valid response ({type(exc).__name__}).") from None


def main():
    args = parse_args()
    key = os.environ.get("MARKETCHECK_API_KEY")
    if not key:
        print("Set the MARKETCHECK_API_KEY environment variable first. See README.md.", file=sys.stderr)
        return 1
    params = {
        "api_key": key, "zip": args.zip, "radius": args.radius,
        "car_type": "used", "make": args.make, "model": args.model,
        "price_range": f"1000-{args.max_price}",
        "miles_range": f"0-{args.max_miles}", "rows": 50,
        "append_api_key": "false",
    }
    if args.max_price < 1000:
        print("max-price must be at least 1000.", file=sys.stderr)
        return 1
    cars = {}
    total = 0
    for page in range(args.pages):
        start = page * 50
        data = fetch({**params, "start": start})
        listings = data.get("listings") or []
        total = data.get("num_found", 0)
        for item in listings:
            price = item.get("price")
            identity = item.get("vin") or item.get("id")
            if not identity or not isinstance(price, (int, float)) or price <= 0:
                continue
            build, dealer = item.get("build") or {}, item.get("dealer") or {}
            car = {"vin": item.get("vin", ""), "year": build.get("year", ""),
                   "make": build.get("make", ""), "model": build.get("model", ""),
                   "trim": build.get("trim", ""), "price": price,
                   "miles": item.get("miles", ""), "dealer": dealer.get("name", ""),
                   "city": dealer.get("city", ""), "url": item.get("vdp_url", "")}
            if identity not in cars or price < cars[identity]["price"]:
                cars[identity] = car
        if not listings or start + len(listings) >= total:
            break
        if page + 1 < args.pages:
            time.sleep(0.5)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(cars.values(), key=lambda car: car["price"]))
    print(f"Saved {len(cars)} unique listings to {args.output}. API reports {total} matches.")
    if total > args.pages * 50:
        print("Results may be incomplete; increase --pages if your API plan permits.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
