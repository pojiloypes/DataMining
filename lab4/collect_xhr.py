from pathlib import Path
from datetime import datetime, timezone
import random
import time

import pandas as pd
import psutil
import requests

URL = "https://www.scrapingcourse.com/ajax/products/json"
folder = Path(__file__).resolve().parent / "results" / "light"
folder.mkdir(parents=True, exist_ok=True)


def collect():
    process = psutil.Process()
    memory = [process.memory_info().rss]
    logs = []
    traffic = 0
    request_count = 0
    start = time.perf_counter()

    try:
        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "student/1.0 (educational use)",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            })
            for attempt in range(3):
                request_start = time.perf_counter()
                request_count += 1
                response = session.get(URL, timeout=15)
                request_count += len(response.history)
                traffic += len(response.content)
                elements = 0
                if response.ok:
                    products = response.json()
                    elements = len(products)
                logs.append({"mode": "light", "iteration": attempt + 1,
                             "elements": elements, "growth": elements, "total_collected": elements,
                             "time": time.perf_counter() - request_start,
                             "timestamp": datetime.now(timezone.utc).isoformat(),
                             "url": response.url, "status": response.status_code})

                if (response.status_code == 429 or 500 <= response.status_code < 600) and attempt < 2:
                    delay = 2 ** attempt + random.random()
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.strip().isdigit():
                        delay = max(delay, int(retry_after))
                    print("Повтор запроса через", round(delay, 2), "с.")
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                break
    finally:
        if logs:
            pd.DataFrame(logs).to_csv(folder / "collection_log.csv", index=False)

    memory.append(process.memory_info().rss)


    records = []
    for product in products:
        name = " ".join(product["name"].split())

        slug = name.lower().replace(" ", "-")
        image = product["images"].split(",")[0].split("/")[-1]
        records.append({
            "name": name,
            "price": product["regular_price"],
            "link": "https://scrapingcourse.com/ecommerce/product/" + slug,
            "image": "https://scrapingcourse.com/ecommerce/wp-content/uploads/2024/03/" + image,
        })

    df = pd.DataFrame(records, columns=["name", "price", "link", "image"])
    if df.empty:
        raise ValueError("API вернул пустой набор товаров")
    
    df["price"] = pd.to_numeric(df["price"])
    print("Дубликатов:", df.duplicated("link").sum())
    
    df = df.drop_duplicates("link")
    missing = df.replace(r"^\s*$", pd.NA, regex=True).isna().mean() * 100
    
    print("Пропуски по полям, %:")
    print(missing)
    if missing.any() or (df["price"] <= 0).any():
        raise ValueError("Есть пустые поля или некорректные цены")

    memory.append(process.memory_info().rss)
    total_time = time.perf_counter() - start
    df.to_csv(folder / "data_light.csv", index=False, encoding="utf-8-sig")
    metric = {"mode": "light", "records": len(df), "time": total_time,
              "requests": request_count,
              "traffic_mb": traffic / 1024 ** 2,
              "peak_observed_rss_mib": max(memory) / 1024 ** 2,
              "time_per_record": total_time / len(df)}
    pd.DataFrame([metric]).to_csv(folder / "metrics.csv", index=False)
    quality = []
    for field, percent in missing.items():
        quality.append({"mode": "light", "field": field, "missing_percent": percent})
    pd.DataFrame(quality).to_csv(folder / "quality.csv", index=False)

    print(f"Товаров через XHR: {len(df)}")
    print(f"Время: {total_time:.2f}с. | запросов: {request_count}")


if __name__ == "__main__":
    collect()
