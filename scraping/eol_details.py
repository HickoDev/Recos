#!/usr/bin/env python3
"""
Selenium scraper to retrieve End-of-Sale and End-of-Support (Last Date of Support)
for Cisco products via the Support site flow provided.

Steps:
	1) Open https://www.cisco.com/c/en/us/support/index.html
	2) Click button: /html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/button/span[2]
	3) Type alias in input: /html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/div/div/form/div[1]/input
	4) Click first suggestion: /html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/div/div/div[1]/ul/li[1]/div/ul/li[1]/a/span[2]
	5) On the opened page, locate the table: /html/body/div[2]/div[2]/div/div/div[1]/table
	 Then read rows containing "End-of-Sale Date" and "End-of-Support Date" (or "Last Date of Support").

Also supports a batch mode to read devices from data/devices.json and
PID aliases from data/pid_alias.json, then scrape End-of-Support using the
alias for each device. Prints navigation whenever a new URL is entered.
"""
from __future__ import annotations
import os, sys, json
import time
from typing import Optional, Dict, Any, List
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

SUPPORT_URL = "https://www.cisco.com/c/en/us/support/index.html"

UA = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

# Paths for batch mode (resolve relative to repo root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DEVICES_JSON = os.path.join(DATA_DIR, 'devices.json')
PID_ALIAS_JSON = os.path.join(DATA_DIR, 'pid_alias.json')

def _build_driver():
	opts = Options()
	opts.add_argument('--headless=new')
	opts.add_argument('--no-sandbox')
	opts.add_argument('--disable-dev-shm-usage')
	opts.add_argument('--disable-gpu')
	opts.add_argument('--window-size=1920,1080')
	opts.add_argument('--log-level=3')
	opts.add_experimental_option('excludeSwitches', ['enable-logging'])
	opts.add_argument(f'--user-agent={UA}')
	driver = webdriver.Chrome(options=opts)
	try:
		driver.execute_cdp_cmd("Network.enable", {})
		driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": UA})
	except Exception:
		pass
	return driver

def _accept_cookies_if_any(driver, wait):
	# Use a short wait for cookies so we don't stall long if not present
	short_wait = WebDriverWait(driver, 5)
	try:
		btn = short_wait.until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
		driver.execute_script("arguments[0].click();", btn)
		time.sleep(0.2)
	except TimeoutException:
		pass

def get_eol_details(alias: str, timeout: int = 45) -> Dict[str, Any] | None:
	if not alias:
		return None
	nav_steps: List[str] = []
	driver = _build_driver()
	wait = WebDriverWait(driver, timeout)
	try:
		print(f"[nav] opening: {SUPPORT_URL}")
		driver.get(SUPPORT_URL)
		nav_steps.append("Opened Support index")
		_accept_cookies_if_any(driver, wait)

		# 2) Click the search button per provided XPath
		x_btn = "/html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/button"
		btn = wait.until(EC.element_to_be_clickable((By.XPATH, x_btn)))
		driver.execute_script("arguments[0].click();", btn)
		nav_steps.append("Clicked search button")

		# 3) Type alias in search input per provided XPath
		x_input = "/html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/div/div/form/div[1]/input"
		search_input = wait.until(EC.element_to_be_clickable((By.XPATH, x_input)))
		search_input.click(); time.sleep(0.2)
		search_input.clear(); time.sleep(0.1)
		search_input.send_keys(alias)
		nav_steps.append(f"Typed alias: {alias}")
		# Wait a moment to allow suggestions to refresh based on the typed alias
		time.sleep(0.6)

		# 4) Wait suggestions UL and click the first suggestion span[2]
		x_suggest_ul = "/html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/div/div/div[1]/ul"
		wait.until(EC.presence_of_element_located((By.XPATH, x_suggest_ul)))
		x_first = "/html/body/div[2]/div/div[3]/div[1]/div[2]/div/section/div/div/div[1]/ul/li[1]/div/ul/li[1]/a/span[2]"
		el = wait.until(EC.element_to_be_clickable((By.XPATH, x_first)))
		text = el.text.strip()
		driver.execute_script("arguments[0].click();", el)
		nav_steps.append(f"Clicked suggestion: {text or '(no text)'}")

		# 5) On next page, wait for details table and extract dates
		prev = SUPPORT_URL
		try:
			wait.until(lambda d: d.current_url != prev)
		except TimeoutException:
			pass
		time.sleep(0.5)
		print(f"[nav] entered: {driver.current_url}")
		nav_steps.append(f"Landed: {driver.title}")

		end_of_sale = None
		end_of_support = None
		status_text = None
		series_release_date = None

		# Prefer the class-based selector as provided in the example
		birth_table_xpath = "//table[contains(@class,'birth-cert-table')]"
		legacy_table_xpath = "/html/body/div[2]/div[2]/div/div/div[1]/table"
		table = None
		try:
			table = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, birth_table_xpath)))
		except TimeoutException:
			try:
				table = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, legacy_table_xpath)))
			except TimeoutException:
				table = None

		if table is None:
			nav_steps.append("Table not found")
		else:
			# Scroll into view in case of lazy-load
			try:
				driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table)
			except Exception:
				pass
			# Directly locate the cells for the specific rows
			x_eos = "//table[contains(@class,'birth-cert-table')]//tr[th[normalize-space()='End-of-Sale Date']]/td"
			x_eosup = (
				"//table[contains(@class,'birth-cert-table')]//tr[th[normalize-space()='End-of-Support Date']]/td"
				" | //table[contains(@class,'birth-cert-table')]//tr[th[normalize-space()='Last Date of Support']]/td"
			)
			def _clean(t: str | None) -> str | None:
				if t is None:
					return None
				return ' '.join(t.split())
			try:
				eos_el = driver.find_element(By.XPATH, x_eos)
				end_of_sale = _clean((eos_el.text or eos_el.get_attribute('textContent') or '').strip())
			except Exception:
				end_of_sale = None
			try:
				eosup_el = driver.find_element(By.XPATH, x_eosup)
				end_of_support = _clean((eosup_el.text or eosup_el.get_attribute('textContent') or '').strip())
			except Exception:
				end_of_support = None

			# Also capture Status and Series Release Date
			x_status = "//table[contains(@class,'birth-cert-table')]//tr[th[normalize-space()='Status']]/td"
			x_series = "//table[contains(@class,'birth-cert-table')]//tr[th[normalize-space()='Series Release Date']]/td"
			try:
				st_el = driver.find_element(By.XPATH, x_status)
				# Remove anchor texts like "EOL Details" before reading text
				try:
					clean_txt = driver.execute_script(
						"var td=arguments[0].cloneNode(true); td.querySelectorAll('a').forEach(a=>a.remove()); return td.textContent;",
						st_el
					) or ''
				except Exception:
					clean_txt = (st_el.text or st_el.get_attribute('textContent') or '')
				status_text = _clean(clean_txt.replace('EOL Details', '').strip())
			except Exception:
				status_text = None
			try:
				sr_el = driver.find_element(By.XPATH, x_series)
				series_release_date = _clean((sr_el.text or sr_el.get_attribute('textContent') or '').strip())
			except Exception:
				series_release_date = None

		return {
			'end_of_sale_date': end_of_sale,
			'end_of_support_date': end_of_support,
			'status': status_text,
			'series_release_date': series_release_date,
			'nav_title': driver.title,
			'nav_url': driver.current_url,
			'nav_steps': nav_steps,
		}
	except Exception:
		return None
	finally:
		driver.quit()

def _load_json(path: str, default):
	try:
		with open(path, 'r', encoding='utf-8') as f:
			return json.load(f)
	except Exception:
		return default

def _save_json(path: str, obj) -> None:
	with open(path, 'w', encoding='utf-8') as f:
		json.dump(obj, f, indent=2, ensure_ascii=False)

def batch_scrape_devices(write: bool = False, only_missing: bool = False, limit: int | None = None, delay: float = 0.0) -> int:
	"""Read devices.json and pid_alias.json, scrape End-of-Support per device using alias.

	Args:
		write: If True, write eol_details back into devices.json
		only_missing: If True, only scrape devices missing end_of_support_date
		limit: Max number of devices to process
		delay: Sleep between devices (seconds)

	Returns number of processed devices.
	"""
	devices = _load_json(DEVICES_JSON, {})
	if not isinstance(devices, dict) or not devices:
		print(f"[batch] [!] {DEVICES_JSON} missing or empty", flush=True)
		return 0
	aliases = _load_json(PID_ALIAS_JSON, {})
	print(f"[batch] devices={len(devices)} aliases={len(aliases)}", flush=True)
	count = 0
	for host, rec in devices.items():
		model = (rec.get('model') or '').strip()
		alias = (aliases.get(model) or model).strip()
		if only_missing:
			cur = (rec.get('eol_details') or {}).get('end_of_support_date')
			if cur:
				continue
		print(f"[batch] host={host} model='{model or '-'}' alias='{alias or '-'}'", flush=True)
		try:
			res = get_eol_details(alias)
		except Exception as e:
			print(f"[batch]   error: {e}", flush=True)
			res = None
		if res:
			print(f"[batch]   Status: {res.get('status')} | Series Release Date: {res.get('series_release_date')}", flush=True)
			print(f"[batch]   End-of-Sale: {res.get('end_of_sale_date')} | End-of-Support: {res.get('end_of_support_date')}", flush=True)
			print(f"[batch]   Page: {res.get('nav_title')} | URL: {res.get('nav_url')}", flush=True)
			if write:
				rec.setdefault('eol_details', {})
				rec['eol_details'].update({
					'end_of_sale_date': res.get('end_of_sale_date'),
					'end_of_support_date': res.get('end_of_support_date'),
					'status': res.get('status'),
					'series_release_date': res.get('series_release_date'),
					'nav_title': res.get('nav_title'),
					'nav_url': res.get('nav_url'),
					'nav_steps': res.get('nav_steps'),
					'alias_used': alias or None,
				})
		else:
			print("[batch]   details not found", flush=True)
		count += 1
		if limit and count >= limit:
			break
		if delay:
			time.sleep(delay)
	if write:
		_save_json(DEVICES_JSON, devices)
		print(f"[batch] [✓] wrote updates to {DEVICES_JSON}", flush=True)
	return count

if __name__ == '__main__':
	import argparse
	parser = argparse.ArgumentParser(description='Cisco EoL/EoSupport scraper')
	parser.add_argument('--single', help='Scrape a single alias or model string')
	parser.add_argument('--batch', action='store_true', help='Batch scrape using data/devices.json and data/pid_alias.json')
	parser.add_argument('--write', action='store_true', help='When used with --batch, write results back into devices.json')
	parser.add_argument('--only-missing', action='store_true', help='When used with --batch, only process devices missing end_of_support_date')
	parser.add_argument('--limit', type=int, default=None, help='Limit number of devices to process in batch')
	parser.add_argument('--delay', type=float, default=0.0, help='Delay between devices in seconds')
	args = parser.parse_args()

	if args.single:
		print(get_eol_details(args.single))
	elif args.batch:
		batch_scrape_devices(write=args.write, only_missing=args.only_missing, limit=args.limit, delay=args.delay)
	else:
		parser.print_help()
