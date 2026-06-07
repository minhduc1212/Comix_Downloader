from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from .utils import get_random_user_agent, random_delay

def get_metadata_app(url):
    try:
        random_delay(1.0, 2.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=get_random_user_agent())
            page.goto(url, wait_until="networkidle")
            
            if "Just a moment" in page.title() or "Cloudflare" in page.title():
                browser.close()
                return {"error": "BANNED"}
                
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, 'html.parser')
        metadata = {}

        title_elem = soup.find('h1', class_='mpage__title')
        metadata['title'] = title_elem.get_text(strip=True) if title_elem else "Unknown Title"

        poster_elem = soup.find('div', class_='poster')
        if poster_elem:
            img_elem = poster_elem.find('img')
            metadata['img'] = img_elem.get('src') if img_elem else None
        else:
            metadata['img'] = None

        desc_elem = soup.find('div', class_='mpage__desc-wrap')
        metadata['desc'] = desc_elem.get_text(strip=True) if desc_elem else "No description"

        return metadata
    except Exception as e:
        return {"error": str(e)}

def get_chapters_page(base_url, page_num):
    try:
        separator = "&" if "?" in base_url else "?"
        url = f"{base_url}{separator}page={page_num}"
        
        random_delay(1.0, 3.0)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=get_random_user_agent())
            try:
                page.goto(url, wait_until='networkidle')
                if "Just a moment" in page.title() or "Cloudflare" in page.title():
                    browser.close()
                    return [{"error": "BANNED"}]
                page.wait_for_selector('.mchap-item', timeout=5000)
            except Exception:
                browser.close()
                return []
                
            soup = BeautifulSoup(page.content(), 'html.parser')
            browser.close()
            
        items = soup.find_all('li', class_='mchap-item')
        if not items:
            return []
            
        results = []
        for item in items:
            a_tag = item.find('a', class_='mchap-row__primary')
            if not a_tag:
                continue
                
            chapter_url = "https://comix.to" + a_tag.get('href', '')
            
            ch_span = a_tag.find('span', class_='mchap-row__ch')
            title_span = a_tag.find('span', class_='mchap-row__title')
            
            chapter_name = ""
            if ch_span:
                chapter_name += ch_span.get_text(strip=True)
            if title_span:
                if chapter_name:
                    chapter_name += " - "
                chapter_name += title_span.get_text(strip=True)
                
            group_tag = item.find('a', class_='mchap-row__group')
            group = ""
            if group_tag:
                group_span = group_tag.find('span')
                if group_span:
                    group = group_span.get_text(strip=True)
                    
            results.append({
                "chapter_name": chapter_name,
                "chapter_url": chapter_url,
                "group": group
            })
            
        return results
    except Exception as e:
        return []
