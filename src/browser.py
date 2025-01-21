import argparse
import contextlib
import locale
import logging
import os
import random
import json
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
        self.webdriver = None
        self.utils = None
        self.setup_browser()
        logging.debug("out __init__")

    def setup_browser(self):
        """Setup browser instance with proper error handling"""
        try:
            self.webdriver = self.browserSetup()
            self._setup_cdp_listeners()
            self.utils = Utils(self.webdriver)
        except Exception as e:
            logging.error(f"Error setting up browser: {str(e)}")
            self.cleanup()
            raise

    def cleanup(self):
        """Clean up browser resources"""
        if self.webdriver:
            try:
                self.webdriver.close()
                self.webdriver.quit()
            except Exception as e:
                logging.error(f"Error during browser quit: {str(e)}")
            finally:
                self.webdriver = None
                self.utils = None

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
        self.cleanup()

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

        # Enhanced stealth script optimized for Microsoft services
        stealth_js = """
            (() => {
                // Advanced stealth script optimized for Microsoft services
                const hookProperty = (obj, prop, value) => {
                    try {
                        Object.defineProperty(obj, prop, {
                            get() { return value; },
                            set(v) { value = v; }
                        });
                    } catch (e) {}
                };

                // Microsoft-specific navigator properties
                hookProperty(navigator, 'msMaxTouchPoints', 0);
                hookProperty(navigator, 'msManipulationViewsEnabled', false);
                hookProperty(navigator, 'msPointerEnabled', false);

                // Enhanced permissions handling
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.__proto__.query = parameters =>
                    parameters.name === 'notifications'
                        ? Promise.resolve({state: Notification.permission})
                        : originalQuery(parameters);

                // WebGL enhancements for Microsoft services
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    const gl = this;
                    
                    // Randomize WebGL parameters slightly
                    if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                        const vendors = ['Google Inc. (Intel)', 'Intel Inc.', 'Intel Open Source Technology Center'];
                        return vendors[Math.floor(Math.random() * vendors.length)];
                    }
                    if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                        const renderers = [
                            'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)',
                            'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)',
                            'ANGLE (Intel, Intel(R) HD Graphics 620 Direct3D11 vs_5_0 ps_5_0)'
                        ];
                        return renderers[Math.floor(Math.random() * renderers.length)];
                    }
                    return getParameter.apply(gl, arguments);
                };

                // Enhanced screen properties
                const screenProps = {
                    width: """ + str(screenWidth) + """,
                    height: """ + str(screenHeight) + """,
                    availWidth: """ + str(screenWidth) + """,
                    availHeight: """ + str(screenHeight) + """,
                    colorDepth: 24,
                    pixelDepth: 24,
                    availLeft: 0,
                    availTop: 0
                };

                for (const [key, value] of Object.entries(screenProps)) {
                    hookProperty(window.screen, key, value);
                }

                // Microsoft-specific window properties
                hookProperty(window, 'innerWidth', """ + str(deviceWidth) + """);
                hookProperty(window, 'innerHeight', """ + str(deviceHeight) + """);
                hookProperty(window, 'outerWidth', """ + str(screenWidth) + """);
                hookProperty(window, 'outerHeight', """ + str(screenHeight) + """);

                // Enhanced plugin spoofing
                const createFakePluginArray = () => {
                    const plugins = [
                        {
                            0: {type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format'},
                            description: 'Portable Document Format',
                            filename: 'internal-pdf-viewer',
                            length: 1,
                            name: 'Chrome PDF Plugin'
                        },
                        {
                            0: {type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format'},
                            description: 'Portable Document Format',
                            filename: 'internal-pdf-viewer',
                            length: 1,
                            name: 'Chrome PDF Viewer'
                        },
                        {
                            0: {type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable'},
                            1: {type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable'},
                            description: 'Native Client',
                            filename: 'internal-nacl-plugin',
                            length: 2,
                            name: 'Native Client'
                        }
                    ];

                    plugins.__proto__ = {
                        item: function(index) { return this[index]; },
                        namedItem: function(name) { return this[name]; },
                        refresh: function() {},
                        [Symbol.iterator]: function* () {
                            for (let i = 0; i < this.length; i++) {
                                yield this[i];
                            }
                        }
                    };

                    return Object.setPrototypeOf(plugins, Plugin.prototype);
                };

                hookProperty(navigator, 'plugins', createFakePluginArray());

                // Enhanced Chrome runtime
                if (window.chrome) {
                    const originalChrome = window.chrome;
                    window.chrome = {
                        ...originalChrome,
                        runtime: {
                            ...originalChrome.runtime,
                            connect: () => ({
                                onMessage: {
                                    addListener: () => {},
                                    removeListener: () => {}
                                },
                                postMessage: () => {},
                                disconnect: () => {}
                            }),
                            sendMessage: () => {},
                            onMessage: {
                                addListener: () => {},
                                removeListener: () => {}
                            }
                        },
                        csi: () => {},
                        loadTimes: () => {}
                    };
                }

                // Enhanced error handling
                window.onerror = function(msg, url, line, col, error) {
                    if (msg.toLowerCase().includes('automation') || 
                        msg.toLowerCase().includes('webdriver') ||
                        msg.toLowerCase().includes('selenium')) {
                        return true;
                    }
                };

                // Override property descriptors
                const overridePropertyDescriptor = (obj, prop, value) => {
                    try {
                        Object.defineProperty(obj, prop, {
                            get() { return value; }
                        });
                    } catch (e) {}
                };

                // Enhanced navigator properties
                overridePropertyDescriptor(navigator, 'productSub', '20100101');
                overridePropertyDescriptor(navigator, 'vendor', 'Google Inc.');
                overridePropertyDescriptor(navigator, 'hardwareConcurrency', 8);
                overridePropertyDescriptor(navigator, 'deviceMemory', 8);
                overridePropertyDescriptor(navigator, 'webdriver', undefined);
                overridePropertyDescriptor(navigator, 'connection', {
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                });

                // Add natural browser behavior
                let lastMouseMove = 0;
                document.addEventListener('mousemove', function(e) {
                    const now = Date.now();
                    if (now - lastMouseMove < 10) return;
                    lastMouseMove = now;
                }, true);

                document.addEventListener('mousedown', function(e) {
                    if (e.isTrusted === false) return;
                }, true);

                // Override toString for native functions
                const _toString = Function.prototype.toString;
                Function.prototype.toString = function() {
                    if (this === Function.prototype.toString) return _toString.call(_toString);
                    if (this === Function.prototype.bind) return 'function bind() { [native code] }';
                    return _toString.call(this);
                };
            })();
        """

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
                    "acceptLanguage": f"{self.localeLang}-{self.localeGeo},{self.localeLang};q=0.9,en;q=0.8"
                },
            ),
            (
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": stealth_js
                }
            ),
            # Enhanced CDP commands for Microsoft services
            ("Page.setBypassCSP", {"enabled": True}),
            ("Network.setBypassServiceWorker", {"bypass": True}),
            ("Network.enable", {}),
            ("Page.enable", {}),
            ("DOM.enable", {}),
            
            # Set custom headers
            ("Network.setExtraHTTPHeaders", {
                "headers": {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": f"{self.localeLang}-{self.localeGeo},{self.localeLang};q=0.9,en;q=0.8",
                    "DNT": "1",
                    "Upgrade-Insecure-Requests": "1"
                }
            })
        ]

        # Add permission grants for specific Microsoft domains
        microsoft_domains = [
            "https://www.bing.com",
            "https://rewards.bing.com",
            "https://account.microsoft.com",
            "https://login.live.com"
        ]
        
        for domain in microsoft_domains:
            cdp_commands.append((
                "Browser.grantPermissions",
                {
                    "origin": domain,
                    "permissions": [
                        "geolocation",
                        "notifications",
                        "midi"
                    ]
                }
            ))

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
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-search-engine-choice-screen")  # 153


        # Enhanced privacy and security options
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process,AutomationControlled")
        options.add_argument("--disable-blink-features")

        # Performance and stability options
        options.add_argument("--disable-dev-tools")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-component-extensions-with-background-pages")
        options.add_argument("--disable-features=TranslateUI")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--force-color-profile=srgb")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-first-run")

        # Microsoft-specific options
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-domain-reliability")
        options.add_argument("--disable-client-side-phishing-detection")

        # Set Chrome preferences instead of experimental options
        prefs = {
            'enable_automation': False,
            'credentials_enable_service': False,
            'profile.password_manager_enabled': False
        }
        options.add_experimental_option('prefs', prefs)


        options.page_load_strategy = "eager"

        seleniumwireOptions: dict[str, Any] = {
            "verify_ssl": False,
            "suppress_connection_errors": True,
            "exclude_hosts": [
                "google-analytics.com",
                "doubleclick.net",
                "bat.bing.com",
                "browser.events.data.msn.com"
            ]
        }

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