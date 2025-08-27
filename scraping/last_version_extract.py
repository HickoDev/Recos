# last_version_extract.py
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, 'screenshots', 'versions')

# Desktop UA to avoid CDN/headless blocks
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

def _build_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')       # headless, doc-style
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
    # OneTrust is common on Cisco
    try:
        btn = wait.until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(0.2)
        print("[cookies] accepted")
    except TimeoutException:
        pass

def scrape_latest_version(url: str) -> dict | None:
    """
    Open a Cisco software page URL and return:
      {
        "switch_type": str,
        "latest_version": str,
        "final_url": str,
        "selected_label": str | None,
        "screenshot_file": str
      }
    Saves a screenshot under screenshots/versions/.
    """
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    driver = _build_driver()
    wait = WebDriverWait(driver, 40)

    try:
        print(f"[open] {url}")
        driver.get(url)
        _accept_cookies_if_any(driver, wait)

        selected_label = None

        # If /type page, choose one of the known labels (IOS Software first)
        if '/type' in driver.current_url:
            print("[type] page detected — trying to pick a software family…")

            # Ensure the list is present
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[@id='stos-list']")))
            preferred_labels = ["IOS Software", "IOS XE Software", "NX-OS System Software", "Switch Firmware"]

            for label in preferred_labels:
                # Try exact anchor match; fallback to li[contains(text())]
                xpath_anchor = f"//*[@id='stos-list']//a[normalize-space()='{label}']"
                elems = driver.find_elements(By.XPATH, xpath_anchor)
                if not elems:
                    xpath_li = f"//*[@id='stos-list']//li[contains(normalize-space(), '{label}')]"
                    elems = driver.find_elements(By.XPATH, xpath_li)
                if not elems:
                    continue

                target = elems[0]
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
                prev_url = driver.current_url
                try:
                    wait.until(EC.element_to_be_clickable((By.XPATH, xpath_anchor if elems and elems[0].tag_name.lower() == "a" else xpath_li)))
                    # JS click avoids overlay/interception in headless
                    driver.execute_script("arguments[0].click();", target)
                except Exception:
                    driver.execute_script("arguments[0].click();", target)

                # Wait for URL change after selecting a family
                try:
                    wait.until(lambda d: d.current_url != prev_url)
                    time.sleep(0.4)
                    selected_label = label
                    print(f"[type] selected: {label}")
                    break
                except TimeoutException:
                    print(f"[warn] click on '{label}' did not change URL; trying next…")
                    continue

        # Wait for “Latest Release” (or equivalent) to appear
        print("[wait] version info…")
        # Primary indicator
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//span[contains(text(), 'Latest Release')]")
            ))
        except TimeoutException:
            # Some pages render slightly differently; small grace wait
            time.sleep(2)

        # Pull version text (your original absolute XPath kept)
        version_xpath = ("/html/body/app-root/div/main/div/div/app-release-page/div/div[1]/app-release-details/nav/div[4]/"
                         "tree-root/tree-viewport/div/div/tree-node-collection/div/tree-node[1]/div/tree-node-children/div/"
                         "tree-node-collection/div/tree-node[1]/div/tree-node-wrapper/div/div/tree-node-content/div/div/span")
        try:
            version_text = driver.find_element(By.XPATH, version_xpath).text.strip()
        except Exception:
            # Mild fallback: first tree-node version text
            version_text = driver.find_element(By.CSS_SELECTOR, "tree-node-content div div span").text.strip()

        # Append “(recommended)” if suggested star present
        try:
            stars = driver.find_elements(By.CSS_SELECTOR, "span.icon-software-suggested.icon-small.suggestedStar")
            if any(s.is_displayed() for s in stars):
                version_text = f"{version_text} (recommended)"
        except Exception:
            pass

        # Switch type title (your original XPath kept)
        try:
            switch_type = driver.find_element(
                By.XPATH,
                "/html/body/app-root/div/main/div/div/app-release-page/div/div[2]/app-image-details/div[1]/h2"
            ).text.strip()
        except Exception:
            # Fallback: any H2 inside app-image-details
            switch_type = driver.find_element(By.CSS_SELECTOR, "app-image-details h2").text.strip()

        # Save screenshot
        safe_switch_type = "".join(c for c in switch_type if c.isalnum() or c in (' ', '-', '_')).strip()
        screenshot_file = os.path.join(SCREENSHOTS_DIR, f"latest_version_{safe_switch_type}.png")
        driver.save_screenshot(screenshot_file)

        return {
            "switch_type": switch_type,
            "latest_version": version_text,
            "final_url": driver.current_url,
            "selected_label": selected_label,
            "screenshot_file": screenshot_file
        }

    except Exception as e:
        print(f"[error] {e}")
        return None
    finally:
        driver.quit()

if __name__ == '__main__':
    # quick manual test against a /type URL
    print(scrape_latest_version("https://software.cisco.com/download/home/282440588/type"))
