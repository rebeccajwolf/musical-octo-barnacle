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
from pyvirtualdisplay import Display
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
        self.node_process = None
        self.monitor_thread = None
        self.running = True
        self.heartbeat_interval = 30
        
    def start(self):
        # Start Node.js monitor
        self.node_process = subprocess.Popen(
            ['node', 'container_monitor.js'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Start monitor thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def _monitor_loop(self):
        while self.running:
            try:
                # Check Node.js monitor health
                requests.get('http://localhost:8080', timeout=5)
                
                # Check system resources
                cpu_percent = psutil.cpu_percent(interval=1)
                mem_percent = psutil.virtual_memory().percent
                
                # Generate CPU activity if needed
                if cpu_percent < 1.0:
                    _ = [i * i for i in range(10000)]
                
                # Memory activity
                temp_array = np.zeros((100, 100), dtype=np.float32)
                del temp_array
                
                # File system activity
                Path('/tmp/activity_marker').touch()
                Path('/tmp/heartbeat').touch()
                
                logging.debug(f"Monitor stats - CPU: {cpu_percent}%, Memory: {mem_percent}%")
                
            except Exception as e:
                logging.error(f"Monitor error: {str(e)}")
            
            time.sleep(self.heartbeat_interval)
    
    def stop(self):
        self.running = False
        if self.node_process:
            self.node_process.terminate()
            self.node_process.wait()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

class BrowserManager:
    def __init__(self):
        self.keep_alive = ContainerMonitor()
        self.display = None
        
    def setup(self):
        try:
            # Start virtual display
            self.display = Display(visible=False, size=(800, 600))
            self.display.start()
            
            # Start the keep-alive mechanism
            self.keep_alive.start()
            
            # Set environment variables
            # os.environ['PYTHONUNBUFFERED'] = '1'
            # os.environ['DISPLAY'] = ':99'
            
        except Exception as e:
            logging.error(f"Browser manager setup error: {str(e)}")
            raise
        
    def cleanup(self):
        try:
            if self.keep_alive:
                self.keep_alive.stop()
            if self.display:
                self.display.stop()
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
    
    # Initialize and start Gradio interface
    iface = gr.Interface(
        fn=lambda: "Application is running",
        inputs=None,
        outputs="text",
        title="App Status",
        description="Monitoring application status"
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
        
        # Schedule jobs with more frequent intervals
        schedule.every(15).minutes.do(lambda: Path("/tmp/heartbeat").touch())
        schedule.every().days.at("05:00", tz="America/New_York").do(run_job_with_activity)
        schedule.every().days.at("11:00", tz="America/New_York").do(run_job_with_activity)
        
        while True:
            schedule.run_pending()
            time.sleep(1)
            
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