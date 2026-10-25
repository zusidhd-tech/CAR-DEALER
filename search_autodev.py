"""Search Auto.dev vehicle listings with a server-side API key."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "https://api.auto.dev/listings"


def get_api_key():
    key = os.environ.get("AUTODEV_API_KEY", "").strip().strip('"\'')
    if key or os.name != "nt":
        return key
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            return str(winreg.QueryValueEx(handle, "AUTODEV_API_KEY")[0]).strip().strip('"\'')
    except (FileNotFoundError, OSError):
        return ""


def fetch(params, key):
    request = Request(
        URL + "?" + urlencode(params),
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("Auto.dev API key 无效或尚未启用。") from None
        if exc.code == 429:
            raise RuntimeError("Auto.dev 免费额度或请求速率已达到上限。") from None
        raise RuntimeError(f"Auto.dev 返回 HTTP {exc.code}。") from None
    except (URLError, TimeoutError, ValueError):
        raise RuntimeError("Auto.dev 暂时无法连接或返回了无效数据。") from None


def normalize(item):
    vehicle = item.get("vehicle") or {}
    listing = item.get("retailListing") or {}
    vin = str(vehicle.get("vin") or item.get("vin") or "").strip().upper()
    price = listing.get("price")
    miles = listing.get("miles")
    if not vin or isinstance(price, bool) or not isinstance(price, (int, float)) or price < 1000:
        return None
    if isinstance(miles, bool) or not isinstance(miles, (int, float)) or miles < 0:
        return None
    return {
        "identity": "AUTO:" + vin,
        "vin": vin,
        "listing_id": vin,
        "source": "Auto.dev",
        "year": vehicle.get("year"),
        "make": vehicle.get("make") or "",
        "model": vehicle.get("model") or "",
        "trim": vehicle.get("trim") or "",
        "price": price,
        "miles": miles,
        "dealer": listing.get("dealer") or "",
        "city": ", ".join(value for value in (listing.get("city"), listing.get("state")) if value),
        "url": listing.get("vdp") or "",
        "image_url": listing.get("primaryImage") or "",
    }


def search(args):
    key = get_api_key()
    if not key:
        raise RuntimeError("尚未配置 AUTODEV_API_KEY。")
    params = {
        "zip": args.zip,
        "distance": args.distance,
        "limit": 20,
        "sort": "updatedAt.desc",
        "retailListing.used": "true",
        "retailListing.price": f"1000-{args.max_price}",
        "retailListing.miles": f"0-{args.max_miles}",
        "includes": "total",
    }
    if args.make:
        params["vehicle.make"] = args.make
    if args.model:
        params["vehicle.model"] = args.model
    if args.min_year is not None or args.max_year is not None:
        params["vehicle.year"] = f"{args.min_year or 1886}-{args.max_year or args.latest_year}"
    cars = {}
    total = None
    for page in range(1, args.pages + 1):
        data = fetch({**params, "page": page}, key)
        rows = data.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Auto.dev 返回格式异常。")
        if isinstance(data.get("total"), int):
            total = data["total"]
        for item in rows:
            car = normalize(item)
            if car and (car["identity"] not in cars or car["price"] < cars[car["identity"]]["price"]):
                cars[car["identity"]] = car
        if len(rows) < 20:
            break
    incomplete = total is None or len(cars) < total
    return list(cars.values()), total, incomplete
