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
import ruamel.yaml
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
import shutil
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
from src.utils import Utils, CONFIG, sendNotification, getProjectRoot, formatNumber, loadPrivateConfig


def executeBot(currentAccount: Account, args: argparse.Namespace) -> int:
    """Execute the bot for a single account and return earned points"""
    logging.info(f"********************{currentAccount.username}********************")

    startingPoints: int | None = None
    accountPoints: int = 0
    remainingSearches: RemainingSearches | None = None
    goalTitle: str = ""
    goalPoints: int = 0

    browser_instances = []  # Keep track of browser instances

    try:
        if args.searchtype in ("desktop", None):
            desktop_browser = Browser(mobile=False, account=currentAccount, args=args)
            browser_instances.append(desktop_browser)
            with desktop_browser as desktopBrowser:
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
            mobile_browser = Browser(mobile=True, account=currentAccount, args=args)
            browser_instances.append(mobile_browser)
            with mobile_browser as mobileBrowser:
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

    except Exception as e:
        # Log the exception
        logging.error(f"Error during execution: {str(e)}")
        raise

    finally:
        # Ensure all browser instances are properly cleaned up
        for browser in browser_instances:
            try:
                browser.cleanup()
            except Exception as cleanup_error:
                logging.error(f"Error during browser cleanup: {str(cleanup_error)}")

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
        # browser_manager.setup()
        
        # Run main job
        main()
        
    except Exception as e:
        logging.exception("Job execution error")
        sendNotification(
            "⚠️ Error occurred, please check the log",
            traceback.format_exc(),
            e
        )
    # finally:
    #     # Cleanup browser environment
    #     browser_manager.cleanup()

def main():
    args = argumentParser()
    Utils.args = args
    loadedAccounts = setupAccounts()

    previous_points_data = load_previous_points_data()

    for currentAccount in loadedAccounts:
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            try:
                earned_points = executeBot(currentAccount, args)
                # If execution succeeds, process the points and break the retry loop
                previous_points = previous_points_data.get(currentAccount.username, 0)
                points_difference = earned_points - previous_points
                log_daily_points_to_csv(earned_points, points_difference)
                previous_points_data[currentAccount.username] = earned_points
                logging.info(
                    f"[POINTS] Data for '{currentAccount.username}' appended to the file."
                )
                break  # Success - exit retry loop
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    logging.error(
                        f"Error executing account {currentAccount.username} (attempt {retry_count}/{max_retries}): {str(e)}"
                    )
                    # Add exponential backoff
                    wait_time = 2 ** retry_count
                    logging.info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    logging.error(
                        f"Failed to execute account {currentAccount.username} after {max_retries} attempts. Moving to next account."
                    )
                    sendNotification(
                        f"⚠️ Error executing {currentAccount.username} after {max_retries} retries",
                        traceback.format_exc(),
                        e,
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

        # Validate token format
        if not token.startswith(('tgram://', 'discord://', 'slack://')):
            logging.error("[CONFIG] Invalid token format. Must start with protocol (e.g., tgram://, discord://, slack://)")
            return

        # Create minimal config with just the token
        config = {
            'apprise': {
                'urls': [token]
            }
        }

        config_path = getProjectRoot() / "config-private.yaml"
        
        # Use ruamel.yaml with proper configuration
        yaml = ruamel.yaml.YAML()
        yaml.default_flow_style = False
        yaml.indent(mapping=2, sequence=4, offset=2)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f)
            logging.info("[CONFIG] Successfully created config-private.yaml from environment variable")
            
        # Validate the created config
        test_config = loadPrivateConfig()
        if not test_config.get('apprise', {}).get('urls', []):
            raise ValueError("Created config file is invalid - missing apprise URLs")
            
        logging.info("[CONFIG] Configuration file validated successfully")
        
    except Exception as e:
        logging.error(f"[CONFIG] Error creating config-private.yaml: {str(e)}")
        raise

def downloadWebDriver():
    """Downloads and sets up chromedriver in the correct location"""
    try:
        # Download the zip file
        download_url = "https://storage.googleapis.com/chrome-for-testing-public/128.0.6613.119/linux64/chromedriver-linux64.zip"
        latest_driver_zip = wget.download(download_url, 'chromedriver.zip')
        
        # Create a temporary directory for extraction
        temp_dir = Path('temp_chromedriver')
        temp_dir.mkdir(exist_ok=True)
        
        # Extract the zip file to temp directory
        with zipfile.ZipFile(latest_driver_zip, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Move the chromedriver to the correct location
        chromedriver_src = temp_dir / 'chromedriver-linux64' / 'chromedriver'
        chromedriver_dest = getProjectRoot() / 'chromedriver'
        
        # Ensure source file exists
        if not chromedriver_src.exists():
            raise FileNotFoundError(f"ChromeDriver not found in {chromedriver_src}")
        
        # Move the file and set permissions
        shutil.move(str(chromedriver_src), str(chromedriver_dest))
        os.chmod(chromedriver_dest, 0o755)
        
        # Cleanup
        os.remove(latest_driver_zip)
        shutil.rmtree(temp_dir)
        
        logging.info("ChromeDriver successfully installed")
        
    except Exception as e:
        logging.error(f"Error downloading ChromeDriver: {str(e)}")
        raise

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

class ScheduleManager:
    def __init__(self):
        self.running = True
        self.stop_event = Event()
        self._schedule_thread = None

    def start(self):
        """Start the schedule manager"""
        self._schedule_thread = Thread(target=self._run_schedule, daemon=True)
        self._schedule_thread.start()

    def stop(self):
        """Stop the schedule manager gracefully"""
        self.running = False
        self.stop_event.set()
        if self._schedule_thread:
            self._schedule_thread.join(timeout=5)

    def _run_schedule(self):
        """Run the schedule loop with proper error handling"""
        while self.running and not self.stop_event.is_set():
            try:
                schedule.run_pending()
                # Use event with timeout instead of sleep for more responsive shutdown
                self.stop_event.wait(timeout=random.uniform(1, 2))
            except Exception as e:
                logging.error(f"Schedule error: {str(e)}")
                time.sleep(5)  # Wait before retrying on error

def setup_schedule():
    """Set up the schedule with randomized times"""
    # Clear any existing jobs
    schedule.clear()

    # Add some randomization to job times to avoid detection
    base_morning_hour = 5
    base_evening_hour = 14
    
    # Add random minutes to base hours
    morning_time = f"{base_morning_hour:02d}:{random.randint(0, 59):02d}"
    evening_time = f"{base_evening_hour:02d}:{random.randint(0, 59):02d}"

    # Schedule jobs
    schedule.every().day.at(morning_time).do(run_job_with_activity)
    schedule.every().day.at(evening_time).do(run_job_with_activity)
    
    logging.info(f"Scheduled jobs for {morning_time} and {evening_time}")

def main_with_schedule():
    """Main function with proper schedule handling"""
    try:
        # Initial setup
        setupLogging()
        logging.info("Starting application...")
        
        create_accounts_json_from_env()
        create_config_yaml_from_env()
        downloadWebDriver()
        
        # Run initial job
        run_job_with_activity()
        
        # Set up and start scheduler
        setup_schedule()
        schedule_manager = ScheduleManager()
        schedule_manager.start()
        
        # Wait for keyboard interrupt or other signals
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Received shutdown signal, cleaning up...")
        finally:
            schedule_manager.stop()
            
    except Exception as e:
        logging.exception("Fatal error occurred")
        sendNotification(
            "⚠️ Fatal error occurred",
            traceback.format_exc(),
            e
        )
        raise

if __name__ == "__main__":
    main_with_schedule()