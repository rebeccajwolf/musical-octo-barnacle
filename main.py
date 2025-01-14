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

class ActivityMonitor:
    def __init__(self):
        self.last_activity = time.time()
        self.lock = threading.Lock()
        self.matrix_size = 100
        self.min_cpu_percent = 5
        self.min_memory_percent = 40
        
    def update_activity(self):
        with self.lock:
            self.last_activity = time.time()
            
    def get_idle_time(self):
        with self.lock:
            return time.time() - self.last_activity
            
    def increase_activity(self):
        with self.lock:
            self.matrix_size += 50
            if self.matrix_size > 500:  # Cap matrix size
                self.matrix_size = 500
                
    def decrease_activity(self):
        with self.lock:
            self.matrix_size -= 50
            if self.matrix_size < 100:  # Minimum matrix size
                self.matrix_size = 100
                
    def get_matrix_size(self):
        with self.lock:
            return self.matrix_size

# Global activity monitor
activity_monitor = ActivityMonitor()

def continuous_cpu_load():
    """Maintains constant CPU activity with adaptive intensity"""
    while not shutdown_event.is_set():
        try:
            matrix_size = activity_monitor.get_matrix_size()
            # Matrix operations with SVD for intensive CPU usage
            a = np.random.rand(matrix_size, matrix_size)
            b = np.random.rand(matrix_size, matrix_size)
            c = np.dot(a, b)
            np.linalg.svd(c)  # More CPU intensive
            
            # Update activity timestamp
            activity_monitor.update_activity()
            
            # Adaptive sleep based on CPU usage
            cpu_percent = psutil.cpu_percent()
            if cpu_percent > 80:
                time.sleep(0.1)  # Longer sleep if CPU is too high
            else:
                time.sleep(0.01)  # Normal sleep
                
        except Exception as e:
            logging.error(f"CPU load error: {str(e)}")

def memory_activity():
    """Maintains constant memory activity with adaptive allocation"""
    chunk_size = 1024 * 1024  # 1MB base chunk
    while not shutdown_event.is_set():
        try:
            data = []
            mem = psutil.virtual_memory()
            
            # Adaptive chunk count based on available memory
            target_chunks = max(1, int((90 - mem.percent) / 10))
            
            for _ in range(target_chunks):
                if shutdown_event.is_set():
                    break
                data.append(os.urandom(chunk_size))
                time.sleep(0.05)
                
            # Clear some data if memory usage is too high
            while mem.percent > 85 and data:
                data.pop()
                mem = psutil.virtual_memory()
                
            activity_monitor.update_activity()
            time.sleep(0.1)
            
        except Exception as e:
            logging.error(f"Memory activity error: {str(e)}")

def io_activity():
    """Maintains constant I/O activity with adaptive writes"""
    temp_file = "temp_activity.dat"
    while not shutdown_event.is_set():
        try:
            # Adaptive write size based on disk usage
            write_size = 1024 * 100  # Base: 100KB
            
            # Write and read from disk
            with open(temp_file, "wb") as f:
                f.write(os.urandom(write_size))
            
            with open(temp_file, "rb") as f:
                f.read()
                
            activity_monitor.update_activity()
            
            # Adaptive sleep based on system load
            load = os.getloadavg()[0]
            sleep_time = min(1.0, max(0.1, load / 10.0))
            time.sleep(sleep_time)
            
        except Exception as e:
            logging.error(f"I/O activity error: {str(e)}")
        
    # Cleanup
    try:
        os.remove(temp_file)
    except:
        pass

def network_activity():
    """Maintains minimal network activity with retry mechanism"""
    urls = [
        "https://huggingface.co",
        "https://google.com",
        "https://microsoft.com"
    ]
    current_url_index = 0
    
    while not shutdown_event.is_set():
        try:
            url = urls[current_url_index]
            response = requests.head(url, timeout=5)
            if response.status_code == 200:
                activity_monitor.update_activity()
                time.sleep(2)
            else:
                # Try next URL if current one fails
                current_url_index = (current_url_index + 1) % len(urls)
                time.sleep(1)
        except Exception as e:
            logging.error(f"Network activity error: {str(e)}")
            current_url_index = (current_url_index + 1) % len(urls)
            time.sleep(1)

def activity_coordinator():
    """Coordinates all activity processes with adaptive resource management"""
    threads = []
    
    # Start activity threads
    activities = [
        continuous_cpu_load,
        memory_activity,
        io_activity,
        network_activity
    ]
    
    for activity in activities:
        thread = threading.Thread(target=activity, daemon=True)
        thread.start()
        threads.append(thread)
        
    # Monitor overall system activity
    while not shutdown_event.is_set():
        try:
            idle_time = activity_monitor.get_idle_time()
            cpu_percent = psutil.cpu_percent()
            mem_percent = psutil.virtual_memory().percent
            
            # Adaptive activity adjustment
            if idle_time > 60 or cpu_percent < activity_monitor.min_cpu_percent:
                activity_monitor.increase_activity()
                logging.warning("System idle or low CPU, increasing activity")
            elif cpu_percent > 90:
                activity_monitor.decrease_activity()
                logging.info("High CPU usage, decreasing activity")
                
            # Memory management
            if mem_percent < activity_monitor.min_memory_percent:
                activity_queue.put(('increase_memory', None))
            elif mem_percent > 90:
                activity_queue.put(('decrease_memory', None))
                
            time.sleep(1)
        except Exception as e:
            logging.error(f"Activity coordinator error: {str(e)}")
            
    # Wait for all threads to finish
    for thread in threads:
        thread.join(timeout=1.0)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logging.info("Shutdown signal received, cleaning up...")
    shutdown_event.set()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    args = argumentParser()
    Utils.args = args
    loadedAccounts = setupAccounts()

    # Load previous day's points data
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

        # Calculate the difference in points from the prior day
        points_difference = earned_points - previous_points

        # Append the daily points and points difference to CSV and Excel
        log_daily_points_to_csv(earned_points, points_difference)

        # Update the previous day's points data
        previous_points_data[currentAccount.username] = earned_points

        logging.info(
            f"[POINTS] Data for '{currentAccount.username}' appended to the file."
        )

    # Save the current day's points data for the next day in the "logs" folder
    save_previous_points_data(previous_points_data)
    logging.info("[POINTS] Data saved for the next day.")

def run_job_with_activity():
    """Priority-based job execution with continuous system activity"""
    try:
        # Set Python process priority to maximum
        try:
            os.setpriority(os.PRIO_PROCESS, 0, -20)  # Highest priority
        except Exception as e:
            logging.warning(f"Could not set process priority: {str(e)}")
        
        # Start activity coordinator in a separate thread
        coordinator_thread = threading.Thread(target=activity_coordinator, daemon=True)
        coordinator_thread.start()
        
        # Start CPU-intensive processes
        processes = []
        
        # One process per CPU core for continuous activity
        cpu_count = mp.cpu_count()
        for _ in range(max(1, cpu_count - 1)):  # Leave one core for main process
            p = mp.Process(target=continuous_cpu_load, daemon=True)
            p.start()
            processes.append(p)
            
        # Start memory and I/O activity processes
        memory_proc = mp.Process(target=memory_activity, daemon=True)
        memory_proc.start()
        processes.append(memory_proc)
        
        io_proc = mp.Process(target=io_activity, daemon=True)
        io_proc.start()
        processes.append(io_proc)
        
        # Monitor and adjust process priorities
        def priority_monitor():
            while not shutdown_event.is_set():
                try:
                    # Get all Python processes
                    python_procs = [p for p in psutil.process_iter(['name', 'pid', 'cpu_percent']) 
                                  if 'python' in p.info['name'].lower()]
                    
                    # Sort processes by CPU usage
                    python_procs.sort(key=lambda x: x.info['cpu_percent'], reverse=True)
                    
                    # Ensure main Python process has highest priority
                    main_pid = os.getpid()
                    for proc in python_procs:
                        try:
                            if proc.info['pid'] == main_pid:
                                proc.nice(-20)  # Highest priority for main process
                            else:
                                proc.nice(-10)  # Lower priority for other Python processes
                        except:
                            pass
                            
                    # Monitor system resources
                    cpu_percent = psutil.cpu_percent()
                    mem_percent = psutil.virtual_memory().percent
                    
                    # Adjust activity based on resource usage
                    if cpu_percent < 30:
                        activity_queue.put(('increase_cpu', None))
                    if mem_percent < 40:
                        activity_queue.put(('increase_memory', None))
                        
                except Exception as e:
                    logging.error(f"Monitor error: {str(e)}")
                finally:
                    time.sleep(0.1)
                    
        monitor_thread = threading.Thread(target=priority_monitor, daemon=True)
        monitor_thread.start()
            
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
        # Cleanup processes
        for p in processes:
            try:
                p.terminate()
                p.join(timeout=1.0)
            except:
                pass
        
        # Signal shutdown
        shutdown_event.set()


def create_accounts_json_from_env():
    """Creates accounts.json file from ACCOUNTS environment variable.
    Expected format of ACCOUNTS env var: 'email1:pass1,email2:pass2'
    """
    try:
        accounts_str = os.getenv('ACCOUNTS', '')
        if not accounts_str:
            logging.warning("[ACCOUNT] No ACCOUNTS environment variable found")
            return

        # Parse accounts string into list of dictionaries
        accounts = []
        for account_str in accounts_str.split(','):
            if ':' in account_str:
                username, password = account_str.split(':')
                accounts.append({
                    "username": username.strip(),
                    "password": password.strip()
                })
        # Write to accounts.json
        account_path = getProjectRoot() / "accounts.json"
        with open(account_path, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=4)
            logging.info("[ACCOUNT] Successfully created accounts.json from environment variable")
    except Exception as e:
        logging.error("[ACCOUNT] Error creating accounts.json: %s", str(e))

def create_config_yaml_from_env():
    """Creates config-private.yaml file from TOKEN environment variable."""
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

        # Write to config-private.yaml
        config_path = getProjectRoot() / "config-private.yaml"
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False)
            logging.info("[CONFIG] Successfully created config-private.yaml from environment variable")
    except Exception as e:
        logging.error("[CONFIG] Error creating config-private.yaml: %s", str(e))

def downloadWebDriver():
    # get the latest chrome driver version number
    # url = 'https://chromedriver.storage.googleapis.com/LATEST_RELEASE'
    # response = requests.get(url)
    # version_number = response.text

    # build the donwload url
    # download_url = "https://chromedriver.storage.googleapis.com/" + version_number +"/chromedriver_linux64.zip"
    download_url = "https://storage.googleapis.com/chrome-for-testing-public/128.0.6613.119/linux64/chromedriver-linux64.zip"
    # download the zip file using the url built above
    latest_driver_zip = wget.download(download_url,'chromedriver.zip')

    # extract the zip file
    with zipfile.ZipFile(latest_driver_zip, 'r') as zip_ref:
        zip_ref.extractall() # you can specify the destination folder path here
    # delete the zip file downloaded above
    os.remove(latest_driver_zip)

def downloadWebDriverv2():
    # get the latest chrome driver version number
    url = 'https://chromedriver.storage.googleapis.com/LATEST_RELEASE'
    response = requests.get(url)
    version_number = response.text

    # build the donwload url
    download_url = "https://chromedriver.storage.googleapis.com/" + version_number +"/chromedriver_linux64.zip"
    # download the zip file using the url built above
    latest_driver_zip = wget.download(download_url,'chromedriver.zip')
    # extract the zip file
    with zipfile.ZipFile(latest_driver_zip, 'r') as zip_ref:
        zip_ref.extractall() # you can specify the destination folder path here
    # delete the zip file downloaded above
    os.remove(latest_driver_zip)

def log_daily_points_to_csv(earned_points, points_difference):
    logs_directory = getProjectRoot() / "logs"
    csv_filename = logs_directory / "points_data.csv"

    # Create a new row with the date, daily points, and points difference
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
    """Sets up and validates a list of accounts loaded from 'accounts.json'."""

    def validEmail(email: str) -> bool:
        """Validate Email."""
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
    """
    configures how results are summarized via Apprise
    """
    ALWAYS = auto()
    ON_ERROR = auto()
    NEVER = auto()

def executeBot(currentAccount: Account, args: argparse.Namespace):
    logging.info(f"********************{currentAccount.username}********************")

    startingPoints: int | None = None
    accountPoints: int
    remainingSearches: RemainingSearches
    goalTitle: str
    goalPoints: int

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

    logging.info(
        f"[POINTS] You have earned {formatNumber(accountPoints - startingPoints)} points this run !"
    )
    logging.info(f"[POINTS] You are now at {formatNumber(accountPoints)} points !")
    appriseSummary = AppriseSummary[CONFIG.get("apprise").get("summary")]
    if appriseSummary == AppriseSummary.ALWAYS:
        goalStatus = ""
        if goalPoints > 0:
            logging.info(
                f"[POINTS] You are now at {(formatNumber((accountPoints / goalPoints) * 100))}% of your "
                f"goal ({goalTitle}) !"
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
    elif appriseSummary == AppriseSummary.ON_ERROR:
        if remainingSearches.getTotal() > 0:
            sendNotification(
                "Error: remaining searches",
                f"account username: {currentAccount.username}, {remainingSearches}",
            )
    elif appriseSummary == AppriseSummary.NEVER:
        pass

    return accountPoints

def export_points_to_csv(points_data):
    logs_directory = getProjectRoot() / "logs"
    csv_filename = logs_directory / "points_data.csv"
    with open(csv_filename, mode="a", newline="") as file:
        fieldnames = ["Account", "Earned Points", "Points Difference"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        if file.tell() == 0:
            writer.writeheader()

        for data in points_data:
            writer.writerow(data)

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

def createDisplay():
    """Create Display"""
    try:
        display = Display(visible=False, size=(1920, 1080))
        display.start()
    except Exception as exc:
        logging.error(exc, exc_info=True)

if __name__ == "__main__":
    setupLogging()
    logging.info("Starting application...")
    
    # Start Gradio interface
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
        prevent_thread_lock=True
    ))
    interface_thread.daemon = True
    interface_thread.start()
    
    create_accounts_json_from_env()
    create_config_yaml_from_env()
    downloadWebDriver()
    createDisplay()
    
    # Run initial job with activity monitoring
    run_job_with_activity()
    
    # Schedule jobs
    schedule.every().days.at("05:00", tz="America/New_York").do(run_job_with_activity)
    schedule.every().days.at("11:00", tz="America/New_York").do(run_job_with_activity)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
            activity_monitor.update_activity()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        shutdown_event.set()