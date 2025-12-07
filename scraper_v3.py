#!/usr/bin/env python3
"""
Google Maps Website Scraper
Extracts emails and Nepali phone numbers from business websites.
"""
import argparse
import os
import json
import csv
import re
import time
from typing import Optional
from datetime import datetime
from pprint import pprint
from typing import List, Set, Dict
import urllib.parse
from urllib.parse import urlparse
import requests
from concurrent.futures import ThreadPoolExecutor
from colorama import init, Fore, Style
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import urllib3
import warnings
import pdb

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
# disable Insecure Connection Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
init()  # Initialize colorama

DEBUGGER=False

# ----------------------------------------------------------------------
# 1. List of *all* valid area codes (exactly as they appear in the page)
# ----------------------------------------------------------------------
_VALID_AREA_CODES = {
    # 2-digit
    "01", "10", "11", "19", "21", "23", "24", "25", "26", "27", "29",
    "31", "33", "35", "36", "37", "38", "41", "44", "46", "47", "48", "49",
    "51", "53", "55", "56", "57", "61", "63", "64", "65", "66", "67", "68",
    "69", "71", "75", "76", "77", "78", "79", "81", "82", "83", "84", "86",
    "87", "88", "89", "91", "92", "93", "94", "95", "96", "97", "99",
    # 3-digit (the “0xx” family)
    "010", "011", "019", "021", "023", "024", "025", "026", "027", "029",
    "031", "033", "035", "036", "037", "038", "041", "044", "046", "047",
    "048", "049", "051", "053", "055", "056", "057", "061", "063", "064",
    "065", "066", "067", "068", "069", "071", "075", "076", "077", "078",
    "079", "081", "082", "083", "084", "086", "087", "088", "089", "091",
    "092", "093", "094", "095", "096", "097", "099",
}

# Build a single alternation pattern – sorted longest-first so that 010 matches before 01
_AREA_CODE_PATTERN = "|".join(sorted(_VALID_AREA_CODES, key=len, reverse=True))


# ==============================
# Configuration & Constants
# ==============================
class Patterns:
    EMAIL = re.compile(
        r"[a-zA-Z0-9._%+-]+\s*(?:@|\[at\]|\(at\))\s*[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    )
    EMAIL_STRICT = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE
    )
    # PHONE_NP = re.compile(r"\b(?:\+?977|01)[\d\-\.\s]{5,}\d\b")
    PHONE_NP = re.compile(
        r"""
        \b(?:\+?977[-\.\s]?)? # Optional +977
        (?:0[-\.\s]?)? # Optional leading 0
        ( # Area code OR mobile prefix
            1[-\.\s]?\d{7} # Kathmandu: 1-4261234 → 014261234
            | [2-9]\d[-\.\s]?\d{5} # Other landlines: 61-531234 → 061531234
            | 9[78]\d[-\.\s]?\d{7} # Mobiles: 9841 234 567
        )\b
        """,
        re.VERBOSE | re.IGNORECASE,
    )
    NEW_PHONE_NP = re.compile(
        r"""
        \b
        (?:\+?977[-\.\s]?)? # +977
        (?:0[-\.\s]?)? # leading 0
        (
            1[-\.\s]?\d{7} # 01-xxxxxxx
            | [2-9]\d[-\.\s]?\d{5} # 61-xxxxx
            | 9[78]\d(?:[-\.\s]+\d{1,4}){2,7} # ← MOBILE: any separators
        )
        \b
        """,
        re.VERBOSE | re.IGNORECASE,
    )
    NEW_NEW_PHONE_NP = re.compile(
        r"""
        \b
        (?:\+?977[-\.\s]?)??   # Optional +977
        (?:0[-\.\s]?)?         # Optional leading 0
        (
            # Kathmandu: 1 + exactly 7 digits (any separators)
            1[-\.\s]?(?:\d[-\.\s]*){7}
    
            # Other landlines: 2-9X + exactly 5 digits
            | [2-9]\d[-\.\s]?(?:\d[-\.\s]*){5}
    
            # Mobiles: 97x/98x + exactly 7 digits
            | 9[78]\d[-\.\s]?(?:\d[-\.\s]*){7}
        )
        \b
        """,
        re.VERBOSE | re.IGNORECASE,
    )
    # THE following regex matches 3-digit area codes
    # OTHER_PHONE_NP = re.compile(
    #     r""" 
    #     \b
    #     (?:\+977[-\.\s]?)?     # +977
    #     (?:0[-\.\s]?)?         # leading 0
    #     (
    #         # Kathmandu: 1 + 7 digits (total 8)
    #         1[-\.\s]?(?:\d[-\.\s]*){7}
    # 
    #         # Other landlines: 2-3 digit area code + digits to make total 8
    #         | [2-9]\d{1,2}[-\.\s]?(?:\d[-\.\s]*){5,6}
    #         #   ↑↑↑           ↑↑↑
    #         #   2–3 digits    5–6 digits → total 7–9 chars → but with area code → 8 digits
    # 
    #         # Wait — better way:
    #         # Just match 8 digits total, starting with valid area code
    #     )
    #     \b
    # """,
    #     re.VERBOSE | re.IGNORECASE,
    # )
    OTHER_PHONE_NP = re.compile(
        fr"""
        \b
        (?:\+977[-\.\s]?)?      # optional country code
        (?:0[-\.\s]?)?          # optional leading 0
        (
            (?P<area>{_AREA_CODE_PATTERN})  # valid area code
            [-\.\s]?            # separator
            \d(?:[-\.\s]?\d){{5,6}}  # 5–6 more digits (total 8 digits)
        )
        \b
        """,
        re.VERBOSE | re.IGNORECASE
    )

    ABOUT_PAGE = re.compile(
        r"(?:https?://)?(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        r"(?:/[^\s]*?)?(?:about|contact|reach-us|team|info)[^\s<>\"]*",
        re.IGNORECASE,
    )


REACT_INDICATORS = [
    'id="root"',
    "id='root'",
    "[data-reactroot]",
    "[data-reactid]",
    "[data-react-root]",
    "react",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "PostmanRuntime/7.49.0",
    "curl/8.0.1",
]
HEADERS = {
    "User-Agent": USER_AGENTS[0],
    "Accept": "*/*",
    "Connection": "keep-alive",
}
ALT_HEADERS = {
    "User-Agent": USER_AGENTS[4],
    "Accept": "*/*",
    # "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
EDU_PATHS = [
    # Segregations
    "/college",
    "/school",
    "/hss",
    # Contact
    "/contact",
    "/contact-us",
    "/contact/",
    "/reach-us",
    "/get-in-touch",
    # Uncomment the following lines if needed (don't slow down the process tho :P)
    # # About
    # "/about", "/about-us", "/about/", "/who-we-are", "/mission-vision",
    # # Admissions
    # "/admissions", "/admission", "/apply", "/apply-now", "/enroll",
    # # Academics
    # "/academics", "/programs", "/courses", "/departments", "/faculty",
    # # Campus
    # "/student-life", "/campus-life", "/housing", "/events",
    # # Legal
    # "/privacy-policy", "/sitemap", "/sitemap.xml",
]
CONTACT_KEYWORDS = [
    "contact",
    "email",
    "phone",
    "call",
    "mobile",
    "landline",
    "support",
    "reach us",
    "get in touch",
    "address",
    "location",
]


# ==============================
# Utility Functions
# ==============================
def log_info(msg: str):
    print(Fore.CYAN + f"[INFO] {msg}" + Style.RESET_ALL)


def log_debug(msg: str):
    print(Fore.YELLOW + f"[DEBUG] {msg}" + Style.RESET_ALL)


def log_error(msg: str):
    print(Fore.RED + f"[ERROR] {msg}" + Style.RESET_ALL)


# def normalize_phone(phone: str) -> Optional[str]:
# digits = re.sub(r"\D", "", phone)
# if 9 <= len(digits) <= 15 and digits[0] in "09456":
# return digits
# return None
def normalize_phone(phone: str) -> Optional[str]:
    """Returns clean 10-digit string or None"""
    digits = re.sub(r"\D", "", phone)  # Kill spaces/dashes/dots

    # +977 prefix
    if digits.startswith("977"):
        digits = digits[3:]

    # Leading 0
    if digits.startswith("0"):
        digits = digits[1:]

    # Must be exactly 10 digits
    if 7 > len(digits) > 15:
        return None

    first = digits[0]
    if first == "1":  # Kathmandu landline
        return "01" + digits[1:]
    if "2" <= first <= "9":  # Other landlines
        return "0" + digits[:2] + digits[2:]
    if first in "89":  # NTC/Ncell mobiles
        return "9" + digits[1:] if first == "9" else digits

    return None


# ==============================
# Core Scraper Module
# ==============================
class ContactScraper:
    def __init__(self, url: str, use_headless: bool = True):
        self.url = url.rstrip("/")
        self.content = ""
        self.is_react = False
        self.has_sitemap = False
        self.captcha_detected = False
        self.emails: Set[str] = set()
        self.phones: Set[str] = set()
        self.about_pages: List[str] = []
        self.options = Options()
        self.allow_redirects = True
        self.seen_links = []
        self.html_content = None
        self.root_domain = self._get_root_domain(self.url)
        if use_headless:
            self.options.add_argument("--headless")

    def _get_root_domain(self, url: str) -> str:
        """Extract the root domain (e.g., example.edu.np) from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # For .edu.np, include the college name as root
        parts = domain.split(".")
        if len(parts) >= 3 and parts[-2] == "edu" and parts[-1] == "np":
            return ".".join(parts[-3:])
        # Fallback for other domains (e.g., example.com)
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return domain

    def fetch_page(self) -> bool:
        try:
            response = requests.get(
                self.url,
                headers=HEADERS,
                timeout=5,
                allow_redirects=self.allow_redirects,
                verify=False,
            )
            if response.status_code // 100 in [4, 5]:
                headers = ALT_HEADERS
                response = requests.get(
                    self.url,
                    headers=headers,
                    timeout=5,
                    allow_redirects=self.allow_redirects,
                    verify=False,
                )
            if response.status_code != 200:
                log_error(f"{self.url} returned {response.status_code}")
                # return False
            self.content = response.text
            self.is_react = any(ind in self.content for ind in REACT_INDICATORS)
            self.is_vue = self.is_vue_page(self.content)
            if self.is_vue:
                log_info("Vue.js detected → will use Selenium")
                self.is_react = False  # Vue wins over generic React checks
            else:
                self.is_react = any(ind in self.content for ind in REACT_INDICATORS)
            # self.captcha_detected = "captcha" in self.content.lower()
            if self.captcha_detected:
                log_error("CAPTCHA detected. Skipping content scraping.")
                return False
            self._check_sitemap()
            return True
        except requests.RequestException as e:
            log_error(f"Failed to fetch {self.url}: {e}")
            return False

    def fetch_common_paths(self):
        for edu_path in EDU_PATHS:
            try:
                response = requests.get(
                    f"{self.url}{edu_path}",
                    allow_redirects=self.allow_redirects,
                    verify=False,
                    timeout=3,
                )
                log_info(f"Checking {self.url}{edu_path}")
                if response.status_code != 200:
                    log_error(f"{self.url} returned {response.status_code}")
                    continue
                self.extract_from_text(response.text)
                self.handle_hyperlinks(response.text)
            except requests.RequestException:
                log_error(f"Failed to fetch {self.url}: e")

    def _check_sitemap(self):
        sitemap_urls = [f"{self.url}/sitemap.xml", f"{self.url}/sitemap"]
        try:
            for sm_url in sitemap_urls:
                res = requests.get(
                    sm_url,
                    headers=HEADERS,
                    timeout=5,
                    allow_redirects=self.allow_redirects,
                    verify=False,
                )
                if res.status_code // 100 in [4, 5]:
                    res = requests.get(
                        self.url,
                        headers=ALT_HEADERS,
                        timeout=5,
                        allow_redirects=self.allow_redirects,
                        verify=False,
                    )
                if res.status_code // 100 == 2:
                    self.has_sitemap = True
                    ###
                    for url in set(Patterns.ABOUT_PAGE.findall(res.text)):
                        if self._is_same_root_domain(url):
                            pprint(url)
                            self.about_pages.append(url)
                    self.about_pages = list(set(self.about_pages))
                    # self.about_pages = list(set(Patterns.ABOUT_PAGE.findall(res.text)))
                    log_debug(
                        f"Found {len(self.about_pages)} about/contact pages in sitemap"
                    )
        except requests.RequestException:
            pass

    def _is_same_root_domain(self, url: str) -> bool:
        """Check if the given URL has the same root domain as self.url."""
        if not url.startswith(("http://", "https://")):
            # Relative URL: assume same domain
            return True
        target_root = self._get_root_domain(url)
        return target_root == self.root_domain

    def extract_from_html(self, html: str):
        parser = BeautifulSoup(html, "html.parser")
        for email in Patterns.EMAIL.findall(html):
            self.emails.add(email.lower())
        # Phones
        # for match in Patterns.PHONE_NP.finditer(html):
        #     if norm := normalize_phone(match.group()):
        #         self.phones.add(norm)

    def extract_from_contact_sections(self, html: str) -> set:
        soup = BeautifulSoup(html, "html.parser")
        phones = set()
        # 1. Find <div>, <section>, <p> with contact keywords
        for tag in soup.find_all(["div", "section", "p", "li", "span", "footer", "a"]):
            text = tag.get_text().lower()
            if any(kw in text for kw in CONTACT_KEYWORDS):
                # Extract phones ONLY from this tag
                for match in Patterns.PHONE_NP.finditer(tag.get_text()):
                    norm = normalize_phone(match.group())
                    if norm:
                        self.phones.add(norm)

                for match in Patterns.NEW_PHONE_NP.finditer(tag.get_text()):
                    norm = normalize_phone(match.group())
                    if norm:
                        self.phones.add(norm)

                for match in Patterns.NEW_NEW_PHONE_NP.finditer(tag.get_text()):
                    norm = normalize_phone(match.group())
                    if norm:
                        self.phones.add(norm)

                for match in Patterns.OTHER_PHONE_NP.finditer(tag.get_text()):
                    norm = normalize_phone(match.group())
                    if norm:
                        self.phones.add(norm)

                for match in Patterns.EMAIL.finditer(tag.get_text()):
                    norm = match.group()
                    self.emails.add(norm)

                for match in Patterns.EMAIL_STRICT.finditer(tag.get_text()):
                    norm = match.group()
                    self.emails.add(norm)

        # 2. Bonus: Footer is gold
        footer = soup.find("footer")
        if footer:
            for match in Patterns.PHONE_NP.finditer(footer.get_text()):
                norm = normalize_phone(match.group())
                if norm:
                    self.phones.add(norm)
            for match in Patterns.NEW_PHONE_NP.finditer(footer.get_text()):
                norm = normalize_phone(match.group())
                if norm:
                    self.phones.add(norm)
            for match in Patterns.NEW_NEW_PHONE_NP.finditer(footer.get_text()):
                norm = normalize_phone(match.group())
                if norm:
                    self.phones.add(norm)
            for match in Patterns.OTHER_PHONE_NP.finditer(footer.get_text()):
                norm = normalize_phone(match.group())
                if norm:
                    self.phones.add(norm)
            for match in Patterns.EMAIL.finditer(footer.get_text()):
                norm = match.group()
                self.emails.add(norm)
            for match in Patterns.EMAIL_STRICT.finditer(footer.get_text()):
                norm = match.group()
                self.emails.add(norm)

        if DEBUGGER == True:
            print(self.emails)
            print(self.phones)
            pdb.set_trace()

        return phones

    def extract_from_text(self, text: str):
        # Emails
        for email in Patterns.EMAIL.findall(text):
            self.emails.add(email.lower())
        # Extract mailto: links
        soup = BeautifulSoup(text, "html.parser")
        # 1. Find <div>, <section>, <p> with contact keywords
        links = soup("a")
        if links is not None:
            for link in links:
                if "href" in list(link.attrs.keys()):
                    href = str(link["href"])
                    if href.startswith("mailto:"):
                        email = href[7:].split("?")[0]
                        if Patterns.EMAIL.match(email):
                            self.emails.add(email.lower())
                    elif href.startswith("tel:"):
                        phone = href[4:]
                        if bool(Patterns.PHONE_NP.search(phone.strip())):
                            self.phones.add(phone)
                        elif bool(Patterns.NEW_PHONE_NP.search(phone.strip())):
                            self.phones.add(phone)
                        elif bool(Patterns.NEW_NEW_PHONE_NP.search(phone.strip())):
                            self.phones.add(phone)
                        elif bool(Patterns.OTHER_PHONE_NP.search(phone.strip())):
                            self.phones.add(phone)

        # Phones
        # for match in Patterns.PHONE_NP.finditer(text):
        # if norm := normalize_phone(match.group()):
        # self.phones.add(norm)
        smart_phones = self.extract_from_contact_sections(text)
        self.phones.update(smart_phones)

    def scrape_static(self):
        if not self.content:
            return
        self.extract_from_text(self.content)
        self.handle_hyperlinks(self.content)
        if self.has_sitemap:
            for page in self.about_pages:  # limit to avoid spam
                try:
                    res = requests.get(
                        page,
                        headers=HEADERS,
                        timeout=5,
                        allow_redirects=self.allow_redirects,
                        verify=False,
                    )
                    if res.status_code == 200:
                        self.extract_from_text(res.text)
                        # self.phones.update(self.extract_from_contact_sections(res.text))
                except:
                    continue

    def scrape_dynamic(self, url, forced=False):
        if forced:
            driver = None
            try:
                driver = webdriver.Firefox(options=self.options)
                driver.get(url)
                time.sleep(5)
                # body_text = driver.find_element(By.TAG_NAME, "body").text
                html_content = driver.page_source
                self.extract_from_text(html_content)
                self.handle_hyperlinks(html_content)
                # Extract mailto: links
                links = driver.find_elements(By.TAG_NAME, "a")
                for link in links:
                    href = link.get_attribute("href") or ""
                    if href.startswith("mailto:"):
                        email = href[7:].split("?")[0]
                        if Patterns.EMAIL.match(email):
                            self.emails.add(email.lower())
            except Exception as e:
                log_error(f"Selenium failed for {url}: {e}")
            finally:
                if driver:
                    driver.quit()
        if not (self.is_vue or self.is_react):
            return
        driver = None
        try:
            driver = webdriver.Firefox(options=self.options)
            driver.get(url)
            time.sleep(5)
            # body_text = driver.find_element(By.TAG_NAME, "body").text
            html_content = driver.page_source
            self.extract_from_text(html_content)
            self.handle_hyperlinks(html_content)
            # Extract mailto: links
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href") or ""
                if href.startswith("mailto:"):
                    email = href[7:].split("?")[0]
                    if Patterns.EMAIL.match(email):
                        self.emails.add(email.lower())
        except Exception as e:
            log_error(f"Selenium failed for {url}: {e}")
        finally:
            if driver:
                driver.quit()

    def handle_hyperlinks(self, html: str):
        """
        Hyperlinks like "Contact Us", "About Us" etc. may exist,
        despite the site not having sitemap.xml
        """
        parser = BeautifulSoup(html, "html.parser")
        links = parser("a")
        if links is not None:
            for link in links:
                if "href" in list(link.attrs.keys()):
                    href = str(link["href"])
                    if href not in self.seen_links and (
                        href.startswith("https") or href.startswith("http")
                    ):
                        if self._is_same_root_domain(href):
                            self.seen_links.append(href)
                            keywords = ["about", "contact"]
                            for k in keywords:
                                if k in href.lower():
                                    log_debug(f"Found {k} Hyperlink at {href}")
                                    res = requests.get(
                                        f"{href}",
                                        allow_redirects=self.allow_redirects,
                                        verify=False,
                                        timeout=5,
                                    )
                                    if res.status_code == 200:
                                        self.extract_from_text(res.text)
                                    else:
                                        log_error(f"{href} returned {res.status_code}")

    def is_vue_page(self, html: str) -> bool:
        """Return True if Vue 2 or Vue 3 is detected"""
        checks = [
            # Vue 2 fingerprints
            r"__vue__",
            r"data-v-",
            r"_v-",
            r"vue\.min\.js",
            r"vue\.global\.prod\.js",
            # Vue 3 fingerprints
            r"__vue_app__",
            r"__VUE__",
            r"@vue/runtime-core",
            r"runtime-dom",
            # Common
            r"Vue\.config",
            r"vue-devtools",
            r'id="app"',
        ]
        return any(re.search(pattern, html, re.IGNORECASE) for pattern in checks)

    def clean_emails(self):
        gibberish = ["example", "yoursite", ".png", ".svg", ".jpg", ".jpeg", ".gif"]
        for email in self.emails.copy():
            for g in gibberish:
                if g in email:
                    self.emails.remove(email)

    def debug_phone_regex(self):
        for phone in self.phones:
            print(phone)
            # print(f"NEW_NEW_PHONE regex:\t\t{bool(Patterns.NEW_NEW_PHONE_NP.search(phone))}")
            # print(f"NEW_PHONE regex:\t\t{bool(Patterns.NEW_PHONE_NP.search(phone))}")
            # print(f"PHONE regex:\t\t{bool(Patterns.PHONE_NP.search(phone))}")
            print(
                f"OTHER_PHONE regex:\t\t{bool(Patterns.OTHER_PHONE_NP.search(phone))}"
            )

    def run(self) -> Dict:
        log_info(f"Scraping: {self.url}")
        if not self.fetch_page():
            return {"website": self.url, "emails": [], "numbers": []}
        self.scrape_static()
        if self.is_react or self.is_vue:
            self.scrape_dynamic(self.url)
        self.fetch_common_paths()
        if len(self.phones) == 0 or len(self.emails) == 0:
            log_info(
                "Static Scraping didn't return proper results\n\tTrying Dynamic Fetching"
            )
            self.scrape_dynamic(self.url, forced=True)

        self.clean_emails()
        self.debug_phone_regex()

        return {
            "website": self.url,
            "emails": sorted(self.emails) or "Not found",
            "numbers": sorted(self.phones) or "Not found",
        }


# ==============================
# Google Maps URL Extractor
# ==============================
class MapsScraper:
    def __init__(self, keywords: str, limit: int = 4, inpfile=None):
        self.keywords = keywords
        self.limit = limit
        self.search_url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(keywords)}?hl=en"
        self.websites: Set[str] = set()
        self.inpfile = inpfile
        if self.inpfile:
            try:
                with open(self.inpfile, "r") as f:
                    urls = f.readlines()
                    self.limit = len(urls)
                    self.websites.update(urls)
            except FileNotFoundError:
                log_error(f"{self.inpfile} not found")

    def run(self) -> List[str]:
        driver = None
        try:
            options = Options()
            options.add_argument("--headless")
            driver = webdriver.Firefox(options=options)
            driver.get(self.search_url)
            driver.maximize_window()
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//a[@data-value='Website']"))
            )
            feed = driver.find_element(By.XPATH, '//div[@role="feed"]')
            last_height = driver.execute_script("return arguments[0].scrollTop", feed)
            while len(self.websites) < self.limit:
                elements = driver.find_elements(By.XPATH, "//a[@data-value='Website']")
                for el in elements:
                    url = el.get_attribute("href")
                    if url and url.startswith("http"):
                        self.websites.add(url)
                    if len(self.websites) >= self.limit:
                        break
                # Scroll
                driver.execute_script("arguments[0].scrollTop += 600", feed)
                time.sleep(3)
                new_height = driver.execute_script(
                    "return arguments[0].scrollTop", feed
                )
                if new_height == last_height:
                    log_info("No more results. End of scroll.")
                    break
                last_height = new_height
            log_info(f"Collected {len(self.websites)} websites from Maps.")
            return list(self.websites)[: self.limit]
        except TimeoutException:
            log_error("Website links not found in Google Maps.")
            return []
        except Exception as e:
            log_error(f"Maps scraping failed: {e}")
            return []
        finally:
            if driver:
                driver.quit()


# ==============================
# CLI & Main Runner
# ==============================


# import os
# import re
# import json
# import csv
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
# 
# # ← Add these imports if missing
# from pprint import pprint
# import argparse

def get_output_dir() -> Path:
    """Always return a writable directory — works on Windows, Linux, macOS, even frozen exe"""
    return Path.cwd() / "FetchedData"   # or use Path(__file__).parent if not frozen

def save_results(data: List[Dict], filename: str):
    output_dir = get_output_dir()
    json_dir = output_dir / "json_data"
    csv_dir = output_dir / "csv_data"

    json_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(filename).stem  # strip .txt, .json etc.

    try:
        json_path = json_dir / f"{base_name}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log_info(f"Results saved to {json_path}")

        csv_path = csv_dir / f"{base_name}.csv"
        if data:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            log_info(f"Results saved to {csv_path}")
    except Exception as e:
        log_error(f"Failed to save results: {e}")


# def save_results(data: List[Dict], filename: str):
#     dirs_to_create = ["json_data", "csv_data"]
#     for folder in dirs_to_create:
#         if not os.path.exists(folder):
#             os.makedirs(folder)
#     try:
#         with open(
#             os.path.join("json_data", f"{filename}.json"), "w", encoding="utf-8"
#         ) as f:
#             json.dump(data, f, indent=2, ensure_ascii=False)
#         log_info(f"Results saved to ./json_data/{filename}.json")
#         with open(
#             os.path.join("csv_data", f"{filename}.csv"), "w", encoding="utf-8"
#         ) as f:
#             if len(data) > 0:
#                 w = csv.DictWriter(f, data[0].keys())
#                 w.writeheader()
#                 for row in data:
#                     w.writerow(row)
#                 log_info(f"Results saved to ./csv_data/{filename}.csv")
#     except Exception as e:
#         log_error(f"Failed to save file: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape contact info from websites or Google Maps",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Example: python scraper.py -k 'restaurants in Kathmandu' -n 6 -l",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-u", "--url", help="Single website URL to scrape")
    group.add_argument("-k", "--keywords", help="Keywords to search in Google Maps")
    group.add_argument(
        "-f",
        "--file",
        help="Scrapes websites in the file containing URLs in each new line",
    )
    parser.add_argument(
        "-n",
        "--number",
        type=int,
        default=4,
        help="Number of sites to scrape (default: 4)",
    )
    parser.add_argument(
        "-l", "--log", action="store_true", help="Save output to JSON file"
    )
    args = parser.parse_args()
    results = []
    if args.url:
        scraper = ContactScraper(args.url)
        result = scraper.run()
        results.append(result)
        pprint(result)
    elif args.keywords:
        maps = MapsScraper(args.keywords, limit=args.number)
        websites = maps.run()
        if not websites:
            log_error("No websites found.")
            return
        results = []
        MAX_WORKERS = 13  # Tune: 5–15 safe for most home IPs

        def subscraper(site: str):
            try:
                scraper = ContactScraper(site)
                result = scraper.run()
                results.append(result)
                pprint(result)
                # time.sleep(0.8) # Be nice to servers
            except Exception as e:
                log_error(f"Thread failed on {site}: {e}")

        # THREAD POOL (fast, clean, auto-join)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(subscraper, websites)
        # SAVE AFTER ALL DONE
        if args.log and results:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            safe_kw = re.sub(r"[^\w\-_]", "_", args.keywords)
            filename = f"contacts_[{safe_kw}]_{timestamp}.json"
            save_results(results, filename)
    elif args.file:
        maps = MapsScraper("", inpfile=args.file)
        websites = maps.websites
        if not websites:
            log_error("No websites found.")
            return
        results = []
        MAX_WORKERS = 12  # Tune: 5–15 safe for most home IPs

        def subscraper(site: str):
            site = site.strip()
            try:
                if site:
                    scraper = ContactScraper(site)
                    result = scraper.run()
                    results.append(result)
                    pprint(result)
                # time.sleep(0.8) # Be nice to servers
            except Exception as e:
                log_error(f"Thread failed on {site}: {e}")

        # THREAD POOL (fast, clean, auto-join)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(subscraper, websites)
        # SAVE AFTER ALL DONE
        if args.log and results:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            safe_kw = re.sub(r"[^\w\-_]", "_", args.file)
            filename = f"contacts_[{safe_kw}]_{timestamp}.json"
            save_results(results, filename)

    if args.log and results and args.url:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_part = args.keywords.replace(" ", "_") if args.keywords else "single"
        filename = f"contacts_[{keyword_part}]_{timestamp}"
        save_results(results, filename)


if __name__ == "__main__":
    main()
