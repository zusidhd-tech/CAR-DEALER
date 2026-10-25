"""Market references from current listings and ForCar's open aggregates."""
import csv
import io
import os
import re
import statistics
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from search_cars import comparable, number

SOURCE_URL = "https://forcar.org/open-data/"
CSV_URL = "https://forcar.org/datasets/used-car-prices-by-model-year.csv"
CACHE = Path(__file__).resolve().parent / "forcar_model_year.csv"
MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()
_last_attempt = 0.0


def key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def parse_csv(content):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("CSV 为空或超过 5 MB。")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        required = {"make", "model", "model_year", "listings", "avg_price_usd", "avg_mileage"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV 字段不符合 ForCar 车型年份数据格式。")
        rows = {}
        for row in reader:
            year = number(row.get("model_year"))
            count = number(row.get("listings"))
            price = number(row.get("avg_price_usd"))
            miles = number(row.get("avg_mileage"))
            make, model = key(row.get("make")), key(row.get("model"))
            if (not make or not model or year is None or not year.is_integer() or
                    count is None or count < 5 or price is None or price < 1000 or miles is None):
                continue
            rows[(make, model, int(year))] = {"price": price, "count": int(count), "miles": miles}
        if not rows:
            raise ValueError("CSV 中没有可用的 ForCar 价格统计。")
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("无法读取 CSV，请选择 UTF-8 编码的 ForCar 文件。") from exc


def save_csv(content):
    rows = parse_csv(content)
    with _lock:
        fd, path = tempfile.mkstemp(prefix="forcar_", suffix=".tmp", dir=CACHE.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(content)
            os.replace(path, CACHE)
        finally:
            if os.path.exists(path):
                os.unlink(path)
    return len(rows)


def load_data():
    """Refresh at most daily; keep a valid cached copy if the source is unavailable."""
    global _last_attempt
    with _lock:
        rows, modified = {}, None
        try:
            rows = parse_csv(CACHE.read_bytes())
            modified = CACHE.stat().st_mtime
        except (OSError, ValueError):
            pass
        now = time.time()
        warning = ""
        if (modified is None or now - modified >= 86400) and now - _last_attempt >= 3600:
            _last_attempt = now
            try:
                request = Request(CSV_URL, headers={"User-Agent": "CarScout/1.0", "Accept": "text/csv"})
                with urlopen(request, timeout=8) as response:
                    content = response.read(MAX_BYTES + 1)
                fresh = parse_csv(content)
                fd, path = tempfile.mkstemp(prefix="forcar_", suffix=".tmp", dir=CACHE.parent)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(content)
                    os.replace(path, CACHE)
                finally:
                    if os.path.exists(path):
                        os.unlink(path)
                rows, modified = fresh, time.time()
            except (OSError, URLError, TimeoutError, ValueError):
                warning = "ForCar 自动更新失败；" + ("正在使用本地缓存。" if rows else "可从 ForCar 下载 CSV 并在左侧导入。")
        if not warning and not rows:
            warning = "尚未导入 ForCar 数据；可从 ForCar 下载 CSV 并在左侧导入。"
        elif not warning and modified is not None and now - modified >= 86400:
            warning = "ForCar 本地缓存已超过 24 小时；自动更新失败或尚未重试，可手动导入新 CSV。"
        return rows, {"cached_at": datetime.fromtimestamp(modified, timezone.utc).isoformat() if modified else None,
                      "warning": warning}


def loose_comparable(car, other):
    if car.get("identity") == other.get("identity"):
        return False
    if not all(key(car.get(field)) and key(car.get(field)) == key(other.get(field)) for field in ("make", "model")):
        return False
    year, other_year, miles, other_miles = map(number, (car.get("year"), other.get("year"), car.get("miles"), other.get("miles")))
    return (all(value is not None for value in (year, other_year, miles, other_miles)) and
            abs(year - other_year) <= 1 and abs(miles - other_miles) <= 15000)


def assess(car, market, benchmarks):
    """Use strict, then relaxed current comparables, then a national aggregate."""
    strict = [other["price"] for other in market if comparable(car, other)]
    relaxed = [other["price"] for other in market if loose_comparable(car, other)]
    car["valuation"] = None
    if len(strict) >= 5 or len(relaxed) >= 5:
        prices, tier = (strict, "same_trim") if len(strict) >= 5 else (relaxed, "model")
        median = statistics.median(prices)
        car["valuation"] = {"source": "live", "tier": tier, "reference": round(median, 2),
                            "count": len(prices), "difference": round(car["price"] - median, 2)}
        return
    year = number(car.get("year"))
    row = benchmarks.get((key(car.get("make")), key(car.get("model")), int(year))) if year is not None and year.is_integer() else None
    if row:
        car["valuation"] = {"source": "forcar", "tier": "national", "reference": row["price"],
                            "count": row["count"], "average_miles": row["miles"],
                            "difference": round(car["price"] - row["price"], 2)}
