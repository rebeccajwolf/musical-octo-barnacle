import argparse
import csv
import json
import logging
import logging.config
import logging.handlers as handlers
import random
import schedule
import re
import sys
import traceback
import subprocess
import time
import yaml
import gradio as gr
import psutil
import threading
import numpy as np
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime
from enum import Enum, auto
from threading import Thread, Event
from pathlib import Path
import requests
import os
import wget
import zipfile
from queue import Queue
import signal
import ctypes
from contextlib import contextmanager

from src import (
    Browser,
    Login,
    PunchCards,
    Searches,
    ReadToEarn,
    Account,
)
from src.activities import Activities
from src.browser import RemainingSearches
from src.loggingColoredFormatter import ColoredFormatter
from src.utils import Utils, CONFIG, sendNotification, getProjectRoot, formatNumber

# Global event for coordinating shutdown
shutdown_event = Event()
activity_queue = Queue()

class ContainerMonitor:
    def __init__(self):
        self.running = True
        self._activity_thread = None
        self._resource_thread = None
        self._last_activity = time.time()
        
    def start(self):
        self._activity_thread = threading.Thread(target=self._simulate_background_tasks)
        self._activity_thread.daemon = True
        self._activity_thread.start()
        
        self._resource_thread = threading.Thread(target=self._maintain_system_state)
        self._resource_thread.daemon = True
        self._resource_thread.start()
        
    def _simulate_background_tasks(self):
        """Simulates legitimate background tasks"""
        while self.running:
            try:
                # Simulate normal system operations
                if time.time() - self._last_activity > 60:
                    # Light file operations
                    with open('/tmp/system.log', 'a') as f:
                        f.write(f"{datetime.now().isoformat()}\n")
                    
                    # Minimal CPU usage
                    data = [random.random() for _ in range(100)]
                    sorted(data)
                    
                    self._last_activity = time.time()
                
                time.sleep(random.uniform(30, 60))
                
            except Exception:
                time.sleep(5)
                
    def _maintain_system_state(self):
        """Maintains system state without suspicious patterns"""
        while self.running:
            try:
                # Update activity timestamp
                Path('/tmp/activity').touch(exist_ok=True)
                
                # Light memory operations
                cache = []
                for _ in range(10):
                    cache.append(os.urandom(1024))
                cache.clear()
                
                time.sleep(random.uniform(45, 75))
                
            except Exception:
                time.sleep(5)
    
    def stop(self):
        self.running = False
        if self._activity_thread:
            self._activity_thread.join(timeout=2)
        if self._resource_thread:
            self._resource_thread.join(timeout=2)

class BrowserManager:
    def __init__(self):
        self.keep_alive = ContainerMonitor()
        self._display = None
        
    def setup(self):
        try:
            self.keep_alive.start()
            
            # Configure environment
            os.environ['PYTHONUNBUFFERED'] = '1'
            # os.environ['DISPLAY'] = ':99'
            
            # Start virtual display more naturally
            self._setup_virtual_display()
            
        except Exception as e:
            logging.error(f"Browser setup error: {str(e)}")
            raise
            
    def _setup_virtual_display(self):
        """Sets up virtual display with randomized parameters"""
        try:
            # Use subprocess with shell=False for better security
            display_cmd = [
                'Xvfb', ':0', 
                '-screen', '0', f'{random.randint(1024, 1920)}x{random.randint(768, 1080)}x24',
                '-ac'
            ]
            self._display = subprocess.Popen(
                display_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            time.sleep(1)  # Brief pause for display to initialize
            
        except Exception as e:
            logging.error(f"Virtual display setup error: {str(e)}")
            raise
        
    def cleanup(self):
        try:
            if self.keep_alive:
                self.keep_alive.stop()
            
            if self._display:
                self._display.terminate()
                self._display.wait(timeout=5)
                
        except Exception as e:
            logging.error(f"Cleanup error: {str(e)}")

# Global browser manager
browser_manager = BrowserManager()

def executeBot(currentAccount: Account, args: argparse.Namespace) -> int:
    """Execute the bot for a single account and return earned points"""
    logging.info(f"********************{currentAccount.username}********************")

    startingPoints: int | None = None
    accountPoints: int = 0
    remainingSearches: RemainingSearches | None = None
    goalTitle: str = ""
    goalPoints: int = 0

    if args.searchtype in ("desktop", None):
        with Browser(mobile=False, account=currentAccount, args=args) as desktopBrowser:
            utils = desktopBrowser.utils
            Login(desktopBrowser, args).login()
            startingPoints = utils.getAccountPoints()
            logging.info(
                f"[POINTS] You have {formatNumber(startingPoints)} points on your account"
            )
            Activities(desktopBrowser).completeActivities()
            PunchCards(desktopBrowser).completePunchCards()

            with Searches(desktopBrowser) as searches:
                searches.bingSearches()

            goalPoints = utils.getGoalPoints()
            goalTitle = utils.getGoalTitle()

            remainingSearches = desktopBrowser.getRemainingSearches(
                desktopAndMobile=True
            )
            accountPoints = utils.getAccountPoints()

    if args.searchtype in ("mobile", None):
        with Browser(mobile=True, account=currentAccount, args=args) as mobileBrowser:
            utils = mobileBrowser.utils
            Login(mobileBrowser, args).login()
            if startingPoints is None:
                startingPoints = utils.getAccountPoints()
            ReadToEarn(mobileBrowser).completeReadToEarn()
            with Searches(mobileBrowser) as searches:
                searches.bingSearches()

            goalPoints = utils.getGoalPoints()
            goalTitle = utils.getGoalTitle()

            remainingSearches = mobileBrowser.getRemainingSearches(
                desktopAndMobile=True
            )
            accountPoints = utils.getAccountPoints()

    if startingPoints is not None:
        logging.info(
            f"[POINTS] You have earned {formatNumber(accountPoints - startingPoints)} points this run!"
        )
        logging.info(f"[POINTS] You are now at {formatNumber(accountPoints)} points!")
        
        appriseSummary = AppriseSummary[CONFIG.get("apprise", {}).get("summary", "NEVER")]
        if appriseSummary == AppriseSummary.ALWAYS:
            goalStatus = ""
            if goalPoints > 0:
                logging.info(
                    f"[POINTS] You are now at {(formatNumber((accountPoints / goalPoints) * 100))}% of your "
                    f"goal ({goalTitle})!"
                )
                goalStatus = (
                    f"🎯 Goal reached: {(formatNumber((accountPoints / goalPoints) * 100))}%"
                    f" ({goalTitle})"
                )

            sendNotification(
                "Daily Points Update",
                "\n".join(
                    [
                        f"👤 Account: {currentAccount.username}",
                        f"⭐️ Points earned today: {formatNumber(accountPoints - startingPoints)}",
                        f"💰 Total points: {formatNumber(accountPoints)}",
                        goalStatus,
                    ]
                ),
            )
        elif appriseSummary == AppriseSummary.ON_ERROR and remainingSearches:
            if remainingSearches.getTotal() > 0:
                sendNotification(
                    "Error: remaining searches",
                    f"account username: {currentAccount.username}, {remainingSearches}",
                )

    return accountPoints

def signal_handler(signum, frame):
    logging.info("Received shutdown signal, cleaning up...")
    if hasattr(signal_handler, 'container_monitor'):
        signal_handler.container_monitor.stop()
    sys.exit(0)

def setupLogging():
    _format = "%(asctime)s [%(levelname)s] %(message)s"
    terminalHandler = logging.StreamHandler(sys.stdout)
    terminalHandler.setFormatter(ColoredFormatter(_format))

    logs_directory = getProjectRoot() / "logs"
    logs_directory.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format=_format,
        handlers=[
            handlers.TimedRotatingFileHandler(
                logs_directory / "activity.log",
                when="midnight",
                interval=1,
                backupCount=2,
                encoding="utf-8",
            ),
            terminalHandler,
        ],
    )

    logging.getLogger().setLevel(logging.INFO)

def argumentParser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MS Rewards Farmer")
    parser.add_argument(
        "-v", "--visible", action="store_true", help="Optional: Visible browser"
    )
    parser.add_argument(
        "-l", "--lang", type=str, default=None, help="Optional: Language (ex: en)"
    )
    parser.add_argument(
        "-g", "--geo", type=str, default=None, help="Optional: Geolocation (ex: US)"
    )
    parser.add_argument(
        "-p",
        "--proxy",
        type=str,
        default=None,
        help="Optional: Global Proxy (ex: http://user:pass@host:port)",
    )
    parser.add_argument(
        "-vn",
        "--verbosenotifs",
        action="store_true",
        help="Optional: Send all the logs to the notification service",
    )
    parser.add_argument(
        "-cv",
        "--chromeversion",
        type=int,
        default=None,
        help="Optional: Set fixed Chrome version (ex. 118)",
    )
    parser.add_argument(
        "-da",
        "--disable-apprise",
        action="store_true",
        help="Optional: Disable Apprise, overrides config.yaml, useful when developing",
    )
    parser.add_argument(
        "-t",
        "--searchtype",
        type=str,
        default=None,
        help="Optional: Set to only search in either desktop or mobile (ex: 'desktop' or 'mobile')",
    )
    return parser.parse_args()

def setupAccounts() -> list[Account]:
    def validEmail(email: str) -> bool:
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        return bool(re.match(pattern, email))

    accountPath = getProjectRoot() / "accounts.json"
    if not accountPath.exists():
        accountPath.write_text(
            json.dumps(
                [{"username": "Your Email", "password": "Your Password"}], indent=4
            ),
            encoding="utf-8",
        )
        noAccountsNotice = """
    [ACCOUNT] Accounts credential file "accounts.json" not found.
    [ACCOUNT] A new file has been created, please edit with your credentials and save.
    """
        logging.warning(noAccountsNotice)
        exit(1)
    loadedAccounts: list[Account] = []
    for rawAccount in json.loads(accountPath.read_text(encoding="utf-8")):
        account: Account = Account(**rawAccount)
        if not validEmail(account.username):
            logging.warning(
                f"[CREDENTIALS] Invalid email: {account.username}, skipping this account"
            )
            continue
        loadedAccounts.append(account)
    random.shuffle(loadedAccounts)
    return loadedAccounts

class AppriseSummary(Enum):
    ALWAYS = auto()
    ON_ERROR = auto()
    NEVER = auto()

def run_job_with_activity():
    """Priority-based job execution with container persistence"""
    try:
        # Setup browser environment
        browser_manager.setup()
        
        # Run main job
        main()
        
    except Exception as e:
        logging.exception("Job execution error")
        sendNotification(
            "⚠️ Error occurred, please check the log",
            traceback.format_exc(),
            e
        )
    finally:
        # Cleanup browser environment
        browser_manager.cleanup()

def main():
    args = argumentParser()
    Utils.args = args
    loadedAccounts = setupAccounts()

    previous_points_data = load_previous_points_data()

    for currentAccount in loadedAccounts:
        try:
            earned_points = executeBot(currentAccount, args)
        except Exception as e1:
            logging.error("", exc_info=True)
            sendNotification(
                f"⚠️ Error executing {currentAccount.username}, please check the log",
                traceback.format_exc(),
                e1,
            )
            continue
        previous_points = previous_points_data.get(currentAccount.username, 0)
        points_difference = earned_points - previous_points
        log_daily_points_to_csv(earned_points, points_difference)
        previous_points_data[currentAccount.username] = earned_points
        logging.info(
            f"[POINTS] Data for '{currentAccount.username}' appended to the file."
        )

    save_previous_points_data(previous_points_data)
    logging.info("[POINTS] Data saved for the next day.")

def create_accounts_json_from_env():
    try:
        accounts_str = os.getenv('ACCOUNTS', '')
        if not accounts_str:
            logging.warning("[ACCOUNT] No ACCOUNTS environment variable found")
            return

        accounts = []
        for account_str in accounts_str.split(','):
            if ':' in account_str:
                username, password = account_str.split(':')
                accounts.append({
                    "username": username.strip(),
                    "password": password.strip()
                })
        account_path = getProjectRoot() / "accounts.json"
        with open(account_path, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=4)
            logging.info("[ACCOUNT] Successfully created accounts.json from environment variable")
    except Exception as e:
        logging.error("[ACCOUNT] Error creating accounts.json: %s", str(e))

def create_config_yaml_from_env():
    try:
        token = os.getenv('TOKEN', '')
        if not token:
            logging.warning("[CONFIG] No TOKEN environment variable found")
            return
        config = {
            'apprise': {
                'urls': [token]
            }
        }
        config_path = getProjectRoot() / "config-private.yaml"
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False)
            logging.info("[CONFIG] Successfully created config-private.yaml from environment variable")
    except Exception as e:
        logging.error("[CONFIG] Error creating config-private.yaml: %s", str(e))

def downloadWebDriver():
    download_url = "https://storage.googleapis.com/chrome-for-testing-public/128.0.6613.119/linux64/chromedriver-linux64.zip"
    latest_driver_zip = wget.download(download_url,'chromedriver.zip')
    with zipfile.ZipFile(latest_driver_zip, 'r') as zip_ref:
        zip_ref.extractall()
    os.remove(latest_driver_zip)

def log_daily_points_to_csv(earned_points, points_difference):
    logs_directory = getProjectRoot() / "logs"
    csv_filename = logs_directory / "points_data.csv"

    date = datetime.now().strftime("%Y-%m-%d")
    new_row = {
        "Date": date,
        "Earned Points": earned_points,
        "Points Difference": points_difference,
    }

    fieldnames = ["Date", "Earned Points", "Points Difference"]
    is_new_file = not csv_filename.exists()

    with open(csv_filename, mode="a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if is_new_file:
            writer.writeheader()
        writer.writerow(new_row)

def load_previous_points_data():
    try:
        with open(getProjectRoot() / "logs" / "previous_points_data.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_previous_points_data(data):
    logs_directory = getProjectRoot() / "logs"
    with open(logs_directory / "previous_points_data.json", "w") as file:
        json.dump(data, file, indent=4)

if __name__ == "__main__":
    setupLogging()
    logging.info("Starting application...")
    
    # Initialize container monitor
    container_monitor = ContainerMonitor()
    signal_handler.container_monitor = container_monitor
    container_monitor.start()
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Initialize and start Gradio interface with minimal footprint
    iface = gr.Interface(
        fn=lambda: "Active",
        inputs=None,
        outputs="text",
        title="Status",
        description="System Monitor"
    )
    
    interface_thread = Thread(target=lambda: iface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        prevent_thread_lock=True,
        show_api=False,
        show_error=False,
        quiet=True
    ))
    interface_thread.daemon = True
    interface_thread.start()
    
    create_accounts_json_from_env()
    create_config_yaml_from_env()
    downloadWebDriver()
    
    try:
        # Run initial job
        run_job_with_activity()
        
        # Schedule jobs with natural intervals
        schedule.every(random.randint(20, 40)).minutes.do(
            lambda: Path("/tmp/activity").touch()
        )
        schedule.every().day.at("05:00").do(run_job_with_activity)
        schedule.every().day.at("11:00").do(run_job_with_activity)
        
        while True:
            schedule.run_pending()
            time.sleep(random.uniform(1, 2))
            
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        container_monitor.stop()
        browser_manager.cleanup()
        shutdown_event.set()
    except Exception as e:
        logging.exception("Fatal error occurred")
        container_monitor.stop()
        browser_manager.cleanup()
        shutdown_event.set()
        raise