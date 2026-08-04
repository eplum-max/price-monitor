#!/usr/bin/env python3
"""
Vuori 50%+ Discount & Marine Layer Last Call Monitor
Runs weekly on Sunday at 6 PM Pacific time
Finds items at 50%+ discount (Vuori) / any discount (Marine Layer), M/L sizes only
"""

import requests
import json
import smtplib
import os
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from typing import List, Optional

# Configuration
EMAIL_RECIPIENT = "eric.slivka@gmail.com"
DISCOUNT_THRESHOLD = 50.0  # Vuori only - 50% or more
VALID_SIZES = ['M', 'L', 'M/L']  # exact-match tokens, not substrings (avoids matching "XL")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
}


class DiscountItem:
    def __init__(self, name: str, original_price: float, sale_price: float,
                 discount_percent: float, url: str, available_sizes: List[str], source: str):
        self.name = name
        self.original_price = original_price
        self.sale_price = sale_price
        self.discount_percent = discount_percent
        self.url = url
        self.available_sizes = available_sizes
        self.source = source

    def to_html(self) -> str:
        sizes_str = ", ".join(self.available_sizes)
        return f"""
        <tr style="border-bottom: 1px solid #ddd;">
            <td style="padding: 12px; text-align: left;">
                <a href="{self.url}" style="color: #0066cc; text-decoration: none; font-weight: 500;">
                    {self.name}
                </a>
            </td>
            <td style="padding: 12px; text-align: center;">${self.sale_price:.2f}</td>
            <td style="padding: 12px; text-align: center;">${self.original_price:.2f}</td>
            <td style="padding: 12px; text-align: center; font-weight: bold; color: #d9534f;">
                {self.discount_percent:.0f}% OFF
            </td>
            <td style="padding: 12px; text-align: center; font-size: 12px;">{sizes_str}</td>
            <td style="padding: 12px; text-align: center;">{self.source}</td>
        </tr>
        """


# =============================================================================
# VUORI MONITOR
# =============================================================================
class VuoriMonitor:
    """
    Monitor Vuori sale section for 50%+ discounts.

    IMPORTANT: vuoriclothing.com/collections/sale renders its product grid
    entirely client-side via a JS search widget (Algolia/Findify) - a plain
    HTTP fetch of that page returns ZERO products (verified). So this class
    tries the underlying Shopify products.json data endpoint FIRST, which
    returns raw structured JSON independent of any JS rendering. If that
    endpoint is unavailable, it falls back to HTML scraping as a best-effort
    (which will likely find nothing, but won't silently look successful).
    """

    def __init__(self):
        self.base_url = "https://vuoriclothing.com"
        self.sale_url = f"{self.base_url}/collections/sale"
        self.collection_handles_to_try = ["sale", "sale-1", "mens-sale"]
        self.items = []
        self.skip_reasons = {}

    def fetch_sale_items(self) -> List[DiscountItem]:
        json_items = self._fetch_via_json()
        if json_items:
            self.items = json_items
            return self.items

        print("JSON endpoint approach found nothing. Falling back to HTML scrape "
              "(expected to be unreliable since this page is JS-rendered).")
        html_items = self._fetch_via_html_fallback()
        self.items = html_items
        return self.items

    def _fetch_via_json(self) -> List[DiscountItem]:
        """Try Shopify's public products.json endpoint for each candidate collection handle."""
        found: List[DiscountItem] = []
        seen_ids = set()

        for handle in self.collection_handles_to_try:
            url = f"{self.base_url}/collections/{handle}/products.json?limit=250"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                print(f"JSON endpoint check [{handle}]: HTTP {resp.status_code}")
                if resp.status_code != 200:
                    continue

                data = resp.json()
                products = data.get('products', [])
                print(f"JSON endpoint [{handle}]: {len(products)} products returned")

                for product in products:
                    if product.get('id') in seen_ids:
                        continue

                    item = self._parse_json_product(product)
                    if item:
                        seen_ids.add(product.get('id'))
                        found.append(item)

            except (requests.exceptions.RequestException, ValueError) as e:
                print(f"JSON endpoint [{handle}] failed: {e}")
                continue

        print(f"Vuori JSON approach total: {len(found)} items matched (50%+ off, M/L available)")
        return found

    def _parse_json_product(self, product: dict) -> Optional[DiscountItem]:
        handle = product.get('handle', '')
        title = product.get('title', 'Unknown item')
        variants = product.get('variants', [])
        options = product.get('options', [])

        if not variants:
            self._log_skip("no_variants")
            return None

        # Find which option index corresponds to "Size"
        size_option_index = None
        for i, opt in enumerate(options):
            if opt.get('name', '').lower() == 'size':
                size_option_index = i  # 0-based -> optionN is 1-based
                break

        # Determine price / compare_at_price from first variant that has both
        original_price = None
        sale_price = None
        for v in variants:
            price = v.get('price')
            compare_at = v.get('compare_at_price')
            if price is not None and compare_at is not None:
                try:
                    price_f = float(price)
                    compare_f = float(compare_at)
                    if compare_f > price_f:
                        original_price = compare_f
                        sale_price = price_f
                        break
                except (TypeError, ValueError):
                    continue

        if original_price is None or sale_price is None:
            self._log_skip("no_discount_data")
            return None

        discount_percent = ((original_price - sale_price) / original_price) * 100
        if discount_percent < DISCOUNT_THRESHOLD:
            self._log_skip("below_threshold")
            return None

        # Collect available (in-stock) sizes
        available_sizes = []
        for v in variants:
            if not v.get('available', False):
                continue
            size_val = None
            if size_option_index is not None:
                size_val = v.get(f'option{size_option_index + 1}')
            else:
                # Single-option products often just use option1 for size
                size_val = v.get('option1')
            if size_val:
                size_val = size_val.strip().upper()
                if size_val in VALID_SIZES and size_val not in available_sizes:
                    available_sizes.append(size_val)

        if not available_sizes:
            self._log_skip("no_ml_size_available")
            return None

        return DiscountItem(
            name=title,
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_percent,
            url=f"{self.base_url}/products/{handle}",
            available_sizes=available_sizes,
            source="Vuori"
        )

    def _log_skip(self, reason: str):
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def _fetch_via_html_fallback(self) -> List[DiscountItem]:
        """Best-effort HTML scrape. Expected to return little/nothing since the
        sale page is JS-rendered, but kept as a documented fallback attempt."""
        try:
            response = requests.get(self.sale_url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            product_count = len(soup.find_all('a', href=re.compile(r'/products/[^?#]*')))
            print(f"HTML fallback: raw page contains {product_count} product links "
                  f"(0 is expected/normal here - this page loads products via JS)")
            return []
        except Exception as e:
            print(f"HTML fallback also failed: {e}")
            return []


# =============================================================================
# MARINE LAYER MONITOR
# =============================================================================
class MarineLayerMonitor:
    """
    Monitor Marine Layer Last Call / Surplus Sale for M/L sizes.

    KEY FIX: the collection listing page itself already contains product name,
    price, and size availability for every item - there is no need to visit
    each individual product page (that was the source of the previous timeout
    failures). This class parses the listing page(s) directly and paginates
    through multiple pages to cover the full section.
    """

    SIZE_TOKEN_RE = re.compile(r'^[A-Z0-9]{1,4}(?:/[A-Z0-9]{1,4})?$')  # e.g. S, M, L, M/L, 2XL, 32
    PRODUCT_BLOCK_RE = re.compile(
        r'\$(\d+(?:\.\d{2})?)\s+\$(\d+(?:\.\d{2})?)'
    )

    def __init__(self):
        self.base_url = "https://www.marinelayer.com"
        self.last_call_url = f"{self.base_url}/collections/guys-last-call"
        self.max_pages = 6
        self.items = []
        self.skip_reasons = {}

    def fetch_last_call_items(self) -> List[DiscountItem]:
        all_items = []
        seen_urls = set()

        for page_num in range(1, self.max_pages + 1):
            page_url = self.last_call_url if page_num == 1 else f"{self.last_call_url}?page={page_num}"
            try:
                resp = requests.get(page_url, headers=HEADERS, timeout=20)
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"Page {page_num}: request failed ({e}), stopping pagination")
                break

            soup = BeautifulSoup(resp.text, 'html.parser')
            product_links = soup.find_all('a', href=re.compile(r'^/products/'))

            # Dedup hrefs on this page, preserve order
            page_urls = list(dict.fromkeys(a.get('href') for a in product_links if a.get('href')))
            new_urls = [u for u in page_urls if u not in seen_urls]

            print(f"Page {page_num}: {len(page_urls)} product links found, {len(new_urls)} new")

            if not new_urls:
                print(f"Page {page_num}: no new products, stopping pagination")
                break

            page_items = 0
            for href in new_urls:
                seen_urls.add(href)
                link_tag = soup.find('a', href=href)
                if link_tag is None:
                    continue
                item = self._extract_item_from_container(link_tag, href)
                if item:
                    all_items.append(item)
                    page_items += 1

            print(f"Page {page_num}: {page_items} items matched M/L criteria")

        print(f"Marine Layer results: {len(all_items)} items found across "
              f"{min(page_num, self.max_pages)} page(s)")
        if self.skip_reasons:
            print(f"Marine Layer skip reasons: {self.skip_reasons}")

        self.items = all_items
        return self.items

    def _extract_item_from_container(self, link_tag, href: str) -> Optional[DiscountItem]:
        """Walk up from the product's anchor tag to find its containing tile,
        then extract name/price/sizes scoped to just that tile's text."""
        node = link_tag
        container_text = None

        for _ in range(6):
            node = node.find_parent()
            if node is None:
                break
            text = node.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text)
            price_matches = self.PRODUCT_BLOCK_RE.findall(text)
            # A good container has exactly one price pair and isn't huge
            # (huge/multiple = we've walked past this product into the grid)
            if len(price_matches) == 1 and len(text) < 500:
                container_text = text
            elif len(price_matches) > 1:
                break  # went too far up, stop and use last good container

        if not container_text:
            self._log_skip("no_price_container_found")
            return None

        price_match = self.PRODUCT_BLOCK_RE.search(container_text)
        if not price_match:
            self._log_skip("no_price_match")
            return None

        original_price = float(price_match.group(1))
        sale_price = float(price_match.group(2))
        if sale_price >= original_price:
            self._log_skip("invalid_price_pair")
            return None
        discount_percent = ((original_price - sale_price) / original_price) * 100

        # Product name: prefer the link's own text if meaningful, else derive from URL
        name = link_tag.get_text(strip=True)
        if not name or len(name) < 3:
            handle = href.rstrip('/').split('/')[-1]
            name = handle.replace('-', ' ').title()

        # Extract size tokens from the container text (tokens before "Adding To Bag"/"Quick Shop")
        sizes_section = container_text.split('Adding To Bag')[0]
        candidate_tokens = sizes_section.split()
        available_sizes = [t.upper() for t in candidate_tokens if t.upper() in VALID_SIZES]
        available_sizes = list(dict.fromkeys(available_sizes))  # dedupe, preserve order

        if not available_sizes:
            self._log_skip("no_ml_size_available")
            return None

        full_url = href if href.startswith('http') else self.base_url + href

        return DiscountItem(
            name=name,
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_percent,
            url=full_url,
            available_sizes=available_sizes,
            source="Marine Layer"
        )

    def _log_skip(self, reason: str):
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


# =============================================================================
# EMAIL / HISTORY
# =============================================================================
def send_email_digest(vuori_items: List[DiscountItem], marine_layer_items: List[DiscountItem]) -> bool:
    try:
        sender_email = os.environ.get('GMAIL_ADDRESS')
        sender_password = os.environ.get('GMAIL_APP_PASSWORD')

        if not sender_email or not sender_password:
            print("ERROR: Gmail credentials not set")
            return False

        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = EMAIL_RECIPIENT
        msg['Subject'] = f"Weekly Discount Digest - {datetime.now().strftime('%B %d, %Y')}"

        total_items = len(vuori_items) + len(marine_layer_items)

        html = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    h1 {{ color: #2c3e50; margin-bottom: 5px; }}
                    h2 {{ color: #34495e; margin-top: 30px; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                    .summary {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                    table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                    th {{ background-color: #3498db; color: white; padding: 12px; text-align: left; }}
                    td {{ padding: 12px; border-bottom: 1px solid #ddd; }}
                    a {{ color: #0066cc; text-decoration: none; }}
                </style>
            </head>
            <body>
                <h1>Weekly Discount Digest</h1>
                <p>Your weekly roundup of premium discounts from Vuori and Marine Layer</p>
                <div class="summary">
                    <p><strong>Found {total_items} items</strong> (Vuori 50%+ off, Marine Layer all Last Call - M/L sizes only)</p>
                    <p>Vuori: {len(vuori_items)} items | Marine Layer: {len(marine_layer_items)} items</p>
                </div>
        """

        for section_name, items in [("Vuori 50%+ Discounts", vuori_items), ("Marine Layer Last Call", marine_layer_items)]:
            html += f"<h2>{section_name}</h2>"
            if items:
                html += """<table><thead><tr>
                    <th>Item</th><th>Sale Price</th><th>Original</th><th>Discount</th><th>Sizes</th><th>Source</th>
                    </tr></thead><tbody>"""
                for item in items:
                    html += item.to_html()
                html += "</tbody></table>"
            else:
                html += "<p>No items found matching criteria.</p>"

        html += """
                <div class="footer" style="margin-top:30px;font-size:12px;color:#7f8c8d;">
                    <p>Click any item to view the full product page.</p>
                    <p>Monitor powered by GitHub Actions • Next digest: Next Sunday at 6 PM PT</p>
                </div>
            </body>
        </html>
        """

        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, EMAIL_RECIPIENT, msg.as_string())

        print(f"Digest email sent to {EMAIL_RECIPIENT}")
        return True

    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def save_digest_history(vuori_items: List[DiscountItem], marine_layer_items: List[DiscountItem]):
    try:
        history = {
            'timestamp': datetime.now().isoformat(),
            'vuori_items': [vars(i) for i in vuori_items],
            'marine_layer_items': [vars(i) for i in marine_layer_items]
        }
        with open('digest_history.json', 'w') as f:
            json.dump(history, f, indent=2)
        print("Digest history saved")
    except Exception as e:
        print(f"Error saving digest history: {e}")


def main():
    print("Starting weekly discount digest monitor")
    print(f"Run time: {datetime.now().isoformat()}")

    print("\n--- Monitoring Vuori ---")
    vuori = VuoriMonitor()
    vuori_items = vuori.fetch_sale_items()
    print(f"Result: {len(vuori_items)} Vuori items (50%+ off, M/L available)")
    if vuori.skip_reasons:
        print(f"Vuori skip reasons: {vuori.skip_reasons}")
    for item in vuori_items[:5]:
        print(f"  - {item.name}: {item.discount_percent:.0f}% off (${item.sale_price:.2f}) sizes={item.available_sizes}")

    print("\n--- Monitoring Marine Layer Last Call ---")
    marine_layer = MarineLayerMonitor()
    marine_layer_items = marine_layer.fetch_last_call_items()
    print(f"Result: {len(marine_layer_items)} Marine Layer items (M/L available)")
    for item in marine_layer_items[:5]:
        print(f"  - {item.name}: {item.discount_percent:.0f}% off (${item.sale_price:.2f}) sizes={item.available_sizes}")

    print("\nSaving digest history...")
    save_digest_history(vuori_items, marine_layer_items)

    total_items = len(vuori_items) + len(marine_layer_items)
    if total_items > 0:
        print(f"\nSending email digest with {total_items} items...")
        success = send_email_digest(vuori_items, marine_layer_items)
        print("✓ Email sent!" if success else "✗ Email failed to send")
    else:
        print("\nNo items found across both retailers - email not sent")
        print("Check the skip-reason logs above to see why")


if __name__ == "__main__":
    main()
