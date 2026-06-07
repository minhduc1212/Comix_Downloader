import customtkinter as ctk
import tkinter.messagebox as messagebox
from tkinter import filedialog
import threading
import requests
from io import BytesIO
from PIL import Image
from .api import get_metadata_app, get_chapters_page
from .downloader import download_chapter, sanitize_filename
import queue
import re
import os
import json
import logging


ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Comix Downloader")
        self.geometry("900x700")
        self.minsize(800, 600)

        self.current_url = ""
        self.current_page = 1
        self.save_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        if not os.path.exists(self.save_path):
            os.makedirs(self.save_path)
        self.chapters_data = []
        self.group_options = ["All Groups"]
        
        # Queue system for serializing downloads to reuse browser
        self.download_queue = queue.Queue()
        self.worker_thread = None
        self.worker_lock = threading.Lock()
        self.stop_worker = False

        # -- UI LAYOUT --
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 1. Top Frame: URL input
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        self.url_label = ctk.CTkLabel(self.top_frame, text="Manga URL:")
        self.url_label.grid(row=0, column=0, padx=10, pady=10)

        self.url_entry = ctk.CTkEntry(self.top_frame, placeholder_text="https://comix.to/title/...")
        self.url_entry.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="ew")

        self.get_btn = ctk.CTkButton(self.top_frame, text="Get Info", command=self.on_get_clicked)
        self.get_btn.grid(row=0, column=2, padx=10, pady=10)

        # 2. Left Frame: Metadata (Cover, Title, Desc)
        self.left_frame = ctk.CTkFrame(self, width=250)
        self.left_frame.grid(row=1, column=0, rowspan=2, padx=(10, 5), pady=5, sticky="nsew")

        self.cover_label = ctk.CTkLabel(self.left_frame, text="Cover Image", width=200, height=300, bg_color="gray")
        self.cover_label.pack(padx=10, pady=10)

        self.title_label = ctk.CTkLabel(self.left_frame, text="Title", font=ctk.CTkFont(size=16, weight="bold"), wraplength=220)
        self.title_label.pack(padx=10, pady=(0, 5))

        self.desc_textbox = ctk.CTkTextbox(self.left_frame, width=220, height=200, wrap="word")
        self.desc_textbox.pack(padx=10, pady=5, fill="both", expand=True)
        self.desc_textbox.insert("0.0", "Description will appear here.")
        self.desc_textbox.configure(state="disabled")

        # 3. Middle Frame: Controls for downloading & pagination
        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.grid(row=1, column=1, padx=(5, 10), pady=5, sticky="ew")
        self.controls_frame.grid_columnconfigure(0, weight=1)
        self.controls_frame.grid_columnconfigure(1, weight=1)

        self.path_label = ctk.CTkLabel(self.controls_frame, text=f"Save Path: {self.save_path}", anchor="w")
        self.path_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")

        self.change_path_btn = ctk.CTkButton(self.controls_frame, text="Change Path", command=self.change_save_path, width=120)
        self.change_path_btn.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="e")

        self.group_combo = ctk.CTkOptionMenu(self.controls_frame, values=self.group_options, command=self.on_group_changed)
        self.group_combo.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")

        self.download_all_btn = ctk.CTkButton(self.controls_frame, text="Download Whole Manga", command=self.download_whole_manga)
        self.download_all_btn.grid(row=1, column=1, padx=10, pady=(5, 10), sticky="ew")

        # 4. Right Frame: Chapters list
        self.chapters_frame = ctk.CTkScrollableFrame(self, label_text="Chapters")
        self.chapters_frame.grid(row=2, column=1, padx=(5, 10), pady=5, sticky="nsew")
        self.chapters_frame.grid_columnconfigure(0, weight=1)

        # 5. Bottom Frame: Pagination
        self.pagination_frame = ctk.CTkFrame(self)
        self.pagination_frame.grid(row=3, column=1, padx=(5, 10), pady=(5, 10), sticky="ew")
        
        self.prev_btn = ctk.CTkButton(self.pagination_frame, text="<- Prev", width=60, command=self.prev_page, state="disabled")
        self.prev_btn.pack(side="left", padx=10, pady=10)

        self.page_label = ctk.CTkLabel(self.pagination_frame, text="Page 1")
        self.page_label.pack(side="left", expand=True, pady=10)

        self.next_btn = ctk.CTkButton(self.pagination_frame, text="Next ->", width=60, command=self.next_page, state="disabled")
        self.next_btn.pack(side="right", padx=10, pady=10)

        # 6. Status Frame
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=4, column=1, padx=(5, 10), pady=(0, 10), sticky="ew")
        
        self.status_label = ctk.CTkLabel(self.status_frame, text="Idle", text_color="gray")
        self.status_label.pack(side="left", padx=10, pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(self.status_frame, mode="indeterminate")
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=10, pady=5)
        self.progress_bar.set(0)

    def change_save_path(self):
        directory = filedialog.askdirectory(initialdir=self.save_path)
        if directory:
            self.save_path = directory
            self.path_label.configure(text=f"Save Path: {self.save_path}")

    def on_get_clicked(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a URL")
            return
            
        self.current_url = url
        self.current_page = 1
        self.all_chapters = []
        self.group_options = ["All Groups"]
        self.group_combo.configure(values=self.group_options)
        self.group_combo.set("All Groups")
        
        # Reset UI
        self.title_label.configure(text="Loading...")
        self.desc_textbox.configure(state="normal")
        self.desc_textbox.delete("0.0", "end")
        self.desc_textbox.insert("0.0", "Loading...")
        self.desc_textbox.configure(state="disabled")
        self.get_btn.configure(state="disabled")
        
        for widget in self.chapters_frame.winfo_children():
            widget.destroy()
        loading_label = ctk.CTkLabel(self.chapters_frame, text="Loading info and chapters...")
        loading_label.grid(row=0, column=0, pady=20)
        
        self.prev_btn.configure(state="disabled")
        self.next_btn.configure(state="disabled")
        
        # Start background thread to load all info and chapters
        threading.Thread(target=self.fetch_info_thread, args=(url,), daemon=True).start()

    def fetch_info_thread(self, url):
        # 1. Fetch metadata first to show on the UI
        metadata = get_metadata_app(url)
        self.after(0, self.update_metadata_ui, metadata)
        
        if "error" in metadata:
            self.after(0, lambda: self.get_btn.configure(state="normal"))
            self.after(0, self.clear_loading_label)
            return
            
        # 2. Extract slug for progress file
        match = re.search(r'/title/([^/]+)', url)
        slug = match.group(1) if match else "unknown"
        progress_file = f"progress_{slug}.json"
        
        # 3. Load existing chapters if file exists
        local_chapters = []
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    local_chapters = data.get("chapters", [])
                logging.info(f"Loaded {len(local_chapters)} chapters from local file.")
                # Show the loaded chapters instantly on the UI!
                self.after(0, self.display_local_chapters, local_chapters)
            except Exception as e:
                logging.error(f"Error loading local progress file: {e}")
                
        # 4. Crawl the website to check for new chapters / fetch all chapters
        self.after(0, lambda: self.status_label.configure(text="Checking for new chapters..."))
        
        from playwright.sync_api import sync_playwright
        from .utils import get_random_user_agent, random_delay
        
        all_chapters = list(local_chapters)
        existing_urls = {c["chapter_url"] for c in all_chapters}
        
        new_chapters = []
        page_num = 1
        banned = False
        
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=get_random_user_agent())
                
                # Route filter to block trackers and images to make it super fast
                def route_filter(route):
                    resource_type = route.request.resource_type
                    url_str = route.request.url
                    if resource_type in ["media", "image"]:
                        route.abort()
                    elif any(tracker in url_str for tracker in ["google-analytics", "doubleclick", "facebook", "analytics", "ads", "whos.amung.us"]):
                        route.abort()
                    else:
                        route.continue_()
                try:
                    page.route("**/*", route_filter)
                except Exception:
                    pass
                    
                while True:
                    separator = "&" if "?" in url else "?"
                    page_url = f"{url}{separator}page={page_num}"
                    self.after(0, lambda p=page_num: self.status_label.configure(text=f"Fetching chapters: Page {p}..."))
                    
                    try:
                        random_delay(0.5, 1.5)
                        page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
                        if "Just a moment" in page.title() or "Cloudflare" in page.title():
                            banned = True
                            break
                        page.wait_for_selector('.mchap-item', timeout=5000)
                    except Exception:
                        # Timeout or no chapters on this page -> we reached the end of the pages
                        break
                        
                    # Parse chapters on this page
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(page.content(), 'html.parser')
                    items = soup.find_all('li', class_='mchap-item')
                    if not items:
                        break
                        
                    page_results = []
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
                                
                        page_results.append({
                            "chapter_name": chapter_name,
                            "chapter_url": chapter_url,
                            "group": group
                        })
                    
                    # Check if we have seen these chapters
                    any_new_in_page = False
                    for r in page_results:
                        if r["chapter_url"] not in existing_urls:
                            new_chapters.append(r)
                            existing_urls.add(r["chapter_url"])
                            any_new_in_page = True
                            
                    # If this page contains NO new chapters and we already have some chapters,
                    # we can stop crawling immediately because we have reached the previously crawled chapters!
                    if not any_new_in_page and len(local_chapters) > 0:
                        logging.info("Found no new chapters on this page, stopping crawl.")
                        break
                        
                    page_num += 1
                    
                browser.close()
            except Exception as e:
                logging.error(f"Error in chapter crawling thread: {e}")
                
        self.after(0, lambda: self.get_btn.configure(state="normal"))
        self.after(0, lambda: self.status_label.configure(text="Idle"))
        
        if banned:
            self.after(0, lambda: messagebox.showerror("Access Denied", "Cloudflare Challenge or IP Ban detected while fetching chapters.\nPlease wait a few minutes or use a VPN."))
            return
            
        # Prepend new chapters to the beginning of the list (since they are newest)
        if new_chapters:
            all_chapters = new_chapters + local_chapters
            # Save to progress file
            try:
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump({"next_page": page_num, "chapters": all_chapters}, f, indent=4)
                logging.info(f"Progress saved to {progress_file}. Total chapters: {len(all_chapters)}")
            except Exception as e:
                logging.error(f"Failed to save progress to {progress_file}: {e}")
        else:
            all_chapters = local_chapters
            # In case it is a new crawl and there was no local progress file
            if not os.path.exists(progress_file) and all_chapters:
                try:
                    with open(progress_file, 'w', encoding='utf-8') as f:
                        json.dump({"next_page": page_num, "chapters": all_chapters}, f, indent=4)
                except Exception as e:
                    logging.error(f"Failed to save progress: {e}")
                
        self.after(0, self.display_local_chapters, all_chapters)

    def clear_loading_label(self):
        for widget in self.chapters_frame.winfo_children():
            widget.destroy()

    def update_metadata_ui(self, metadata):
        if "error" in metadata:
            if metadata["error"] == "BANNED":
                messagebox.showerror("Access Denied", "Cloudflare Challenge or IP Ban detected from the website.\n\nPlease wait a few minutes, clear your IP limit, or try using a VPN.")
            else:
                messagebox.showerror("Error", metadata["error"])
            return
            
        title = metadata.get("title", "Unknown")
        desc = metadata.get("desc", "No description.")
        img_url = metadata.get("img")
        
        self.title_label.configure(text=title)
        
        self.desc_textbox.configure(state="normal")
        self.desc_textbox.delete("0.0", "end")
        self.desc_textbox.insert("0.0", desc)
        self.desc_textbox.configure(state="disabled")
        
        if img_url:
            threading.Thread(target=self.load_image_thread, args=(img_url,), daemon=True).start()
            
    def load_image_thread(self, img_url):
        try:
            response = requests.get(img_url)
            if response.status_code == 200:
                img_data = response.content
                image = Image.open(BytesIO(img_data))
                ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(200, 300))
                self.after(0, lambda: self.cover_label.configure(image=ctk_image, text=""))
        except Exception as e:
            print(f"Error loading image: {e}")

    def display_local_chapters(self, all_chapters):
        self.all_chapters = all_chapters
        
        # Update scanlation group options in the combo menu
        new_groups_found = False
        for chap in all_chapters:
            g = chap.get("group", "")
            if g and g not in self.group_options:
                self.group_options.append(g)
                new_groups_found = True
                
        if new_groups_found:
            self.group_combo.configure(values=self.group_options)
            
        self.render_chapters_page()

    def on_group_changed(self, choice):
        self.current_page = 1
        self.render_chapters_page()

    def render_chapters_page(self):
        for widget in self.chapters_frame.winfo_children():
            widget.destroy()
            
        selected_group = self.group_combo.get()
        
        # Filter chapters by group
        filtered_chapters = self.all_chapters
        if selected_group != "All Groups":
            filtered_chapters = [c for c in self.all_chapters if c.get("group", "") == selected_group]
            
        page_size = 20
        total_filtered = len(filtered_chapters)
        total_pages = max(1, (total_filtered + page_size - 1) // page_size)
        
        # Clamp current_page
        if self.current_page > total_pages:
            self.current_page = total_pages
        if self.current_page < 1:
            self.current_page = 1
            
        self.page_label.configure(text=f"Page {self.current_page} of {total_pages}")
        
        # Enable/disable pagination buttons
        self.prev_btn.configure(state="normal" if self.current_page > 1 else "disabled")
        self.next_btn.configure(state="normal" if self.current_page < total_pages else "disabled")
        
        # Slice for the current page
        start_idx = (self.current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total_filtered)
        page_chapters = filtered_chapters[start_idx:end_idx]
        
        self.chapter_buttons = getattr(self, "chapter_buttons", {})
        
        if not page_chapters:
            lbl = ctk.CTkLabel(self.chapters_frame, text="No chapters found.")
            lbl.grid(row=0, column=0, pady=20)
            return
            
        for i, chap in enumerate(page_chapters):
            frame = ctk.CTkFrame(self.chapters_frame)
            frame.grid(row=i, column=0, padx=5, pady=5, sticky="ew")
            frame.grid_columnconfigure(0, weight=1)
            
            name_text = chap.get("chapter_name", "")
            if chap.get("group"):
                name_text += f" [{chap['group']}]"
                
            lbl = ctk.CTkLabel(frame, text=name_text, anchor="w")
            lbl.grid(row=0, column=0, padx=10, pady=5, sticky="w")
            
            # Check complete status from disk
            match = re.search(r'/title/([^/]+)', self.current_url)
            slug = match.group(1) if match else "unknown"
            base_dir = os.path.join(self.save_path, slug)
            
            ch_name_safe = sanitize_filename(chap.get("chapter_name", "Unknown"))
            group_safe = sanitize_filename(chap.get("group", ""))
            folder_name = ch_name_safe
            if group_safe:
                folder_name += f" [{group_safe}]"
            save_dir = os.path.join(base_dir, folder_name)
            
            is_done = os.path.exists(os.path.join(save_dir, ".complete"))
            
            btn_text = "Done" if is_done else "Download"
            btn_state = "disabled" if is_done else "normal"
            
            btn = ctk.CTkButton(frame, text=btn_text, width=80, state=btn_state,
                                command=lambda c=chap: self.download_chapter(c))
            btn.grid(row=0, column=1, padx=10, pady=5)
            
            self.chapter_buttons[chap.get("chapter_url")] = btn

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.render_chapters_page()

    def next_page(self):
        self.current_page += 1
        self.render_chapters_page()

    def start_worker_if_needed(self):
        with self.worker_lock:
            if self.worker_thread is None or not self.worker_thread.is_alive():
                self.stop_worker = False
                self.worker_thread = threading.Thread(target=self.queue_worker_loop, daemon=True)
                self.worker_thread.start()

    def queue_worker_loop(self):
        from playwright.sync_api import sync_playwright
        from .utils import get_random_user_agent
        
        with sync_playwright() as p:
            browser = None
            page = None
            try:
                while not self.stop_worker:
                    try:
                        # Get a chapter task from the queue, wait up to 1 second
                        chap_task = self.download_queue.get(timeout=1.0)
                    except queue.Empty:
                        break
                        
                    ch_name = chap_task.get("chapter_name", "Unknown")
                    ch_url = chap_task.get("chapter_url")
                    group = chap_task.get("group", "")
                    
                    q_size = self.download_queue.qsize()
                    status_text = f"Downloading: {ch_name}"
                    if q_size > 0:
                        status_text += f" ({q_size} in queue)"
                        
                    self.after(0, lambda s=status_text: self.status_label.configure(text=s))
                    self.after(0, lambda: self.progress_bar.start())
                    
                    if browser is None:
                        try:
                            browser = p.chromium.launch(headless=True)
                            page = browser.new_page(user_agent=get_random_user_agent())
                        except Exception as e:
                            print(f"Error launching browser: {e}")
                            self.download_queue.task_done()
                            continue
                            
                    # Target folder
                    match = re.search(r'/title/([^/]+)', self.current_url)
                    slug = match.group(1) if match else "unknown"
                    base_dir = os.path.join(self.save_path, slug)
                    
                    ch_name_safe = sanitize_filename(ch_name)
                    group_safe = sanitize_filename(group) if group else ""
                    folder_name = ch_name_safe
                    if group_safe:
                        folder_name += f" [{group_safe}]"
                    save_dir = os.path.join(base_dir, folder_name)
                    
                    def progress_cb(img_idx, name=ch_name, size=q_size):
                        lbl_text = f"Downloading {name}: Image {img_idx}"
                        if size > 0:
                            lbl_text += f" ({size} in queue)"
                        self.after(0, lambda t=lbl_text: self.status_label.configure(text=t))
                        
                    success = False
                    if os.path.exists(os.path.join(save_dir, ".complete")):
                        success = True
                    else:
                        try:
                            success = download_chapter(page, ch_url, save_dir, progress_cb)
                        except Exception as e:
                            print(f"Error downloading chapter {ch_name}: {e}")
                            success = False
                            
                    self.after(0, lambda: self.progress_bar.stop())
                    self.after(0, lambda: self.status_label.configure(text="Idle"))
                    
                    if success == "BANNED":
                        print(f"Banned during: {ch_name}")
                        self.after(0, lambda: messagebox.showerror(
                            "Access Denied", 
                            "Cloudflare Challenge or IP Ban detected during download.\nPlease wait a few minutes or use a VPN."
                        ))
                        # Clear remaining queue on ban
                        while not self.download_queue.empty():
                            try:
                                self.download_queue.get_nowait()
                                self.download_queue.task_done()
                            except queue.Empty:
                                break
                        break
                    elif success:
                        print(f"Downloaded: {ch_name}")
                        chap_task["downloaded"] = True
                        btn = getattr(self, "chapter_buttons", {}).get(ch_url)
                        if btn:
                            self.after(0, lambda b=btn: b.configure(text="Done", state="disabled"))
                    else:
                        print(f"Failed to download chapter: {ch_name}")
                        
                    self.download_queue.task_done()
            finally:
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
        self.after(0, lambda: self.status_label.configure(text="Idle"))

    def download_chapter(self, chap):
        self.download_queue.put(chap)
        self.start_worker_if_needed()


    def download_whole_manga(self):
        selected_group = self.group_combo.get()
        count = 0
        for chap in self.all_chapters:
            if selected_group != "All Groups" and chap.get("group", "") != selected_group:
                continue
            self.download_chapter(chap)
            count += 1
        if count > 0:
            messagebox.showinfo("Info", f"Queued {count} chapters for download.")
