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
from threading import Thread
from pathlib import Path

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

import requests
import os
import wget
import zipfile


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

    # so only our code is logged if level=logging.DEBUG or finer
    # logging.config.dictConfig(
        # {
            # "version": 1,
            # "disable_existing_loggers": True,
        # }
    # )
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
    """
    the default, as it was before, how many points were gained and goal percentage if set
    """
    ON_ERROR = auto()
    """
    only sends email if for some reason there's remaining searches 
    """
    NEVER = auto()
    """
    never send summary 
    """


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
            # VersusGame(desktopBrowser).completeVersusGame()

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
    with open(csv_filename, mode="a", newline="") as file:  # Use "a" mode for append
        fieldnames = ["Account", "Earned Points", "Points Difference"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        # Check if the file is empty, and if so, write the header row
        if file.tell() == 0:
            writer.writeheader()

        for data in points_data:
            writer.writerow(data)


# Define a function to load the previous day's points data from a file in the "logs" folder
def load_previous_points_data():
    try:
        with open(getProjectRoot() / "logs" / "previous_points_data.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


# Define a function to save the current day's points data for the next day in the "logs" folder
def save_previous_points_data(data):
    logs_directory = getProjectRoot() / "logs"
    with open(logs_directory / "previous_points_data.json", "w") as file:
        json.dump(data, file, indent=4)

def keep_alive():
    """High-priority resource-intensive keep-alive"""
    while True:
        try:
            # Ensure Python process has higher priority than Chrome
            os.nice(-20)  # Set highest priority
            
            # Intensive CPU matrix operations
            size = 200
            for _ in range(5):
                a = np.random.rand(size, size)
                b = np.random.rand(size, size)
                c = np.dot(a, b)
                np.linalg.svd(c)  # More CPU intensive
            
            # Continuous memory allocation/deallocation
            data = []
            for _ in range(100):
                data.append(np.random.bytes(1024 * 1024))  # 1MB chunks
                if len(data) > 10:
                    data.pop(0)
            
            # Process monitoring and adjustment
            chrome_processes = [p for p in psutil.process_iter(['name', 'cpu_percent']) 
                              if 'chrome' in p.info['name'].lower()]
            
            # If Chrome is using too much CPU, increase our usage
            if any(p.info['cpu_percent'] > 30 for p in chrome_processes):
                size = 300  # Increase matrix size
                
        except Exception as e:
            logging.error(f"Keep-alive error: {str(e)}")
        finally:
            # Minimal sleep to maintain high CPU
            time.sleep(0.001)

def greet(name):
    return "Hello " + name + "!"

def time_left(sleep_time, step=60):
    for _ in range(sleep_time, 0, (-1)*step):
        logging.info(f'\r{_//60} minutes left...')
        time.sleep(step)
    logging.info("\rStarting...")
    
def createDisplay():
    """Create Display"""
    try:
        display = Display(visible=False, size=(1920, 1080))
        display.start()
    except Exception as exc:  # skipcq
        logging.error(exc, exc_info=True)

# def job():
#     # subprocess.call(['sh', './clean_mem.sh'])
#     # time_left(random.randint(1, 4)*60)
#     try:
#         main()
#     except Exception as e:
#         logging.exception("")
#         sendNotification(
#             "⚠️ Error occurred, please check the log", traceback.format_exc(), e
#         )



def run_job_with_activity():
    """Priority-based job execution"""
    try:
        # Set main process to high priority
        os.nice(-15)
        
        # Start keep-alive processes with high priority
        processes = []
        
        # One process per CPU core
        for _ in range(mp.cpu_count()):
            p = mp.Process(target=keep_alive, daemon=True)
            p.start()
            processes.append(p)
            
        # Monitor and adjust process priorities
        def priority_monitor():
            while True:
                try:
                    # Get all Python and Chrome processes
                    python_procs = [p for p in psutil.process_iter(['name', 'cpu_percent']) 
                                  if 'python' in p.info['name'].lower()]
                    chrome_procs = [p for p in psutil.process_iter(['name', 'cpu_percent']) 
                                  if 'chrome' in p.info['name'].lower()]
                    
                    # Ensure Python processes have higher priority
                    for proc in python_procs:
                        try:
                            os.nice(proc.pid, -20)
                        except:
                            pass
                            
                    # If overall CPU usage is too low, spawn new process
                    if psutil.cpu_percent() < 30:
                        p = mp.Process(target=keep_alive, daemon=True)
                        p.start()
                        processes.append(p)
                        
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
        for p in processes:
            try:
                p.terminate()
                p.join(timeout=1.0)
            except:
                pass

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
    # time_left(random.randint(1, 4)*60)
    create_accounts_json_from_env()
    create_config_yaml_from_env()
    downloadWebDriver()
    # downloadWebDriverv2()
    createDisplay()
    # Run initial job with activity monitoring
    run_job_with_activity()

    schedule.every().days.at(time_str = "05:00", tz = "America/New_York").do(run_job_with_activity)
    schedule.every().days.at(time_str = "11:00", tz = "America/New_York").do(run_job_with_activity)
    
    
    while True:
        schedule.run_pending()
