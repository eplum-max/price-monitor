#!/usr/bin/env python3
"""
Vuori 50%+ Discount & Marine Layer Last Call Monitor
Runs weekly on Sunday at 6 PM Pacific time
Finds items at 50%+ discount (M/L sizes only) and sends weekly email digest
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
from typing import List, Dict

# Configuration
EMAIL_RECIPIENT = "eric.slivka@gmail.com"
DISCOUNT_THRESHOLD = 50.0  # 50% or more
VALID_SIZES = ['M', 'L', 'Medium', 'Large']
MIN_SIZE_KEYWORDS = ['M', 'L', 'medium', 'large']

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
        """Convert item to HTML row for email"""
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

class VuoriMonitor:
    """Monitor Vuori sale section for 50%+ discounts"""
    
    def __init__(self):
        self.base_url = "https://vuoriclothing.com"
        self.sale_url = f"{self.base_url}/collections/sale"
        self.items = []
    
    def fetch_sale_items(self) -> List[DiscountItem]:
        """Fetch all Vuori sale items with 50%+ discount in M/L sizes"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            # Vuori uses Shopify, which loads products via JSON
            # We'll scrape the HTML and look for product links, then fetch details
            response = requests.get(self.sale_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for product cards - Vuori uses specific classes
            product_links = soup.find_all('a', {'class': re.compile('product-card|ProductCard')})
            
            if not product_links:
                # Fallback: look for any links with product URLs
                product_links = soup.find_all('a', href=re.compile(r'/products/'))
            
            print(f"Found {len(product_links)} potential product links on Vuori sale page")
            
            for link in product_links:
                try:
                    product_url = link.get('href', '')
                    if not product_url:
                        continue
                    
                    if not product_url.startswith('http'):
                        product_url = self.base_url + product_url
                    
                    # Extract product name from link
                    product_name = link.get_text(strip=True)
                    if not product_name:
                        continue
                    
                    # Fetch product page to get detailed info
                    item = self._get_product_details(product_url, product_name)
                    if item:
                        self.items.append(item)
                
                except Exception as e:
                    print(f"Error processing product link: {e}")
                    continue
            
            return self.items
        
        except Exception as e:
            print(f"Error fetching Vuori sale items: {e}")
            return []
    
    def _get_product_details(self, url: str, name: str) -> DiscountItem | None:
        """Fetch detailed product info from product page"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text()
            
            # Extract prices using regex
            # Pattern: "Original price $298. Sale price $238"
            pattern = r'Original price \$(\d+(?:\.\d{2})?)\.\s*Sale price \$(\d+(?:\.\d{2})?)'
            match = re.search(pattern, text)
            
            if not match:
                return None
            
            original_price = float(match.group(1))
            sale_price = float(match.group(2))
            
            # Calculate discount
            discount_percent = ((original_price - sale_price) / original_price) * 100
            
            # Check if discount meets threshold
            if discount_percent < self.DISCOUNT_THRESHOLD:
                return None
            
            # Extract available sizes (M and L only)
            available_sizes = self._extract_sizes(soup)
            
            if not available_sizes:
                return None
            
            return DiscountItem(
                name=name,
                original_price=original_price,
                sale_price=sale_price,
                discount_percent=discount_percent,
                url=url,
                available_sizes=available_sizes,
                source="Vuori"
            )
        
        except Exception as e:
            print(f"Error fetching product details from {url}: {e}")
            return None
    
    def _extract_sizes(self, soup: BeautifulSoup) -> List[str]:
        """Extract M and L sizes from product page"""
        sizes = []
        
        # Look for size buttons/options
        size_elements = soup.find_all(['button', 'option', 'span'], 
                                     {'class': re.compile('size|Size')})
        
        for elem in size_elements:
            text = elem.get_text(strip=True).upper()
            if text in ['M', 'L', 'MEDIUM', 'LARGE']:
                if text not in sizes:
                    sizes.append(text)
        
        return sizes
    
    DISCOUNT_THRESHOLD = 50.0

class MarineLayerMonitor:
    """Monitor Marine Layer Last Call for M/L sizes"""
    
    def __init__(self):
        self.base_url = "https://www.marinelayer.com"
        self.last_call_url = f"{self.base_url}/collections/guys-last-call"
        self.items = []
    
    def fetch_last_call_items(self) -> List[DiscountItem]:
        """Fetch Marine Layer Last Call items in M/L sizes"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            # Marine Layer Last Call (men's)
            response = requests.get(self.last_call_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for product cards
            product_links = soup.find_all('a', href=re.compile(r'/products/'))
            
            print(f"Found {len(product_links)} potential product links on Marine Layer Last Call")
            
            seen_urls = set()
            
            for link in product_links:
                try:
                    product_url = link.get('href', '')
                    if not product_url or product_url in seen_urls:
                        continue
                    
                    seen_urls.add(product_url)
                    
                    if not product_url.startswith('http'):
                        product_url = self.base_url + product_url
                    
                    # Fetch product details
                    item = self._get_product_details(product_url)
                    if item:
                        self.items.append(item)
                
                except Exception as e:
                    print(f"Error processing Marine Layer product: {e}")
                    continue
            
            return self.items
        
        except Exception as e:
            print(f"Error fetching Marine Layer Last Call items: {e}")
            return []
    
    def _get_product_details(self, url: str) -> DiscountItem | None:
        """Fetch detailed product info from Marine Layer product page"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract product name
            name_elem = soup.find('h1')
            if not name_elem:
                return None
            product_name = name_elem.get_text(strip=True)
            
            # Extract prices and discount
            # Marine Layer shows: "$138 $68" (original sale) or "Save $70"
            text = soup.get_text()
            
            # Look for price pattern
            price_match = re.search(r'\$(\d+(?:\.\d{2})?)\s+\$(\d+(?:\.\d{2})?)', text)
            if not price_match:
                return None
            
            original_price = float(price_match.group(1))
            sale_price = float(price_match.group(2))
            
            # Calculate discount
            discount_percent = ((original_price - sale_price) / original_price) * 100
            
            # Extract available sizes (M and L only)
            available_sizes = self._extract_sizes(soup)
            
            if not available_sizes:
                return None
            
            return DiscountItem(
                name=product_name,
                original_price=original_price,
                sale_price=sale_price,
                discount_percent=discount_percent,
                url=url,
                available_sizes=available_sizes,
                source="Marine Layer"
            )
        
        except Exception as e:
            print(f"Error fetching Marine Layer product details from {url}: {e}")
            return None
    
    def _extract_sizes(self, soup: BeautifulSoup) -> List[str]:
        """Extract M and L sizes from product page"""
        sizes = []
        
        # Look for size buttons/options
        size_elements = soup.find_all(['button', 'option', 'span'], 
                                     {'class': re.compile('size|Size')})
        
        for elem in size_elements:
            text = elem.get_text(strip=True).upper()
            if text in ['M', 'L', 'MEDIUM', 'LARGE']:
                if text not in sizes:
                    sizes.append(text)
        
        return sizes

def send_email_digest(vuori_items: List[DiscountItem], 
                     marine_layer_items: List[DiscountItem]):
    """Send email digest with all discount items"""
    try:
        sender_email = os.environ.get('GMAIL_ADDRESS')
        sender_password = os.environ.get('GMAIL_APP_PASSWORD')
        
        if not sender_email or not sender_password:
            print("ERROR: Gmail credentials not set")
            return False
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = EMAIL_RECIPIENT
        msg['Subject'] = f"Weekly Discount Digest - {datetime.now().strftime('%B %d, %Y')}"
        
        total_items = len(vuori_items) + len(marine_layer_items)
        
        # Build HTML body
        html = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    h1 {{ color: #2c3e50; margin-bottom: 5px; }}
                    h2 {{ color: #34495e; margin-top: 30px; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                    .summary {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                    .summary p {{ margin: 5px 0; }}
                    table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                    th {{ background-color: #3498db; color: white; padding: 12px; text-align: left; }}
                    td {{ padding: 12px; border-bottom: 1px solid #ddd; }}
                    tr:hover {{ background-color: #f9f9f9; }}
                    .discount {{ color: #d9534f; font-weight: bold; }}
                    .footer {{ margin-top: 30px; font-size: 12px; color: #7f8c8d; border-top: 1px solid #ecf0f1; padding-top: 20px; }}
                    a {{ color: #0066cc; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                </style>
            </head>
            <body>
                <h1>Weekly Discount Digest</h1>
                <p>Your weekly roundup of premium discounts from Vuori and Marine Layer</p>
                
                <div class="summary">
                    <p><strong>Found {total_items} items</strong> matching your criteria (50%+ off M/L sizes)</p>
                    <p>Vuori: {len(vuori_items)} items | Marine Layer: {len(marine_layer_items)} items</p>
                </div>
        """
        
        # Add Vuori section
        if vuori_items:
            html += "<h2>Vuori 50%+ Discounts</h2>"
            html += """
            <table>
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Sale Price</th>
                        <th>Original</th>
                        <th>Discount</th>
                        <th>Sizes</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in vuori_items:
                html += item.to_html()
            html += """
                </tbody>
            </table>
            """
        else:
            html += "<h2>Vuori 50%+ Discounts</h2><p>No items found matching criteria.</p>"
        
        # Add Marine Layer section
        if marine_layer_items:
            html += "<h2>Marine Layer Last Call</h2>"
            html += """
            <table>
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Sale Price</th>
                        <th>Original</th>
                        <th>Discount</th>
                        <th>Sizes</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in marine_layer_items:
                html += item.to_html()
            html += """
                </tbody>
            </table>
            """
        else:
            html += "<h2>Marine Layer Last Call</h2><p>No items found matching criteria.</p>"
        
        # Add footer
        html += """
                <div class="footer">
                    <p>This is your weekly discount digest. Click on any item to view the full product page.</p>
                    <p>Monitor powered by GitHub Actions • Next digest: Next Sunday at 6 PM PT</p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        # Send email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, EMAIL_RECIPIENT, msg.as_string())
        
        print(f"Digest email sent to {EMAIL_RECIPIENT}")
        return True
    
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def save_digest_history(vuori_items: List[DiscountItem], 
                       marine_layer_items: List[DiscountItem]):
    """Save digest to history file"""
    try:
        history = {
            'timestamp': datetime.now().isoformat(),
            'vuori_items': [{
                'name': item.name,
                'sale_price': item.sale_price,
                'original_price': item.original_price,
                'discount_percent': item.discount_percent,
                'url': item.url,
                'sizes': item.available_sizes
            } for item in vuori_items],
            'marine_layer_items': [{
                'name': item.name,
                'sale_price': item.sale_price,
                'original_price': item.original_price,
                'discount_percent': item.discount_percent,
                'url': item.url,
                'sizes': item.available_sizes
            } for item in marine_layer_items]
        }
        
        with open('digest_history.json', 'w') as f:
            json.dump(history, f, indent=2)
        
        print("Digest history saved")
    except Exception as e:
        print(f"Error saving digest history: {e}")

def main():
    print("Starting weekly discount digest monitor")
    print(f"Run time: {datetime.now().isoformat()}")
    
    # Monitor Vuori
    print("\nMonitoring Vuori...")
    vuori = VuoriMonitor()
    vuori_items = vuori.fetch_sale_items()
    print(f"Found {len(vuori_items)} Vuori items with 50%+ discount in M/L sizes")
    
    # Monitor Marine Layer
    print("\nMonitoring Marine Layer Last Call...")
    marine_layer = MarineLayerMonitor()
    marine_layer_items = marine_layer.fetch_last_call_items()
    print(f"Found {len(marine_layer_items)} Marine Layer Last Call items in M/L sizes")
    
    # Save history
    save_digest_history(vuori_items, marine_layer_items)
    
    # Send email digest
    if vuori_items or marine_layer_items:
        print("\nSending email digest...")
        send_email_digest(vuori_items, marine_layer_items)
    else:
        print("\nNo items found - email not sent")

if __name__ == "__main__":
    main()
