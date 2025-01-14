import argparse
import contextlib
import locale
import logging
import os
import random
from pathlib import Path
from types import TracebackType
from typing import Any, Type

import ipapi
import pycountry
import seleniumwire.undetected_chromedriver as webdriver
import undetected_chromedriver
from ipapi.exceptions import RateLimited
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By

from src import Account, RemainingSearches
from src.userAgentGenerator import GenerateUserAgent
from src.utils import CONFIG, Utils, getBrowserConfig, getProjectRoot, saveBrowserConfig


class Browser:
    """WebDriver wrapper class."""

    webdriver: undetected_chromedriver.Chrome

    def __init__(
        self, mobile: bool, account: Account, args: argparse.Namespace
    ) -> None:
        # Initialize browser instance
        logging.debug("in __init__")
        self.mobile = mobile
        self.browserType = "mobile" if mobile else "desktop"
        self.headless = not args.visible
        self.username = account.username
        self.password = account.password
        self.totp = account.totp
        self.localeLang, self.localeGeo = self.getLanguageCountry(args.lang, args.geo)
        self.proxy = None
        if args.proxy:
            self.proxy = args.proxy
        elif account.proxy:
            self.proxy = account.proxy
        self.userDataDir = self.setupProfiles()
        self.browserConfig = getBrowserConfig(self.userDataDir)
        (
            self.userAgent,
            self.userAgentMetadata,
            newBrowserConfig,
        ) = GenerateUserAgent().userAgent(self.browserConfig, mobile)
        if newBrowserConfig:
            self.browserConfig = newBrowserConfig
            saveBrowserConfig(self.userDataDir, self.browserConfig)
        self.webdriver = self.browserSetup()
        self._setup_cdp_listeners()
        self.utils = Utils(self.webdriver)
        logging.debug("out __init__")

    def __enter__(self):
        logging.debug("in __enter__")
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ):
        # Cleanup actions when exiting the browser context
        logging.debug(
            f"in __exit__ exc_type={exc_type} exc_value={exc_value} traceback={traceback}"
        )
        # turns out close is needed for undetected_chromedriver
        self.webdriver.close()
        self.webdriver.quit()

    def _apply_cdp_settings(self, target_id=None):
        """Apply CDP settings to a specific target or current tab"""
        if self.browserConfig.get("sizes"):
            deviceHeight = self.browserConfig["sizes"]["height"]
            deviceWidth = self.browserConfig["sizes"]["width"]
        else:
            if self.mobile:
                deviceHeight = random.randint(568, 1024)
                deviceWidth = random.randint(320, min(576, int(deviceHeight * 0.7)))
            else:
                deviceWidth = random.randint(1024, 2560)
                deviceHeight = random.randint(768, min(1440, int(deviceWidth * 0.8)))
            self.browserConfig["sizes"] = {
                "height": deviceHeight,
                "width": deviceWidth,
            }
            saveBrowserConfig(self.userDataDir, self.browserConfig)

        if self.mobile:
            screenHeight = deviceHeight + 146
            screenWidth = deviceWidth
        else:
            screenWidth = deviceWidth + 55
            screenHeight = deviceHeight + 151

        logging.info(f"Screen size: {screenWidth}x{screenHeight}")
        logging.info(f"Device size: {deviceWidth}x{deviceHeight}")

        cdp_commands = [
            (
                "Emulation.setTouchEmulationEnabled",
                {"enabled": self.mobile}
            ),
            (
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": deviceWidth,
                    "height": deviceHeight,
                    "deviceScaleFactor": 0,
                    "mobile": self.mobile,
                    "screenWidth": screenWidth,
                    "screenHeight": screenHeight,
                    "positionX": 0,
                    "positionY": 0,
                    "viewport": {
                        "x": 0,
                        "y": 0,
                        "width": deviceWidth,
                        "height": deviceHeight,
                        "scale": 1,
                    },
                }
            ),
            (
                "Emulation.setUserAgentOverride",
                {
                    "userAgent": self.userAgent,
                    "platform": self.userAgentMetadata["platform"],
                    "userAgentMetadata": self.userAgentMetadata,
                },
            ),
            # (
            #     "Page.addScriptToEvaluateOnNewDocument",
            #     {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            # )
        ]

        for command, params in cdp_commands:
            if target_id:
                self.webdriver.execute_cdp_cmd(
                    f'Target.sendMessageToTarget',
                    {
                        'targetId': target_id,
                        'message': json.dumps({
                            'method': command,
                            'params': params
                        })
                    }
                )
            else:
                self.webdriver.execute_cdp_cmd(command, params)

    def _setup_cdp_listeners(self):
        """Setup listeners for new tab creation and navigation"""
        def handle_target_created(target):
            target_id = target.get('targetId')
            if target.get('type') == 'page':
                self._apply_cdp_settings(target_id)

        # Enable target events
        self.webdriver.execute_cdp_cmd('Target.setDiscoverTargets', {'discover': True})
        
        # Add event listener for target creation
        self.webdriver.add_cdp_listener('Target.targetCreated', handle_target_created)
        
        # Apply settings to initial tab
        self._apply_cdp_settings()

    def browserSetup(
        self,
    ) -> undetected_chromedriver.Chrome:
        # Configure and setup the Chrome browser
        options = undetected_chromedriver.ChromeOptions()
        options.headless = self.headless
        options.add_argument(f"--lang={self.localeLang}")
        options.add_argument("--log-level=3")
        options.add_argument(
            "--blink-settings=imagesEnabled=false"
        )  # If you are having MFA sign in issues comment this line out
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-certificate-errors-spki-list")
        options.add_argument("--ignore-ssl-errors")
        if os.environ.get("DOCKER"):
            options.add_argument("--headless=new")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-extensions")
        options.add_argument("--dns-prefetch-disable")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-features=Translate")
        options.add_argument("--disable-features=PrivacySandboxSettings4")
        options.add_argument("--disable-http2")
        # options.add_argument("--disable-setuid-sandbox")
        # options.add_argument("--window-size=800,600")
        # options.add_argument("--single-process")  # Reduces memory footprint
        # options.add_argument("--disable-software-rasterizer")  # Reduces GPU memory usage
        # options.add_argument("--disable-plugins")
        # options.add_argument("--disable-popup-blocking")
        # options.add_argument("--disable-infobars")
        # options.add_argument("--incognito")  # Reduces cache/history memory usage
        # options.add_argument("--aggressive-cache-discard")
        # options.add_argument("--disable-cache")
        # options.add_argument("--disable-application-cache")
        # options.add_argument("--disable-offline-load-stale-cache")
        # options.add_argument("--disk-cache-size=0")
        # options.add_argument("--disable-background-networking")
        # options.add_argument("--disable-component-extensions-with-background-pages")
        # options.add_argument("--disable-sync")
        # options.add_argument("--disable-translate")
        # options.add_argument("--hide-scrollbars")
        # options.add_argument("--metrics-recording-only")
        # options.add_argument("--mute-audio")
        # options.add_argument("--no-first-run")
        # options.add_argument("--safebrowsing-disable-auto-update")
        options.add_argument("--disable-search-engine-choice-screen")  # 153
        options.page_load_strategy = "eager"

        seleniumwireOptions: dict[str, Any] = {"verify_ssl": False}

        if self.proxy:
            # Setup proxy if provided
            seleniumwireOptions["proxy"] = {
                "http": self.proxy,
                "https": self.proxy,
                "no_proxy": "localhost,127.0.0.1",
            }
        driver = None

        if os.environ.get("DOCKER"):
            driver = webdriver.Chrome(
                options=options,
                seleniumwire_options=seleniumwireOptions,
                user_data_dir=self.userDataDir.as_posix(),
                driver_executable_path="/usr/bin/chromedriver",
            )
        else:
            # Obtain webdriver chrome driver version
            version = self.getChromeVersion()
            major = int(version.split(".")[0])

            driver = webdriver.Chrome(
                options=options,
                seleniumwire_options=seleniumwireOptions,
                user_data_dir=self.userDataDir.as_posix(),
                driver_executable_path=getProjectRoot() / "chromedriver",
                # version_main=112,
            )

        seleniumLogger = logging.getLogger("seleniumwire")
        seleniumLogger.setLevel(logging.ERROR)

        return driver

    def setupProfiles(self) -> Path:
        """
        Sets up the sessions profile for the chrome browser.
        Uses the username to create a unique profile for the session.

        Returns:
            Path
        """
        sessionsDir = getProjectRoot() / "sessions"

        # Concatenate username and browser type for a plain text session ID
        sessionid = f"{self.username}"

        sessionsDir = sessionsDir / sessionid
        sessionsDir.mkdir(parents=True, exist_ok=True)
        return sessionsDir

    @staticmethod
    def getLanguageCountry(language: str, country: str) -> tuple[str, str]:
        if not country:
            country = CONFIG.get("default").get("geolocation")

        if not language:
            country = CONFIG.get("default").get("language")

        if not language or not country:
            currentLocale = locale.getlocale()
            if not language:
                with contextlib.suppress(ValueError):
                    language = pycountry.languages.get(
                        alpha_2=currentLocale[0].split("_")[0]
                    ).alpha_2
            if not country:
                with contextlib.suppress(ValueError):
                    country = pycountry.countries.get(
                        alpha_2=currentLocale[0].split("_")[1]
                    ).alpha_2

        if not language or not country:
            try:
                ipapiLocation = ipapi.location()
                if not language:
                    language = ipapiLocation["languages"].split(",")[0].split("-")[0]
                if not country:
                    country = ipapiLocation["country"]
            except RateLimited:
                logging.warning(exc_info=True)

        if not language:
            language = "en"
            logging.warning(
                f"Not able to figure language returning default: {language}"
            )

        if not country:
            country = "US"
            logging.warning(f"Not able to figure country returning default: {country}")

        return language, country

    @staticmethod
    def getChromeVersion() -> str:
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument('--disable-dev-shm-usage')
        driver = WebDriver(service=ChromeService(getProjectRoot() / "chromedriver"), options=chrome_options)
        # driver = WebDriver(options=chrome_options)
        version = driver.capabilities["browserVersion"]

        driver.close()
        driver.quit()
        # driver.__exit__(None, None, None)

        return version

    def getRemainingSearches(
        self, desktopAndMobile: bool = False
    ) -> RemainingSearches | int:
        # bingInfo = self.utils.getBingInfo()
        bingInfo = self.utils.getDashboardData()
        searchPoints = 1
        counters = bingInfo["userStatus"]["counters"]
        pcSearch: dict = counters["pcSearch"][0]
        pointProgressMax: int = pcSearch["pointProgressMax"]

        searchPoints: int
        if pointProgressMax in [30, 90, 102]:
            searchPoints = 3
        elif pointProgressMax in [50, 150] or pointProgressMax >= 170:
            searchPoints = 5
        pcPointsRemaining = pcSearch["pointProgressMax"] - pcSearch["pointProgress"]
        assert pcPointsRemaining % searchPoints == 0
        remainingDesktopSearches: int = int(pcPointsRemaining / searchPoints)

        activeLevel = bingInfo["userStatus"]["levelInfo"]["activeLevel"]
        remainingMobileSearches: int = 0
        if activeLevel == "Level2":
            mobileSearch: dict = counters["mobileSearch"][0]
            mobilePointsRemaining = (
                mobileSearch["pointProgressMax"] - mobileSearch["pointProgress"]
            )
            assert mobilePointsRemaining % searchPoints == 0
            remainingMobileSearches = int(mobilePointsRemaining / searchPoints)
        elif activeLevel == "Level1":
            pass
        else:
            raise AssertionError(f"Unknown activeLevel: {activeLevel}")

        if desktopAndMobile:
            return RemainingSearches(
                desktop=remainingDesktopSearches, mobile=remainingMobileSearches
            )
        if self.mobile:
            return remainingMobileSearches
        return remainingDesktopSearches