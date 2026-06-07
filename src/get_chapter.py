import json
import logging
import os
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def get_chapters(base_url):
    """
    Crawls chapter pages starting from ?page=1 and extracts chapter details.
    Features save/resume and error logging.
    """
    # Extract slug for progress file
    match = re.search(r'/title/([^/]+)', base_url)
    slug = match.group(1) if match else "unknown"
    progress_file = f"progress_{slug}.json"
    
    results = []
    page_num = 1
    
    # Load progress if exists
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                results = data.get("chapters", [])
                page_num = data.get("next_page", 1)
            logging.info(f"Resuming from page {page_num} with {len(results)} chapters already loaded.")
        except Exception as e:
            logging.error(f"Failed to load progress file: {e}. Starting from page 1.")
            
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Route filter to block heavy resources/trackers
            def route_filter(route):
                resource_type = route.request.resource_type
                url_str = route.request.url
                if resource_type in ["stylesheet", "font", "media", "image"]:
                    route.abort()
                elif any(tracker in url_str for tracker in ["google-analytics", "doubleclick", "facebook", "analytics", "ads"]):
                    route.abort()
                else:
                    route.continue_()
            try:
                page.route("**/*", route_filter)
            except Exception:
                pass
            
            while True:
                separator = "&" if "?" in base_url else "?"
                url = f"{base_url}{separator}page={page_num}"
                logging.info(f"Fetching {url}")
                
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    # Wait for chapters to load, timeout after 5s if none exist
                    page.wait_for_selector('.mchap-item', timeout=5000)
                except Exception as e:
                    logging.warning(f"No chapters found on page {page_num} or timeout reached. Stopping crawler. Detail: {str(e)}")
                    break
                    
                soup = BeautifulSoup(page.content(), 'html.parser')
                items = soup.find_all('li', class_='mchap-item')
                
                if not items:
                    logging.info(f"No '.mchap-item' elements found on page {page_num}. Stopping crawler.")
                    break
                    
                page_results = []
                for item in items:
                    a_tag = item.find('a', class_='mchap-row__primary')
                    if not a_tag:
                        continue
                        
                    chapter_url = "https://comix.to" + a_tag.get('href', '')
                    
                    # Combine chapter number and title
                    ch_span = a_tag.find('span', class_='mchap-row__ch')
                    title_span = a_tag.find('span', class_='mchap-row__title')
                    
                    chapter_name = ""
                    if ch_span:
                        chapter_name += ch_span.get_text(strip=True)
                    if title_span:
                        if chapter_name:
                            chapter_name += " - "
                        chapter_name += title_span.get_text(strip=True)
                        
                    # Extract scanlation group
                    group_tag = item.find('a', class_='mchap-row__group')
                    group = ""
                    if group_tag:
                        group_span = group_tag.find('span')
                        if group_span:
                            group = group_span.get_text(strip=True)
                            
                    page_results.append({
                        "chapter_name": chapter_name,
                        "chapter_url": chapter_url,
                        "group": group
                    })
                    
                results.extend(page_results)
                logging.info(f"Successfully scraped {len(page_results)} chapters from page {page_num}.")
                
                page_num += 1
                
                # Save progress after each successful page
                try:
                    with open(progress_file, 'w', encoding='utf-8') as f:
                        json.dump({"next_page": page_num, "chapters": results}, f, indent=4)
                    logging.info(f"Progress saved to {progress_file}")
                except Exception as e:
                    logging.error(f"Failed to save progress to {progress_file}: {e}")
                    
        except Exception as e:
            logging.error(f"A critical error occurred in the browser instance: {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass
            
    logging.info(f"Crawl finished. Total chapters: {len(results)}")
    return results

if __name__ == "__main__":
    test_url = "https://comix.to/title/pvry-one-piece"
    chapters = get_chapters(test_url)
    
    if chapters:
        logging.info("Sample from the first loaded chapter:")
        logging.info(json.dumps(chapters[0], indent=4))
        
        logging.info("Sample from the last fetched chapter:")
        logging.info(json.dumps(chapters[-1], indent=4))
