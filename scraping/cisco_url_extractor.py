# cisco_url_extractor.py
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import os

import os

BASE_URL = 'https://software.cisco.com/download/home'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
OUTPUT_FILE = os.path.join(DATA_DIR, 'cisco_urls.txt')

# A normal desktop UA helps headless pass CDN checks
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

def _build_driver():
    proxies = {
        "http_proxy": "http://proxy.dsi.scom:8080",
        "https_proxy": "http://proxy.dsi.scom:8080",
        "no_proxy": "localhost,127.0.0.1,::1"
    }
    for p in proxies:
        os.environ[p] = proxies[p]
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')       # ← enable headless
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--log-level=3')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_argument(f'--user-agent={UA}')   # UA at startup

    driver = webdriver.Chrome(options=chrome_options)
    # Page-level UA override via CDP (extra insurance)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": UA})
    except Exception:
        pass
    return driver

def _accept_cookies_if_any(driver, wait):
    try:
        btn = wait.until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(0.2)
        print("[cookies] accepted")
    except TimeoutException:
        pass

def extract_url_for_model(model_name: str, save_to_file: bool = True) -> str | None:
    """Return the Cisco download URL for a given model name."""
    driver = _build_driver()
    wait = WebDriverWait(driver, 40)
    final_url = None

    try:
        print(f"[model] {model_name}")
        driver.get(BASE_URL)

        # Basic block check (optional)
        if "Access Denied" in driver.page_source:
            print("[blocked] CDN blocked at home page")
            return None

        _accept_cookies_if_any(driver, wait)

        # Search box (your original selector kept, with fallbacks)
        search_input = None
        for by, sel in [
            (By.XPATH, "/html/body/app-root/div/main/div/div/app-home/div[3]/app-psa/div/div[1]/div/div[2]/form/div/div/input"),
            (By.CSS_SELECTOR, "app-home app-psa input[type='text']"),
            (By.CSS_SELECTOR, "input[placeholder*='Search']"),
        ]:
            try:
                search_input = wait.until(EC.element_to_be_clickable((by, sel)))
                break
            except TimeoutException:
                continue
        if not search_input:
            raise TimeoutException("Search input not found")

        search_input.click()
        time.sleep(0.2)
        search_input.clear()
        search_input.send_keys(model_name)
        print("[search] waiting suggestions…")

        # Wait for typeahead container
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ngb-typeahead-window")))
        # IMPORTANT: click the BUTTON (not the inner div), and use JS click
        first_button = wait.until(EC.element_to_be_clickable((
            By.CSS_SELECTOR, "ngb-typeahead-window button"
        )))
        driver.execute_script("arguments[0].click();", first_button)

        # Wait for navigation off the home page
        wait.until(lambda d: (d.current_url != BASE_URL) and
                            ("/download/" in d.current_url or d.current_url.endswith("/type")))
        time.sleep(0.4)
        current_url = driver.current_url
        print(f"[nav] landed on: {current_url}")

        

        final_url = current_url

        if save_to_file and final_url:
            with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{model_name}: {final_url}\n")
            print(f"[saved] {final_url}")

        return final_url

    except Exception as e:
        print(f"[error] {e}")
        return None
    finally:
        driver.quit()

if __name__ == '__main__':
    # quick manual test
    print(extract_url_for_model("Catalyst 1000 Switch 10G Stack"))
