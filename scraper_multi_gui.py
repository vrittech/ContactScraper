#!/usr/bin/env python3
"""
Contact Scraper Desktop UI – Multithreaded
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import json
import csv
import os
import re
import queue
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

# ----------------------------------------------------------------------
# Import the scraper (the huge script you posted earlier)
# ----------------------------------------------------------------------
try:
    from scraper_v3 import ContactScraper, MapsScraper, save_results
except Exception as e:
    messagebox.showerror(
        "Import Error",
        f"Could not import scraper.py\n{e}\nMake sure it is in the same folder."
    )
    raise SystemExit(1)


# ----------------------------------------------------------------------
# Helper wrappers – keep the scraper code untouched
# ----------------------------------------------------------------------
def scrape_one_site(url: str) -> dict:
    """Run ContactScraper on a single URL and return its dict result."""
    scraper = ContactScraper(url)
    return scraper.run()


def get_maps_sites(keywords: str, limit: int) -> list[str]:
    """Run MapsScraper and return the list of website URLs."""
    maps = MapsScraper(keywords, limit=limit)
    return maps.run()


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class ScraperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Contact Scraper")
        self.root.geometry("980x720")
        self.root.minsize(800, 600)

        # style
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.bg_color = "#f5f5f5"
        self.root.configure(bg=self.bg_color)
        self.tree_font = ("Consolas", 13)

        # vars
        self.mode_var = tk.StringVar(value="url")
        self.url_var = tk.StringVar()
        self.keywords_var = tk.StringVar()
        self.num_sites_var = tk.IntVar(value=4)
        self.max_workers_var = tk.IntVar(value=12)
        self.save_results_var = tk.BooleanVar(value=True)
        self.file_path_var = tk.StringVar()

        self.is_running = False
        self.executor: ThreadPoolExecutor | None = None
        self.futures: dict[Future, str] = {}   # future → site URL
        self.results: list[dict] = []

        self.log_queue: queue.Queue = queue.Queue()
        self.result_queue: queue.Queue = queue.Queue()

        self.total_sites = 0
        self.completed = 0

        self.setup_ui()
        self.process_queues()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def setup_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        self.create_header(main)
        self.create_input_section(main)
        self.create_log_section(main)
        self.create_bottom_buttons(main)

    def create_header(self, parent):
        f = ttk.Frame(parent)
        f.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        tk.Label(
            f, text="Contact Scraper", font=("Helvetica", 20, "bold"),
            bg=self.bg_color, fg="#2196F3"
        ).pack()
        tk.Label(
            f, text="Extracts emails & phone numbers",
            font=("Helvetica", 20), bg=self.bg_color, fg="#666"
        ).pack()

    def create_input_section(self, parent):
        f = ttk.LabelFrame(parent, text="Configuration", padding=10)
        f.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        f.columnconfigure(1, weight=1)

        # ---- mode ----
        ttk.Label(f, text="Scraping Mode:", font=("Helvetica", 20, "bold")).grid(
            row=0, column=0, sticky="w", pady=5
        )
        mode_f = ttk.Frame(f)
        mode_f.grid(row=0, column=1, sticky="w", pady=5)
        for txt, val in [
            ("Single URL", "url"),
            ("Google Maps Search", "keywords"),
            ("File (URLs)", "file"),
        ]:
            ttk.Radiobutton(
                mode_f, text=txt, variable=self.mode_var, value=val,
                command=self.on_mode_change
            ).pack(side="left", padx=5)

        # ---- URL ----
        self.url_lbl = ttk.Label(f, text="Website URL:")
        self.url_ent = ttk.Entry(f, textvariable=self.url_var, width=55)

        # ---- Keywords ----
        self.kw_lbl = ttk.Label(f, text="Search Keywords:")
        self.kw_ent = ttk.Entry(f, textvariable=self.keywords_var, width=55)

        # ---- Number of sites ----
        self.num_lbl = ttk.Label(f, text="Number of Sites:")
        self.num_spn = ttk.Spinbox(
            f, from_=1, to=50, textvariable=self.num_sites_var, width=10
        )

        # ---- File ----
        self.file_lbl = ttk.Label(f, text="File with URLs:")
        self.file_fr = ttk.Frame(f)
        self.file_ent = ttk.Entry(self.file_fr, textvariable=self.file_path_var,
                                 state="readonly", width=45)
        self.file_ent.pack(side="left", fill="x", expand=True)
        ttk.Button(self.file_fr, text="Browse...", command=self.browse_file).pack(
            side="left", padx=(5, 0)
        )

        # ---- Workers ----
        self.workers_lbl = ttk.Label(f, text="Max Threads:")
        self.workers_spn = ttk.Spinbox(
            f, from_=1, to=30, textvariable=self.max_workers_var, width=10
        )

        # ---- Save checkbox ----
        ttk.Checkbutton(
            f, text="Save results to JSON/CSV", variable=self.save_results_var
        ).grid(row=99, column=0, columnspan=2, sticky="w", pady=10)

        self.on_mode_change()   # initial visibility

    def create_log_section(self, parent):
        f = ttk.LabelFrame(parent, text="Logs & Results", padding=10)
        f.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        nb = ttk.Notebook(f)
        nb.grid(row=0, column=0, sticky="nsew")

        # ---- Log tab ----
        log_tab = ttk.Frame(nb)
        nb.add(log_tab, text="Console Logs")
        self.log_txt = scrolledtext.ScrolledText(
            log_tab, wrap="word", font=("Consolas", 13),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        self.log_txt.pack(fill="both", expand=True)
        for tag, fg in [
            ("info", "#4EC9B0"),
            ("success", "#4CAF50"),
            ("error", "#f44336"),
            ("warning", "#FF9800"),
        ]:
            self.log_txt.tag_config(tag, foreground=fg)

        # ---- Results tab ----
        res_tab = ttk.Frame(nb)
        nb.add(res_tab, text="Results")
        tree_fr = ttk.Frame(res_tab)
        tree_fr.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical")
        hsb = ttk.Scrollbar(tree_fr, orient="horizontal")
        self.tree = ttk.Treeview(
            tree_fr,
            columns=("Website", "Emails", "Phones"),
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        self.tree.heading("Website", text="Website")
        self.tree.heading("Emails", text="Emails")
        self.tree.heading("Phones", text="Phone Numbers")
        self.tree.column("Website", width=300)
        self.tree.column("Emails", width=300)
        self.tree.column("Phones", width=250)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

    def create_bottom_buttons(self, parent):
        f = ttk.Frame(parent)
        f.grid(row=3, column=0, sticky="ew")

        self.start_btn = tk.Button(
            f, text="Start Scraping", command=self.start_scraping,
            bg="#4CAF50", fg="white", font=("Helvetica", 11, "bold"),
            padx=20, pady=8, relief="flat", cursor="hand2"
        )
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = tk.Button(
            f, text="Stop", command=self.stop_scraping,
            bg="#f44336", fg="white", font=("Helvetica", 11, "bold"),
            padx=20, pady=8, relief="flat", cursor="hand2", state="disabled"
        )
        self.stop_btn.pack(side="left", padx=5)

        tk.Button(
            f, text="Clear Logs", command=self.clear_logs,
            bg="#757575", fg="white", font=("Helvetica", 11),
            padx=15, pady=8, relief="flat", cursor="hand2"
        ).pack(side="left", padx=5)

        tk.Button(
            f, text="Export Results", command=self.export_results,
            bg="#2196F3", fg="white", font=("Helvetica", 11),
            padx=15, pady=8, relief="flat", cursor="hand2"
        ).pack(side="right", padx=5)

        self.status_lbl = tk.Label(
            f, text="Ready", font=("Helvetica", 10), bg=self.bg_color, fg="#666"
        )
        self.status_lbl.pack(side="right", padx=10)

        self.progress = ttk.Progressbar(f, mode="determinate")
        self.progress.pack(side="right", fill="x", expand=True, padx=10)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def on_mode_change(self):
        mode = self.mode_var.get()
        # hide everything
        for w in (
            self.url_lbl, self.url_ent,
            self.kw_lbl, self.kw_ent,
            self.num_lbl, self.num_spn,
            self.file_lbl, self.file_fr,
            self.workers_lbl, self.workers_spn,
        ):
            w.grid_remove()

        if mode == "url":
            self.url_lbl.grid(row=1, column=0, sticky="w", pady=5)
            self.url_ent.grid(row=1, column=1, sticky="ew", pady=5, padx=5)
        elif mode == "keywords":
            self.kw_lbl.grid(row=1, column=0, sticky="w", pady=5)
            self.kw_ent.grid(row=1, column=1, sticky="ew", pady=5, padx=5)
            self.num_lbl.grid(row=2, column=0, sticky="w", pady=5)
            self.num_spn.grid(row=2, column=1, sticky="w", pady=5, padx=5)
            self.workers_lbl.grid(row=3, column=0, sticky="w", pady=5)
            self.workers_spn.grid(row=3, column=1, sticky="w", pady=5, padx=5)
        elif mode == "file":
            self.file_lbl.grid(row=1, column=0, sticky="w", pady=5)
            self.file_fr.grid(row=1, column=1, sticky="ew", pady=5, padx=5)
            self.workers_lbl.grid(row=2, column=0, sticky="w", pady=5)
            self.workers_spn.grid(row=2, column=1, sticky="w", pady=5, padx=5)

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Select file with URLs",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.file_path_var.set(path)

    # ------------------------------------------------------------------
    # Thread-safe logging / result handling
    # ------------------------------------------------------------------
    def log(self, msg: str, tag: str = "info"):
        self.log_queue.put((msg, tag))

    def add_result(self, res: dict):
        self.result_queue.put(res)

    def process_queues(self):
        # logs
        while True:
            try:
                msg, tag = self.log_queue.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                self.log_txt.insert("end", f"[{ts}] {msg}\n", tag)
                self.log_txt.see("end")
            except queue.Empty:
                break

        # results
        while True:
            try:
                res = self.result_queue.get_nowait()
                self.results.append(res)
                self._insert_tree_row(res)
                self.completed += 1
                self.progress["value"] = (self.completed / self.total_sites) * 100
                self.status_lbl.config(
                    text=f"Completed: {self.completed}/{self.total_sites}"
                )
            except queue.Empty:
                break

        self.root.after(100, self.process_queues)

    def _insert_tree_row(self, res: dict):
        emails = ", ".join(res.get("emails", [])) if isinstance(res.get("emails"), list) else res.get("emails", "")
        phones = ", ".join(res.get("numbers", [])) if isinstance(res.get("numbers"), list) else res.get("numbers", "")
        item = self.tree.insert("", "end", values=(res["website"], emails, phones), )
        self.tree.item(item, tags=("row",))

    # Apply font to the whole row
        self.tree.tag_configure("row", font=self.tree_font)

    def clear_logs(self):
        self.log_txt.delete("1.0", "end")
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.results.clear()
        self.log("Cleared logs & results", "info")

    # ------------------------------------------------------------------
    # Validation & start/stop
    # ------------------------------------------------------------------
    def validate(self) -> bool:
        mode = self.mode_var.get()
        if mode == "url":
            url = self.url_var.get().strip()
            if not url:
                messagebox.showwarning("Input", "Enter a URL")
                return False
            if not url.startswith(("http://", "https://")):
                messagebox.showwarning("URL", "URL must start with http:// or https://")
                return False
        elif mode == "keywords":
            if not self.keywords_var.get().strip():
                messagebox.showwarning("Input", "Enter search keywords")
                return False
        elif mode == "file":
            path = self.file_path_var.get()
            if not path or not os.path.isfile(path):
                messagebox.showerror("File", "Select a valid URL file")
                return False
        return True

    def start_scraping(self):
        if not self.validate():
            return

        # ---- CLEAN PREVIOUS RUN ----
        self._reset_run_state()

        self.is_running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress["value"] = 0
        self.completed = 0
        self.results.clear()
        for i in self.tree.get_children():
            self.tree.delete(i)

        threading.Thread(target=self._scrape_worker, daemon=True).start()

    def _reset_run_state(self):
        """Make sure a brand-new executor is used on every click."""
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None
        self.futures = {}
        self.total_sites = 0
        self.completed = 0

    def stop_scraping(self):
        self.is_running = False
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log("Scraping stopped by user", "warning")


    # ------------------------------------------------------------------
    # Core scraping worker (runs in its own thread)
    # ------------------------------------------------------------------
    def _scrape_worker(self):
        try:
            mode = self.mode_var.get()
            max_workers = self.max_workers_var.get()

            # ---- 1. Gather URLs -------------------------------------------------
            if mode == "url":
                sites = [self.url_var.get().strip()]
                self.total_sites = 1
            elif mode == "keywords":
                self.log(f"Searching Google Maps: {self.keywords_var.get()}", "info")
                sites = get_maps_sites(self.keywords_var.get(),
                                      self.num_sites_var.get())
                self.total_sites = len(sites)
                self.log(f"Found {self.total_sites} sites", "success")
            else:   # file
                path = self.file_path_var.get()
                with open(path, "r", encoding="utf-8") as f:
                    sites = [line.strip() for line in f if line.strip()]
                self.total_sites = len(sites)
                self.log(f"Loaded {self.total_sites} URLs from file", "success")

            if not sites:
                self.log("No sites to scrape", "error")
                return

            # ---- 2. **NEW** ThreadPoolExecutor for THIS run --------------------
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
            self.futures = {
                self.executor.submit(scrape_one_site, url): url for url in sites
            }

            # ---- 3. Consume futures --------------------------------------------
            for future in as_completed(self.futures):
                if not self.is_running:
                    break
                url = self.futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"website": url, "emails": "Error", "numbers": "Error"}
                    self.log(f"{url} → {exc}", "error")
                finally:
                    self.add_result(result)

            # ---- 4. Clean shutdown of the pool ---------------------------------
            self.executor.shutdown(wait=True)

            # ---- 5. Auto-save --------------------------------------------------
            if self.save_results_var.get() and self.results:
                self._auto_save()

            self.log("Scraping finished", "success")
        except Exception as e:
            self.log(f"Fatal error: {e}", "error")
        finally:
            self.root.after(0, self._finished)




    def _finished(self):
        self.is_running = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress["value"] = 100
        self.status_lbl.config(text="Finished")
        # **IMPORTANT** – release the executor so the next run gets a fresh one
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None
        self.futures = {}


    # ------------------------------------------------------------------
    # Export / auto-save
    # ------------------------------------------------------------------
    def _auto_save(self):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base = {
            "url": "single",
            "keywords": re.sub(r"[^\w\-_]", "_", self.keywords_var.get()),
            "file": "file",
        }[self.mode_var.get()]

        name = f"contacts_[{base}]_{timestamp}"
        save_results(self.results, name)
        self.log(f"Auto-saved → json_data/{name}.json", "success")

    def export_results(self):
        if not self.results:
            messagebox.showinfo("Export", "No results to export")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("CSV", "*.csv")]
        )
        if not path:
            return
        try:
            if path.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.results, f, indent=2, ensure_ascii=False)
            else:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=self.results[0].keys())
                    w.writeheader()
                    w.writerows(self.results)
            self.log(f"Exported → {path}", "success")
            messagebox.showinfo("Export", f"Saved to\n{path}")
        except Exception as e:
            self.log(f"Export error: {e}", "error")
            messagebox.showerror("Export", str(e))


# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = ScraperGUI(root)
    root.mainloop()
