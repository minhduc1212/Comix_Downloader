import os
import re
import json
import logging
import requests
import concurrent.futures
import threading
import time
from playwright.sync_api import sync_playwright
from .utils import get_random_user_agent, random_delay

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

def download_sequential_images(first_image_url, save_dir, progress_callback=None, max_workers=5):
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
    
    # Consistent User-Agent for this chapter
    user_agent = get_random_user_agent()
    
    status = {}
    status_lock = threading.Lock()
    banned_flag = threading.Event()
    
    def download_page(idx):
        if banned_flag.is_set():
            return 'banned'
            
        current_num_str = str(idx).zfill(num_length)
        url = f"{base_url}{current_num_str}{ext}{query}"
        file_path = os.path.join(save_dir, f"{current_num_str}{ext.split('?')[0]}")
        
        # Skip if we already downloaded this exact image
        if os.path.exists(file_path):
            logging.debug(f"File {file_path} already exists. Skipping.")
            return 'downloaded'
            
        logging.info(f"Downloading image {idx}: {url}")
        
        temp_file_path = file_path + ".tmp"
        max_retries = 5
        for attempt in range(max_retries):
            if banned_flag.is_set():
                return 'banned'
                
            # Random delay per request to avoid spikes
            random_delay(0.3, 1.2)
            
            headers = {
                "User-Agent": user_agent,
                "Referer": "https://comix.to/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
                "Connection": "close"
            }
            
            # Check if there is a partial download to resume
            downloaded_bytes = 0
            if os.path.exists(temp_file_path):
                downloaded_bytes = os.path.getsize(temp_file_path)
                
            if downloaded_bytes > 0:
                headers["Range"] = f"bytes={downloaded_bytes}-"
                logging.info(f"Resuming download of image {idx} from byte {downloaded_bytes}...")
            
            try:
                response = requests.get(url, headers=headers, timeout=30, stream=True)
                
                if response.status_code == 404:
                    logging.info(f"Encountered 404 for image {idx}.")
                    return '404'
                    
                if response.status_code == 416:
                    logging.info(f"Encountered 416 (Range Not Satisfiable) for image {idx}. Assuming complete.")
                    if os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) > 0:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        os.rename(temp_file_path, file_path)
                        if progress_callback:
                            progress_callback(idx)
                        return 'downloaded'
                    else:
                        if os.path.exists(temp_file_path):
                            os.remove(temp_file_path)
                        raise Exception("416 Range Not Satisfiable with empty or missing temp file")
                        
                if response.status_code in [403, 429]:
                    logging.error(f"Encountered {response.status_code} for image {idx}. Banned or rate-limited.")
                    banned_flag.set()
                    return 'banned'
                    
                response.raise_for_status()
                
                content_type = response.headers.get("Content-Type", "")
                if "text/html" in content_type or "cloudflare" in content_type.lower():
                    logging.error(f"Encountered HTML response instead of image for {url}. Likely Cloudflare challenge/ban.")
                    banned_flag.set()
                    return 'banned'
                
                is_partial = (response.status_code == 206)
                write_mode = "ab" if is_partial else "wb"
                
                with open(temp_file_path, write_mode) as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                # Check if file is valid (non-empty)
                if os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) > 0:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    os.rename(temp_file_path, file_path)
                else:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    raise Exception("Downloaded file is empty")
                
                if progress_callback:
                    progress_callback(idx)
                return 'downloaded'
                
            except Exception as e:
                logging.warning(f"Error downloading {url} (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))  # Backoff
                    
        return 'failed'

    active_futures = {}
    next_submit_idx = 1
    last_page = None
    window_size = max_workers * 2
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            if banned_flag.is_set():
                break
                
            # Check for consecutive 404s to determine last_page
            # Scan from 1 upwards
            detected_last_page = None
            for i in range(1, next_submit_idx + 1):
                # If we see two consecutive 404s, i-1 is the last page
                with status_lock:
                    is_404_i = (status.get(i) == '404')
                    is_404_next = (status.get(i + 1) == '404')
                if is_404_i and is_404_next:
                    detected_last_page = i - 1
                    break
                    
            if detected_last_page is not None:
                last_page = detected_last_page
                
            # If last page is known, check if all pages up to last page are completed
            if last_page is not None:
                all_done = True
                for i in range(1, last_page + 1):
                    with status_lock:
                        st = status.get(i)
                    if st not in ['downloaded', 'failed']:
                        all_done = False
                        break
                if all_done:
                    break
                    
            # Calculate highest_finished_idx: the contiguous block of finished/failed/404 pages from 1.
            contig = 0
            while True:
                with status_lock:
                    has_it = (contig + 1) in status
                if has_it:
                    contig += 1
                else:
                    break
            highest_finished_idx = contig
            
            # Submit new tasks to fill up max_workers
            while len(active_futures) < max_workers:
                should_submit = False
                if last_page is not None:
                    if next_submit_idx <= last_page:
                        should_submit = True
                else:
                    if next_submit_idx <= highest_finished_idx + window_size:
                        should_submit = True
                        
                if should_submit:
                    future = executor.submit(download_page, next_submit_idx)
                    active_futures[future] = next_submit_idx
                    next_submit_idx += 1
                else:
                    break
                    
            if not active_futures:
                break
                
            # Wait for at least one future to complete
            done, _ = concurrent.futures.wait(active_futures.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                idx = active_futures.pop(future)
                try:
                    res = future.result()
                    with status_lock:
                        status[idx] = res
                except Exception as e:
                    logging.error(f"Future for page {idx} raised exception: {e}")
                    with status_lock:
                        status[idx] = 'failed'
                        
    if banned_flag.is_set() or any(status.get(i) == 'banned' for i in status):
        return "BANNED"
        
    if last_page is None or last_page == 0:
        logging.error("Could not determine the end of the chapter (no pages found).")
        return False
        
    failed_pages = [i for i in range(1, last_page + 1) if status.get(i) == 'failed']
    if failed_pages:
        logging.warning(f"Chapter download incomplete. Failed pages: {failed_pages}")
        return False
        
    # Mark this chapter as completely downloaded
    with open(os.path.join(save_dir, ".complete"), "w") as f:
        f.write("done")
    logging.info(f"Finished processing {save_dir}. All pages downloaded successfully.")
    return True

def download_chapter(page, chapter_url, save_dir, progress_callback=None):
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
    
    # Abort trackers/analytics to load faster
    def route_filter(route):
        url = route.request.url
        if any(tracker in url for tracker in ["google-analytics", "doubleclick", "facebook", "analytics", "ads", "whos.amung.us"]):
            route.abort()
        else:
            route.continue_()
            
    try:
        page.route("**/*", route_filter)
    except Exception:
        pass
        
    logging.info(f"Navigating to {chapter_url}...")
    try:
        # domcontentloaded is much faster than networkidle
        page.goto(chapter_url, wait_until="domcontentloaded", timeout=20000)
        
        # Poll for first_image_url with timeout of 5 seconds (50 * 100ms)
        for _ in range(50):
            if first_image_url:
                break
            page.wait_for_timeout(100)
    except Exception as e:
        logging.error(f"Error loading page {chapter_url}: {e}")
        
    # Always clean up routing and listeners
    try:
        page.remove_listener("response", handle_response)
        page.unroute("**/*")
    except Exception:
        pass
    
    if "Just a moment" in page.title() or "Cloudflare" in page.title():
        logging.error("Cloudflare challenge detected. You are temporarily banned or blocked.")
        return "BANNED"

    if first_image_url:
        logging.info(f"Starting concurrent download to {save_dir}/ ...")
        success = download_sequential_images(first_image_url, save_dir, progress_callback)
        if success == "BANNED":
            return "BANNED"
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
        
    # Reverse the chapters list to download oldest first (chapter 1 -> chapter 1000)
    chapters.reverse() 
    total_chapters = len(chapters)
    logging.info(f"Found {total_chapters} chapters to download.")
    
    with sync_playwright() as p:
        try:
            # Reusing browser instance across all downloads
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=get_random_user_agent())
            
            for idx in range(total_chapters):
                chapter = chapters[idx]
                ch_name = sanitize_filename(chapter.get("chapter_name", f"chapter_{idx}"))
                ch_url = chapter.get("chapter_url")
                group = sanitize_filename(chapter.get("group", ""))
                
                folder_name = ch_name
                if group:
                    folder_name += f" [{group}]"
                    
                save_dir = os.path.join(base_dir, folder_name)
                
                # Check complete marker in case folder was manually managed
                if os.path.exists(os.path.join(save_dir, ".complete")):
                    logging.info(f"Chapter {idx+1}/{total_chapters} ({folder_name}) already fully downloaded. Skipping.")
                    continue
                    
                logging.info(f"\n--- Processing {idx+1}/{total_chapters}: {folder_name} ---")
                
                success = download_chapter(page, ch_url, save_dir)
                if success == "BANNED":
                    logging.error("Banned by Cloudflare. Stopping batch download.")
                    break
                    
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