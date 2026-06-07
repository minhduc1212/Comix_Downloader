import os
import sys

import src.downloader as downloader
from playwright.sync_api import sync_playwright

def download_single_chapter(ch_name, ch_url, group, base_save_path):
    try:
        ch_name_safe = downloader.sanitize_filename(ch_name)
        group_safe = downloader.sanitize_filename(group) if group else ""
        
        folder_name = ch_name_safe
        if group_safe:
            folder_name += f" [{group_safe}]"
            
        save_dir = os.path.join(base_save_path, folder_name)
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        if os.path.exists(os.path.join(save_dir, ".complete")):
            return True
            
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            from .utils import get_random_user_agent
            page = browser.new_page(user_agent=get_random_user_agent())
            success = downloader.download_chapter(page, ch_url, save_dir)
            browser.close()
            
        return success
    except Exception as e:
        print(f"Download failed: {e}")
        return False
