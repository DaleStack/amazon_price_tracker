import requests
from bs4 import BeautifulSoup
import smtplib
import time
import configparser
import logging
import random
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
import json
import os

# Configure logging with UTF-8 encoding for emoji support
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_tracker.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Fix console encoding for Windows
import sys
if sys.platform.startswith('win'):
    try:
        # Try to set console to UTF-8 mode
        import os
        os.system('chcp 65001 >nul 2>&1')
        # Reconfigure stdout for UTF-8
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        # If UTF-8 fails, we'll strip emojis from console output
        pass
logger = logging.getLogger(__name__)

def safe_log(message):
    """Log message with emoji fallback for console compatibility"""
    try:
        logger.info(message)
    except UnicodeEncodeError:
        # Strip emojis for console output if encoding fails
        import re
        clean_message = re.sub(r'[^\x00-\x7F]+', '', message)
        logger.info(clean_message)

class AmazonPriceTracker:
    def __init__(self, config_file='config.ini'):
        self.config = self.load_config(config_file)
        self.session = requests.Session()
        self.setup_session()
        self.price_history_file = 'price_history.json'
        self.price_history = self.load_price_history()
        
    def load_config(self, config_file):
        """Load and validate configuration"""
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file {config_file} not found")
        
        config = configparser.ConfigParser(interpolation=None)
        config.read(config_file)
        
        # Validate required sections
        required_sections = ['email', 'products', 'tracking']
        for section in required_sections:
            if not config.has_section(section):
                raise ValueError(f"Missing required section '{section}' in config file")
        
        # Validate email settings
        required_email_keys = ['sender', 'recipient', 'api_key']
        for key in required_email_keys:
            if not config.has_option('email', key):
                raise ValueError(f"Missing required email setting '{key}'")
        
        logger.info("Configuration loaded successfully")
        return config
    
    def setup_session(self):
        """Setup requests session with more sophisticated anti-detection measures"""
        # More diverse and recent user agents
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0'
        ]
        
        # More realistic headers
        self.session.headers.clear()
        self.session.headers.update({
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        })
        
        # Add some randomization to avoid fingerprinting
        if random.choice([True, False]):
            self.session.headers['DNT'] = '1'
    
    def load_price_history(self):
        """Load price history from file"""
        if os.path.exists(self.price_history_file):
            try:
                with open(self.price_history_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Could not load price history, starting fresh")
        return {}
    
    def save_price_history(self):
        """Save price history to file"""
        try:
            with open(self.price_history_file, 'w') as f:
                json.dump(self.price_history, f, indent=2)
        except IOError as e:
            logger.error(f"Could not save price history: {e}")
    
    def get_price(self, url: str, max_retries: int = 3) -> Optional[float]:
        """Get current price from Amazon with enhanced anti-detection"""
        
        # Multiple price selectors for different Amazon layouts
        price_selectors = [
            'span.a-offscreen',
            'span#priceblock_dealprice',
            'span#priceblock_ourprice', 
            'span.a-price-whole',
            'span.a-price.a-text-price.a-size-medium.apexPriceToPay',
            'span.a-price-range',
            '.a-price .a-offscreen',
            '#corePrice_feature_div .a-price .a-offscreen',
            '#apex_desktop .a-price .a-offscreen',
            '.a-price-to-pay .a-offscreen',
            '#priceblock_pactprice',
            '.a-price.a-text-price.a-size-medium.apexPriceToPay .a-offscreen'
        ]
        
        for attempt in range(max_retries):
            try:
                # Short progressive delay with jitter
                if attempt > 0:
                    base_delay = 2 + (attempt * 1.5)  # 2, 3.5, 5 seconds
                    jitter = random.uniform(-0.5, 0.5)
                    delay = max(1, base_delay + jitter)
                    logger.info(f"Retry {attempt + 1}, waiting {delay:.1f} seconds...")
                    time.sleep(delay)
                
                # Refresh session and headers for each attempt
                self.setup_session()
                
                # Add referrer to look more natural
                if 'amazon.com' in url:
                    self.session.headers['Referer'] = 'https://www.amazon.com/'
                
                # Make request with longer timeout
                response = self.session.get(url, timeout=20, allow_redirects=True)
                response.raise_for_status()
                
                # Enhanced bot detection
                response_text = response.text.lower()
                bot_indicators = [
                    "robot check", "blocked", "captcha", "unusual traffic",
                    "automated queries", "sorry, we just need to make sure you're not a robot",
                    "enter the characters you see below", "type the characters you see in this image"
                ]
                
                if any(indicator in response_text for indicator in bot_indicators):
                    logger.warning(f"Attempt {attempt + 1}: Bot detection triggered")
                    # Shorter delay when detected - only if we have more retries
                    if attempt < max_retries - 1:
                        delay = random.uniform(10, 20)  # Reduced from 30-60 to 10-20 seconds
                        logger.info(f"Bot detected, waiting {delay:.1f} seconds before retry...")
                        time.sleep(delay)
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try each price selector
                for selector in price_selectors:
                    try:
                        price_elements = soup.select(selector)
                        for price_element in price_elements:
                            if price_element:
                                price_text = price_element.get_text().strip()
                                price = self.parse_price(price_text)
                                if price and self.validate_price(price):
                                    logger.info(f"Found price ${price} using selector: {selector}")
                                    return price
                    except Exception as e:
                        logger.debug(f"Error with selector {selector}: {e}")
                        continue
                
                # If no price found, log page info for debugging
                title_element = soup.find('title')
                title = title_element.get_text() if title_element else "Unknown"
                logger.warning(f"No price found on attempt {attempt + 1}. Page title: {title[:100]}...")
                
                # Check if we're on the right product page
                if "amazon" not in title.lower() and "error" not in title.lower():
                    logger.warning("Possibly redirected to non-Amazon page")
                
            except requests.exceptions.Timeout:
                logger.warning(f"Attempt {attempt + 1}: Request timeout after 20 seconds")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}: Request failed - {e}")
            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Unexpected error - {e}")
        
        logger.error(f"Failed to get price after {max_retries} attempts")
        return None
    
    def parse_price(self, price_text: str) -> Optional[float]:
        """Parse price from text with multiple formats"""
        if not price_text:
            return None
        
        # Remove common currency symbols and clean text
        cleaned = re.sub(r'[^\d.,\-]', '', price_text)
        
        # Handle different price formats
        price_patterns = [
            r'(\d+(?:,\d{3})*\.?\d*)',  # Standard format: 123,456.78
            r'(\d+\.?\d*)',              # Simple format: 123.45
            r'(\d+,\d+)',                # European format: 123,45
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, cleaned)
            if match:
                try:
                    price_str = match.group(1).replace(',', '')
                    price = float(price_str)
                    return price
                except (ValueError, AttributeError):
                    continue
        
        return None
    
    def validate_price(self, price: float) -> bool:
        """Validate that price is reasonable"""
        return 0.01 <= price <= 50000  # Reasonable price range
    
    def update_price_history(self, product_name: str, price: float):
        """Update price history for a product"""
        if product_name not in self.price_history:
            self.price_history[product_name] = []
        
        entry = {
            'price': price,
            'timestamp': datetime.now().isoformat()
        }
        
        self.price_history[product_name].append(entry)
        
        # Keep only last 100 entries per product
        if len(self.price_history[product_name]) > 100:
            self.price_history[product_name] = self.price_history[product_name][-100:]
    
    def send_alert(self, product_name: str, current_price: float, target_price: float, url: str):
        """Send email alert via SendGrid SMTP"""
        try:
            sender = self.config.get('email', 'sender')
            recipient = self.config.get('email', 'recipient')
            api_key = self.config.get('email', 'api_key')

            # Calculate savings
            previous_prices = self.price_history.get(product_name, [])
            previous_price = previous_prices[-2]['price'] if len(previous_prices) >= 2 else None
            
            subject = f"PRICE ALERT: {product_name} dropped to ${current_price:.2f}!"

            # Enhanced HTML email body (keeping emojis here since email supports them)
            savings_text = ""
            if previous_price and previous_price > current_price:
                savings = previous_price - current_price
                savings_percent = (savings / previous_price) * 100
                savings_text = f"<p>💰 <strong>You save ${savings:.2f} ({savings_percent:.1f}%)</strong> from the previous price of ${previous_price:.2f}</p>"

            body = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.5; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                  <h2 style="margin: 0;">🎯 Price Alert!</h2>
                </div>
                <div style="background: white; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 10px 10px;">
                  <h3 style="color: #333; margin-top: 0;">{product_name}</h3>
                  <p style="font-size: 18px;">
                    Current Price: <strong style="color: #28a745; font-size: 24px;">${current_price:.2f}</strong><br>
                    Target Price: <strong>${target_price:.2f}</strong>
                  </p>
                  {savings_text}
                  <div style="text-align: center; margin: 30px 0;">
                    <a href="{url}" style="background: #ff9500; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                      🛒 Buy Now on Amazon
                    </a>
                  </div>
                  <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                  <small style="color: #666;">
                    Amazon Price Tracker by Casey Dale Siatong<br>
                    Alert sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                  </small>
                </div>
              </body>
            </html>
            """

            msg = MIMEMultipart("alternative")
            msg["From"] = sender
            msg["To"] = recipient
            msg["Subject"] = subject

            # Plain text fallback
            text_fallback = f"""
Price Alert: {product_name}

Current Price: ${current_price:.2f}
Target Price: ${target_price:.2f}

Buy now: {url}

Amazon Price Tracker by Casey Dale Siatong
            """.strip()
            
            msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
            msg.attach(MIMEText(body, "html", "utf-8"))

            with smtplib.SMTP("smtp.sendgrid.net", 587) as server:
                server.starttls()
                server.login("apikey", api_key)
                server.sendmail(sender, [recipient], msg.as_string())

            logger.info(f"Alert sent successfully for {product_name}!")
            
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")

    def run_single_check(self):
        """Run a single price check cycle"""
        logger.info("Starting price check cycle")
        
        if not self.config.has_section('products'):
            logger.error("No products section found in config")
            return
        
        products = dict(self.config.items('products'))
        if not products:
            logger.error("No products configured")
            return
        
        check_interval = self.config.getint('tracking', 'check_interval', fallback=30)
        
        for product_name, product_config in products.items():
            try:
                # Parse product configuration
                parts = product_config.split(',', 1)
                if len(parts) != 2:
                    logger.error(f"Invalid product config for {product_name}: {product_config}")
                    continue
                
                url = parts[0].strip()
                target_price = float(parts[1].strip())
                
                logger.info(f"Checking price for: {product_name}")
                logger.info(f"Target price: ${target_price:.2f}")
                
                current_price = self.get_price(url)
                
                if current_price is None:
                    logger.error(f"Could not retrieve price for {product_name}")
                    continue
                
                logger.info(f"Current price: ${current_price:.2f}")
                
                # Update price history
                self.update_price_history(product_name, current_price)
                
                # Check if price dropped below target
                if current_price <= target_price:
                    safe_log(f"TARGET HIT! Price target hit for {product_name}!")
                    self.send_alert(product_name, current_price, target_price, url)
                else:
                    logger.info(f"Price still above target (${current_price:.2f} > ${target_price:.2f})")
                
                # Save price history after each product
                self.save_price_history()
                
                # Random delay between products to avoid detection
                if len(products) > 1:
                    delay = random.uniform(check_interval * 0.5, check_interval * 1.5)
                    logger.info(f"Waiting {delay:.1f} seconds before next product...")
                    time.sleep(delay)
                    
            except ValueError as e:
                logger.error(f"Invalid target price for {product_name}: {e}")
            except Exception as e:
                logger.error(f"Error processing {product_name}: {e}")
        
        logger.info("Price check cycle completed")

def main():
    """Main function with improved error handling"""
    try:
        tracker = AmazonPriceTracker()
        
        # Check if running continuously or once
        run_mode = tracker.config.get('tracking', 'run_mode', fallback='once').lower()
        
        if run_mode == 'continuous':
            interval_minutes = tracker.config.getint('tracking', 'interval_minutes', fallback=60)
            logger.info(f"Starting continuous monitoring (checking every {interval_minutes} minutes)")
            
            while True:
                tracker.run_single_check()
                
                logger.info(f"Sleeping for {interval_minutes} minutes...")
                time.sleep(interval_minutes * 60)
        else:
            logger.info("Running single price check")
            tracker.run_single_check()
            
    except KeyboardInterrupt:
        logger.info("Price tracker stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()