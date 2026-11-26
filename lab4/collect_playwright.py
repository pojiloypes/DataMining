from pathlib import Path
import time
from datetime import datetime, timezone

import pandas as pd
import psutil
from playwright.sync_api import sync_playwright

URL = "https://www.scrapingcourse.com/javascript-rendering"
TIMEOUT = 15_000
MAX_ITERATIONS = 10
MAX_RECORDS = 200
CARD = ".product-item"
folder = Path(__file__).resolve().parent / "results" / "browser"
artifacts = folder / "artifacts"
artifacts.mkdir(parents=True, exist_ok=True)

collection_log = []
extraction_benchmark = []
quality = []

EXTRACT = """
els => els.map(el => {
    const name = el.querySelector('.product-name');
    const price = el.querySelector('.product-price');
    const link = el.querySelector('a.product-link');
    const image = el.querySelector('img.product-image');

    return {
        name: name ? name.textContent.trim() : '',
        price: price ? price.textContent.trim() : '',
        link: link ? link.href : '',
        image: image ? image.src : ''
    };
})
"""


def save_artifacts(page, name):
    try:
        with open(artifacts / (name + ".html"), "w", encoding="utf-8") as file:
            file.write(page.content())
        page.screenshot(path=artifacts / (name + ".png"), timeout=5000)
    except Exception as error:
        print("Не удалось сохранить артефакт:", error)


def smoke_check(df):
    empty = df.replace(r"^\s*$", pd.NA, regex=True)
    missing = empty[["name", "price", "link"]].isna().any(axis=1).mean()
    print("Неполных обязательных записей:", round(missing * 100, 2), "%")
    return empty.isna().mean() * 100


def measure_memory():
    process = psutil.Process()
    memory = 0
    for child in [process] + process.children(recursive=True):
        try:
            memory += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return memory / 1024 ** 2

def collect(block_resources=False):
    mode = "browser"
    if block_resources:
        mode = "browser_blocked"
    print("\nРежим:", mode)
    records = []
    links = set()
    stats = {"requests": 0, "bytes": 0, "blocked": 0}
    memory = {"memory_before_launch_mib": measure_memory()}
    start = time.time()

    with sync_playwright() as pw:
        browser = None
        context = None
        page = None
        try:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                java_script_enabled=True,
                user_agent="student/1.0 (educational use)",
                viewport={"width": 1280, "height": 900},
                locale="ru-RU",
            )
            context.set_default_timeout(TIMEOUT)
            context.set_default_navigation_timeout(TIMEOUT)
            page = context.new_page()
            memory["memory_after_launch_mib"] = measure_memory()

            def count_request(request):
                stats["requests"] += 1

            def count_traffic(request):
                stats["bytes"] += request.sizes()["responseBodySize"]

            def block_request(route):
                if route.request.resource_type in ["image", "font", "media"]:
                    stats["blocked"] += 1
                    route.abort()
                else:
                    route.continue_()

            page.on("request", count_request)
            page.on("requestfinished", count_traffic)
            if block_resources:
                page.route("**/*", block_request)

            t0 = time.time()
            page.goto(URL, wait_until="commit")
            page.wait_for_selector(".product-item .product-name")
            memory["memory_after_load_mib"] = measure_memory()

            cards = page.locator(CARD)
            for i in range(MAX_ITERATIONS + 1):
                status = "initial_load"
                if i > 0:
                    time.sleep(0.5)
                    t0 = time.time()
                    page.mouse.wheel(0, 20000)

                products = page.eval_on_selector_all(CARD, EXTRACT)
                elements = len(products)
                new_products = []
                for product in products:
                    if product["link"] not in links:
                        new_products.append(product)

                growth = 0
                for product in new_products:
                    if len(records) >= MAX_RECORDS:
                        break
                    if product["link"] not in links:
                        records.append(product)
                        links.add(product["link"])
                        growth += 1
                if i > 0:
                    status = "new_items"
                    if growth == 0:
                        status = "no_growth"
                collection_log.append({"mode": mode, "iteration": i,
                             "elements": elements, "growth": growth,
                             "total_collected": len(records),
                             "time": time.time() - t0,
                             "timestamp": datetime.now(timezone.utc).isoformat(),
                             "url": page.url, "status": status})
                print("Итерация:", i, "| товаров:", len(records), "| новых:", growth)
                if growth == 0 or len(records) >= MAX_RECORDS:
                    break
                
            # Чтение по одному
            read_start = time.time()
            for card in cards.all():
                card.locator(".product-name").text_content().strip()
                card.locator(".product-price").text_content().strip()
                card.locator("a.product-link").evaluate("el => el.href")
                card.locator("img.product-image").evaluate("el => el.src")
            slow_time = time.time() - read_start

            # Чтение сразу всех
            read_start = time.time()
            page.eval_on_selector_all(CARD, EXTRACT)
            fast_time = time.time() - read_start
            extraction_benchmark.append({"mode": mode,
                               "per_element_time": slow_time,
                               "bulk_time": fast_time,
                               "speedup": slow_time / fast_time})
            memory["memory_after_collect_mib"] = measure_memory()
        except Exception as error:
            if page is not None:
                save_artifacts(page, mode + "_error")
            collection_log.append({"mode": mode, "timestamp": datetime.now(timezone.utc).isoformat(),
                                   "url": URL, "status": str(error)})
            raise
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            memory["memory_after_close_mib"] = measure_memory()

    total_time = time.time() - start

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError("Не собрано ни одного товара")
    df["name"] = df["name"].str.replace(r"\s+", " ", regex=True).str.strip()
    df["price"] = pd.to_numeric(df["price"].str.replace("$", "", regex=False).str.strip())

    print("Собрано товаров:", len(df))
    print("Дубликатов:", df.duplicated("link").sum())
    df = df.drop_duplicates("link")

    missing = smoke_check(df)
    print("Пропуски по полям, %:")
    print(missing)
    for field, percent in missing.items():
        quality.append({"mode": mode, "field": field, "missing_percent": percent})
    if missing.any() or (df["price"] <= 0).any():
        raise ValueError("Есть пустые поля или некорректные цены")

    df.to_csv(folder / f"data_{mode}.csv", index=False, encoding="utf-8-sig")
    metric = {"mode": mode, "records": len(df), "time": total_time,
              "requests": stats["requests"], "blocked_requests": stats["blocked"],
              "traffic_mb": stats["bytes"] / 1024 ** 2,
              "peak_observed_rss_mib": max(memory.values()),
              "time_per_record": total_time / len(df)}
    metric.update(memory)
    print("Результат сохранён:", f"data_{mode}.csv")
    print(f"Ускорение массового чтения: {slow_time / fast_time:.2f} раза")

    return df, metric

if __name__ == "__main__":
    metrics = []
    
    for blocked in [False, True]:
        mode = "browser"
        if blocked:
            mode = "browser_blocked"
        try:
            df, metric = collect(blocked)
            metrics.append(metric)
        except Exception as error:
            print("ОШИБКА:", error)
    pd.DataFrame(collection_log).to_csv(folder / "collection_log.csv", index=False)
    
    pd.DataFrame(extraction_benchmark).to_csv(folder / "extraction_benchmark.csv", index=False)
    
    pd.DataFrame(quality).to_csv(folder / "quality.csv", index=False)
    
    pd.DataFrame(metrics).to_csv(folder / "metrics.csv", index=False)

    time_saved = metrics[0]["time"] - metrics[1]["time"]
    traffic_saved = metrics[0]["traffic_mb"] - metrics[1]["traffic_mb"]
    print(f"\nЭкономия времени: {time_saved:.2f} c.")
    print(f"Экономия трафика: {traffic_saved:.2f} МиБ.")
