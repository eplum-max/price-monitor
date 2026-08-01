#!/usr/bin/env python3
"""
Vuori Jacket Price Monitor
Checks if the Steadfast Insulated Full Zip Jacket (Blue Coast) drops below $200
"""

import requests
import json
import smtplib
import os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# Configuration
PRODUCT_URL = "https://vuoriclothing.com/products/steadfast-insulated-full-zip-jacket-blue-coast"
PRICE_THRESHOLD = 200.00
EMAIL_RECIPIENT = "eric.slivka@gmail.com"
PRICE_LOG_FILE = "price_history.json"

def extract_price_from_html(html_content):
    """Extract the sale price from Vuori product page"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for sale price in the page
        # Vuori uses pattern: "Original price $298. Sale price $238.$298$238"
        # We need to find the actual price value
        
        # Try multiple selectors to find the price
        price_patterns = [
            'span[class*="price"]',
            '[data-price]',
            'div[class*="Sale price"]'
        ]
        
        # Search for text containing price pattern
        text = soup.get_text()
        
        # Find the line with sale price
        for line in text.split('\n'):
            line = line.strip()
            if 'Sale price' in line or '$' in line:
                # Extract numbers that look like prices ($XXX)
                import re
                matches = re.findall(r'\$(\d+(?:\.\d{2})?)', line)
                if matches:
                    # Return the last price found (usually the sale price)
                    return float(matches[-1])
        
        # Fallback: look for any price in common price format
        import re
        prices = re.findall(r'\$(\d+(?:\.\d{2})?)', text)
        if prices:
            # Usually sale price is listed after original, so take the last one
            # But Vuori format shows both, so we need to find the smaller one
            prices = [float(p) for p in prices]
            prices = [p for p in prices if p < 500]  # Filter out unrealistic prices
            if prices:
                return min(prices)
        
        return None
    except Exception as e:
        print(f"Error parsing HTML: {e}")
        return None

def fetch_current_price():
    """Fetch the current price from Vuori website"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(PRODUCT_URL, headers=headers, timeout=15)
        response.raise_for_status()
        
        price = extract_price_from_html(response.text)
        return price
    except requests.exceptions.RequestException as e:
        print(f"Error fetching page: {e}")
        return None

def load_price_history():
    """Load previous price checks from history file"""
    try:
        if os.path.exists(PRICE_LOG_FILE):
            with open(PRICE_LOG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading history: {e}")
    return []

def save_price_history(history):
    """Save price history to file"""
    try:
        with open(PRICE_LOG_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving history: {e}")

def send_alert_email(current_price, previous_price=None):
    """Send email alert about price drop"""
    try:
        # Get credentials from environment variables
        sender_email = os.environ.get('GMAIL_ADDRESS')
        sender_password = os.environ.get('GMAIL_APP_PASSWORD')
        
        if not sender_email or not sender_password:
            print("ERROR: Gmail credentials not set in environment variables")
            print("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in GitHub secrets")
            return False
        
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = EMAIL_RECIPIENT
        msg['Subject'] = "Vuori Jacket Price drop alert"
        
        # Build email body
        if previous_price:
            price_change = previous_price - current_price
            percent_change = (price_change / previous_price) * 100
            body = f"""Price Drop Alert!

The Steadfast Insulated Full Zip Jacket (Blue Coast) has dropped below $200!

Current Price: ${current_price:.2f}
Previous Price: ${previous_price:.2f}
Price Change: -${price_change:.2f} ({percent_change:.1f}% off)

Product Link: {PRODUCT_URL}

Shop now while this price lasts!
"""
        else:
            body = f"""Price Alert!

The Steadfast Insulated Full Zip Jacket (Blue Coast) is now priced at ${current_price:.2f} (below your $200 threshold).

Product Link: {PRODUCT_URL}

Shop now while this price lasts!
"""
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Send email via Gmail SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, EMAIL_RECIPIENT, msg.as_string())
        
        print(f"Alert email sent to {EMAIL_RECIPIENT}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def main():
    """Main monitoring function"""
    print(f"Starting Vuori price monitor at {datetime.now().isoformat()}")
    print(f"Target: {PRODUCT_URL}")
    print(f"Threshold: ${PRICE_THRESHOLD:.2f}")
    
    # Fetch current price
    current_price = fetch_current_price()
    
    if current_price is None:
        print("ERROR: Could not fetch price from Vuori website")
        return
    
    print(f"Current price: ${current_price:.2f}")
    
    # Load history
    history = load_price_history()
    previous_price = history[-1]['price'] if history else None
    
    # Check if price is below threshold
    if current_price < PRICE_THRESHOLD:
        print(f"ALERT: Price ${current_price:.2f} is below threshold ${PRICE_THRESHOLD:.2f}")
        
        # Check if we already alerted about this price
        if previous_price is None or abs(current_price - previous_price) > 0.01:
            print("Sending alert email...")
            send_alert_email(current_price, previous_price)
        else:
            print(f"Price unchanged from last check (${previous_price:.2f}), skipping alert")
    else:
        print(f"Price ${current_price:.2f} is above threshold ${PRICE_THRESHOLD:.2f}")
    
    # Save to history
    history.append({
        'timestamp': datetime.now().isoformat(),
        'price': current_price,
        'alerted': current_price < PRICE_THRESHOLD
    })
    
    # Keep only last 90 days of history
    cutoff_date = datetime.now().isoformat()[:10]
    history = [h for h in history[-2160:]]  # ~90 days of hourly checks
    
    save_price_history(history)
    print(f"Price history updated ({len(history)} entries)")

if __name__ == "__main__":
    main()
