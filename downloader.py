import os
import re
import json
import logging
import requests
from playwright.sync_api import sync_playwright

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("downloader.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def sanitize_filename(name):
    # Remove invalid characters for Windows/Linux folder names
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def download_sequential_images(first_image_url, save_dir):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    # Example first_image_url: https://jloo.wowpic1.store/i/bEqPbYfoNT0GmkHkQj6fsAJYwq0Za/01.webp
    match = re.search(r'(.*?/)(0*1)(\.[a-zA-Z0-9]+)(\?.*)?$', first_image_url)
    if not match:
        logging.error(f"Could not parse image URL pattern from: {first_image_url}")
        return False
        
    base_url = match.group(1)
    num_str = match.group(2)
    ext = match.group(3)
    query = match.group(4) or ""
    
    num_length = len(num_str)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://comix.to/"
    }

    current_idx = 1
    downloaded_any = False
    
    while True:
        current_num_str = str(current_idx).zfill(num_length)
        url = f"{base_url}{current_num_str}{ext}{query}"
        
        file_path = os.path.join(save_dir, f"{current_num_str}{ext.split('?')[0]}")
        
        # Skip if we already downloaded this exact image
        if os.path.exists(file_path):
            logging.debug(f"File {file_path} already exists. Skipping.")
            current_idx += 1
            downloaded_any = True
            continue
            
        logging.info(f"Downloading image {current_idx}: {url}")
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 404:
                logging.info(f"Encountered 404. Assuming chapter download is complete.")
                # Mark this chapter as completely downloaded
                with open(os.path.join(save_dir, ".complete"), "w") as f:
                    f.write("done")
                break
            response.raise_for_status()
            
            with open(file_path, "wb") as f:
                f.write(response.content)
                
            downloaded_any = True
            current_idx += 1
        except Exception as e:
            logging.error(f"Error downloading {url}: {e}")
            break
            
    return downloaded_any

def download_chapter(page, chapter_url, save_dir):
    first_image_url = None
    
    def handle_response(response):
        nonlocal first_image_url
        if first_image_url:
            return
            
        # Check API response
        if "/api/v1/chapters/" in response.url and response.request.method == "GET":
            try:
                json_data = response.json()
                urls = re.findall(r'(https?://[^\s"\'\\]+/i/[^\s"\'\\]+/(?:0*1)\.(?:webp|jpg|png|jpeg))', json.dumps(json_data))
                if urls:
                    first_image_url = urls[0]
            except Exception:
                pass
        
        # Check image response
        if response.request.resource_type == "image":
            match = re.search(r'(https?://.*?/(?:0*1)\.(?:webp|jpg|png|jpeg)(?:\?.*)?)', response.url)
            if match:
                first_image_url = match.group(1)

    page.on("response", handle_response)
    
    logging.info(f"Navigating to {chapter_url}...")
    try:
        page.goto(chapter_url, wait_until="networkidle")
        page.wait_for_timeout(2000) # Wait to allow responses to trigger
    except Exception as e:
        logging.error(f"Error loading page {chapter_url}: {e}")
        
    # Always remove listener to prevent duplicate firings on subsequent navigations
    page.remove_listener("response", handle_response)
    
    if first_image_url:
        logging.info(f"Starting sequential download to {save_dir}/ ...")
        success = download_sequential_images(first_image_url, save_dir)
        if success:
            logging.info(f"Finished processing {save_dir}.")
            return True
        else:
            logging.warning(f"Failed sequential download for {save_dir}.")
            return False
    else:
        logging.error(f"Could not find the first image URL for {chapter_url}.")
        return False

def download_all_from_progress(progress_file):
    if not os.path.exists(progress_file):
        logging.error(f"Progress file '{progress_file}' not found.")
        return
        
    with open(progress_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    chapters = data.get("chapters", [])
    if not chapters:
        logging.warning("No chapters found in progress file.")
        return
        
    # Base folder using the slug, e.g., progress_pvry-one-piece.json -> pvry-one-piece
    manga_slug = os.path.basename(progress_file).replace("progress_", "").replace(".json", "")
    base_dir = sanitize_filename(manga_slug)
    
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
        
    # Download state file to keep track of completed indexes
    downloader_state_file = f"downloader_state_{manga_slug}.json"
    start_idx = 0
    
    if os.path.exists(downloader_state_file):
        try:
            with open(downloader_state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                start_idx = state_data.get("last_completed_idx", -1) + 1
            logging.info(f"Resuming download from chapter index {start_idx} based on state file.")
        except Exception as e:
            logging.error(f"Failed to load downloader state file: {e}")
    
    # Reverse the chapters list to download oldest first (chapter 1 -> chapter 1000)
    chapters.reverse() 
    total_chapters = len(chapters)
    logging.info(f"Found {total_chapters} chapters to download.")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            for idx in range(start_idx, total_chapters):
                chapter = chapters[idx]
                ch_name = sanitize_filename(chapter.get("chapter_name", f"chapter_{idx}"))
                ch_url = chapter.get("chapter_url")
                group = sanitize_filename(chapter.get("group", ""))
                
                folder_name = ch_name
                if group:
                    folder_name += f" [{group}]"
                    
                save_dir = os.path.join(base_dir, folder_name)
                
                logging.info(f"\n--- Processing {idx+1}/{total_chapters}: {folder_name} ---")
                
                # Check complete marker in case folder was manually managed
                if os.path.exists(os.path.join(save_dir, ".complete")):
                    logging.info(f"Chapter already fully downloaded. Skipping.")
                else:
                    success = download_chapter(page, ch_url, save_dir)
                
                # Save progress after each chapter loop completes
                try:
                    with open(downloader_state_file, 'w', encoding='utf-8') as f:
                        json.dump({"last_completed_idx": idx}, f, indent=4)
                    logging.info(f"Downloader progress saved to {downloader_state_file}")
                except Exception as e:
                    logging.error(f"Failed to save downloader state: {e}")
                    
        except Exception as e:
            logging.error(f"A critical error occurred in the Playwright instance: {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass
            
    logging.info("All specified chapters have been processed.")

if __name__ == "__main__":
    download_all_from_progress("test.json")