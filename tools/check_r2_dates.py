from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(".env"))

from juggler_predictor.storage.r2 import build_r2_client_from_env
import yaml

client = build_r2_client_from_env()

data = yaml.safe_load(Path("config/shops.yaml").read_text(encoding="utf-8"))
shops = data if isinstance(data, list) else data.get("shops", [])

header = "{:30s} {:>5s}  {:>12s}  {:>12s}".format("shop_id", "days", "min_date", "max_date")
print(header)
print("-" * 70)

total = 0
for s in shops:
    sid = s["id"] if isinstance(s, dict) else s
    keys = list(client.list_keys(prefix=f"dataset/{sid}/"))
    dates = []
    for k in keys:
        name = k.rsplit("/", 1)[-1]
        d = name.split(".")[0]
        if len(d) == 10 and d[4] == "-" and d[7] == "-":
            dates.append(d)
    dates.sort()
    n = len(dates)
    total += n
    if dates:
        print("{:30s} {:>5d}  {:>12s}  {:>12s}".format(sid, n, dates[0], dates[-1]))
    else:
        print("{:30s} {:>5d}  {:>12s}  {:>12s}".format(sid, n, "-", "-"))

print("-" * 70)
print("{:30s} {:>5d}".format("TOTAL", total))
