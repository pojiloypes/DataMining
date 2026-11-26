import asyncio, json, re, time, os
import requests
from bs4 import BeautifulSoup
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError


DINAMIC_URL = "https://www.scrapingcourse.com/javascript-rendering"
DINAMIC_TARGET = "Bruno Compete Hoodie"
DINAMIC_ITEM_NAME = ".product-item"
DINAMIC_PRODUCT_NAME = ".product-name"

STATIC_URL = "https://books.toscrape.com/"
STATIC_TARGET = "Tipping the Velvet"
STATIC_ITEM_NAME = ".product-pod"
STATIC_PRODUCT_NAME = ".product_pod h3 a"

TIMEOUT = 15_000

def diagnose(html, target, item_name, product_name):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(item_name)
    names = soup.select(product_name)
    
    print(f"\t{len(html):>6} байт HTML")
    print(f"\tНайдено {item_name} = {len(items)}")
    print(f"\tНайдено {product_name} = {len(names)}")
    print(f"\tЕсть искомое название({target}): {target in html}")
        
        
def run_html(url, target, item_name, product_name):
    html_server = requests.get(url, timeout=15,
                           headers={"User-Agent": "course-crawler/1.0"}).text
    
    diagnose(html_server, target, item_name, product_name)


def run_browser(url, target, item_name, product_name, js_enabled=True):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            java_script_enabled=js_enabled,
            user_agent="course-crawler/1.0 (educational use)",
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
        )
        context.set_default_timeout(TIMEOUT)
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(product_name)  
        except TimeoutError:
            print(f"Не дождался загрузки {product_name}")
            
        html_browser = page.content()
        diagnose(html_browser, target, item_name, product_name)


print('ДИНАМИЧЕСКИЙ САЙТ')
print("Простой Request")
run_html(DINAMIC_URL, DINAMIC_TARGET, DINAMIC_ITEM_NAME, DINAMIC_PRODUCT_NAME)

print("Браузер")
run_browser(DINAMIC_URL, DINAMIC_TARGET, DINAMIC_ITEM_NAME, DINAMIC_PRODUCT_NAME)

print("Браузер без js")
run_browser(DINAMIC_URL, DINAMIC_TARGET, DINAMIC_ITEM_NAME, DINAMIC_PRODUCT_NAME, False)

print('\nСТАТИЧЕСКИЙ САЙТ')
print("Простой Request")
run_html(STATIC_URL, STATIC_TARGET, STATIC_ITEM_NAME, STATIC_PRODUCT_NAME)

print("Браузер")
run_browser(STATIC_URL, STATIC_TARGET, STATIC_ITEM_NAME, STATIC_PRODUCT_NAME)

print("Браузер без js")
run_browser(STATIC_URL, STATIC_TARGET, STATIC_ITEM_NAME, STATIC_PRODUCT_NAME, False)