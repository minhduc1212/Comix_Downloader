from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json

url = "https://comix.to/title/pvry-one-piece"

def get_metadata(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        content = page.content()
        browser.close()

    soup = BeautifulSoup(content, 'html.parser')

    metadata = {}

    # h1 class="mpage__title": title
    title_elem = soup.find('h1', class_='mpage__title')
    metadata['title'] = title_elem.get_text(strip=True) if title_elem else None

    # div class="poster" -> get img
    poster_elem = soup.find('div', class_='poster')
    if poster_elem:
        img_elem = poster_elem.find('img')
        if img_elem:
            metadata['img'] = img_elem.get('src')
        else:
            metadata['img'] = None
    else:
        metadata['img'] = None

    # div class="mpage__desc-wrap" -> get desc
    desc_elem = soup.find('div', class_='mpage__desc-wrap')
    metadata['desc'] = desc_elem.get_text(strip=True) if desc_elem else None

    return metadata

if __name__ == "__main__":
    metadata = get_metadata(url)
    print(json.dumps(metadata, indent=4, ensure_ascii=False))