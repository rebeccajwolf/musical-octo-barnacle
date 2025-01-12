import contextlib
import logging
import time
from random import randint
from time import sleep

from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.keys import Keys

from src.browser import Browser
from src.constants import REWARDS_URL
from src.utils import CONFIG, sendNotification, getAnswerCode

# todo These are US-English specific, maybe there's a good way to internationalize
ACTIVITY_TITLE_TO_SEARCH = {
    "Black Friday shopping": "black friday deals",
    "Discover open job roles": "jobs at microsoft",
    "Expand your vocabulary": "define demure",
    "Find places to stay": "hotels rome italy",
    "Find somewhere new to explore": "directions to new york",
    "Gaming time": "vampire survivors video game",
    "Get your shopping done faster": "new iphone",
    "Houses near you": "apartments manhattan",
    "How's the economy?": "sp 500",
    "Learn to cook a new recipe": "how cook pierogi",
    "Let's watch that movie again!": "aliens movie",
    "Plan a quick getaway": "flights nyc to paris",
    "Prepare for the weather": "weather tomorrow",
    "Quickly convert your money": "convert 374 usd to yen",
    "Search the lyrics of a song": "black sabbath supernaut lyrics",
    "Stay on top of the elections": "election news latest",
    "Too tired to cook tonight?": "Pizza Hut near me",
    "Translate anything": "translate pencil sharpener to spanish",
    "What time is it?": "china time",
    "What's for Thanksgiving dinner?": "pumpkin pie recipe",
    "Who won?": "braves score",
    "You can track your package": "usps tracking",
}


class Activities:
    def __init__(self, browser: Browser):
        self.browser = browser
        self.webdriver = browser.webdriver

    def openDailySetActivity(self, cardId: int):
        # Open the Daily Set activity for the given cardId
        cardId += 1
        element = self.webdriver.find_element(
            By.XPATH,
            f'//*[@id="daily-sets"]/mee-card-group[1]/div/mee-card[{cardId}]/div/card-content/mee-rewards-daily-set-item-content/div/a',
        )
        self.browser.utils.click(element)
        self.browser.utils.switchToNewTab()

    def openMorePromotionsActivity(self, cardId: int):
        cardId += 1
        # Open the More Promotions activity for the given cardId
        element = self.webdriver.find_element(
            By.CSS_SELECTOR,
            f"#more-activities > .m-card-group > .ng-scope:nth-child({cardId}) .ds-card-sec",
        )
        self.browser.utils.click(element)
        # self.browser.utils.switchToNewTab()

    def completeSearch(self):
        # Simulate completing a search activity
        # for _ in range(1):
        #     html = self.webdriver.find_element(By.TAG_NAME, 'html')
        #     for _ in range(3):
        #         html.send_keys(Keys.END)
        #         html.send_keys(Keys.HOME)
        #     try:
        #         sleep(1.5)
        #         searchbar = self.webdriver.find_element(By.XPATH, '//*[@id="sb_form_q"]')
        #         searchbar.click()
        #         sleep(1.5)
        #         self.webdriver.find_element(By.ID, "b_header").click()
        #         sleep(1.5)
        #     except:
        #         pass
        #     self.webdriver.refresh()
        #     sleep(3.5)
        pass

    def completeSurvey(self):
        # Simulate completing a survey activity
        # noinspection SpellCheckingInspection
        self.webdriver.find_element(By.ID, f"btoption{randint(0, 1)}").click()
        
    def waitUntilQuizLoads(self):
        """Wait until quiz loads"""
        tries = 0
        refreshCount = 0
        while True:
            try:
                self.webdriver.find_element(
                    By.XPATH, '//*[@id="currentQuestionContainer"]')
                return True
            except:
                if tries < 10:
                    tries += 1
                    sleep(0.5)
                else:
                    if refreshCount < 5:
                        self.webdriver.refresh()
                        refreshCount += 1
                        tries = 0
                        sleep(5)
                    else:
                        return False

    def completeQuiz(self):
        # Simulate completing a quiz activity
        # with contextlib.suppress(TimeoutException):
            # startQuiz = self.browser.utils.waitUntilQuizLoads()
            # self.browser.utils.click(startQuiz)
        sleep(12)
        if not self.waitUntilQuizLoads():
            self.browser.utils.resetTabs()
            return
        with contextlib.suppress(TimeoutException):
            startQuiz = self.browser.utils.waitUntilQuizLoads()
            self.browser.utils.click(startQuiz)
        self.browser.utils.waitUntilVisible(
            By.XPATH, '//*[@id="currentQuestionContainer"]/div/div[1]', 180
        )
        currentQuestionNumber: int = self.webdriver.execute_script(
            "return _w.rewardsQuizRenderInfo.currentQuestionNumber"
        )
        maxQuestions = self.webdriver.execute_script(
            "return _w.rewardsQuizRenderInfo.maxQuestions"
        )
        numberOfOptions = self.webdriver.execute_script(
            "return _w.rewardsQuizRenderInfo.numberOfOptions"
        )
        for _ in range(currentQuestionNumber, maxQuestions + 1):
            if numberOfOptions == 8:
                answers = []
                for i in range(numberOfOptions):
                    isCorrectOption = self.webdriver.find_element(
                        By.ID, f"rqAnswerOption{i}"
                    ).get_attribute("iscorrectoption")
                    if isCorrectOption and isCorrectOption.lower() == "true":
                        answers.append(f"rqAnswerOption{i}")
                for answer in answers:
                    element = self.webdriver.find_element(By.ID, answer)
                    self.browser.utils.click(element)
                    self.browser.utils.waitUntilQuestionRefresh()
            elif numberOfOptions in [2, 3, 4]:
                correctOption = self.webdriver.execute_script(
                    "return _w.rewardsQuizRenderInfo.correctAnswer"
                )
                for i in range(numberOfOptions):
                    if (
                        self.webdriver.find_element(
                            By.ID, f"rqAnswerOption{i}"
                        ).get_attribute("data-option")
                        == correctOption
                    ):
                        element = self.webdriver.find_element(
                            By.ID, f"rqAnswerOption{i}"
                        )
                        self.browser.utils.click(element)

                        self.browser.utils.waitUntilQuestionRefresh()
                        break

    def completeABC(self):
        # Simulate completing an ABC activity
        counter = self.webdriver.find_element(
            By.XPATH, '//*[@id="QuestionPane0"]/div[2]'
        ).text[:-1][1:]
        numberOfQuestions = max(int(s) for s in counter.split() if s.isdigit())
        for question in range(numberOfQuestions):
            element = self.webdriver.find_element(
                By.ID, f"questionOptionChoice{question}{randint(0, 2)}"
            )
            self.browser.utils.click(element)
            sleep(randint(10, 15))
            element = self.webdriver.find_element(By.ID, f"nextQuestionbtn{question}")
            self.browser.utils.click(element)
            sleep(randint(10, 15))

    def completeThisOrThat(self):
        # Simulate completing a This or That activity
        # startQuiz = self.browser.utils.waitUntilQuizLoads()
        # self.browser.utils.click(startQuiz)
        sleep(12)
        if not self.waitUntilQuizLoads():
            self.browser.utils.resetTabs()
            return
        with contextlib.suppress(TimeoutException):
            startQuiz = self.browser.utils.waitUntilQuizLoads()
            self.browser.utils.click(startQuiz)
        self.browser.utils.waitUntilVisible(
            By.XPATH, '//*[@id="currentQuestionContainer"]/div/div[1]', 180
        )
        sleep(randint(10, 15))
        for _ in range(10):
            correctAnswerCode = self.webdriver.execute_script(
                "return _w.rewardsQuizRenderInfo.correctAnswer"
            )
            answer1, answer1Code = self.getAnswerAndCode("rqAnswerOption0")
            answer2, answer2Code = self.getAnswerAndCode("rqAnswerOption1")
            answerToClick: WebElement
            if answer1Code == correctAnswerCode:
                answerToClick = answer1
            elif answer2Code == correctAnswerCode:
                answerToClick = answer2

            self.browser.utils.click(answerToClick)
            sleep(randint(10, 15))

    def getAnswerAndCode(self, answerId: str) -> tuple[WebElement, str]:
        # Helper function to get answer element and its code
        answerEncodeKey = self.webdriver.execute_script("return _G.IG")
        answer = self.webdriver.find_element(By.ID, answerId)
        answerTitle = answer.get_attribute("data-option")
        return (
            answer,
            getAnswerCode(answerEncodeKey, answerTitle),
        )

    def doActivity(self, activity: dict, activities: list[dict]) -> None:
        try:
            activityTitle = cleanupActivityTitle(activity["title"])
            logging.debug(f"activityTitle={activityTitle}")
            if activity["complete"] is True or activity["pointProgressMax"] == 0 or activity["exclusiveLockedFeatureStatus"] == "locked":
                logging.debug("Already done, returning")
                return
            if activityTitle in CONFIG.get("apprise").get("notify").get(
                "incomplete-activity"
            ).get("ignore"):
                logging.debug(f"Ignoring {activityTitle}")
                return
            # Open the activity for the activity
            cardId = activities.index(activity)
            isDailySet = (
                "daily_set_date" in activity["attributes"]
                and activity["attributes"]["daily_set_date"]
            )
            if isDailySet:
                self.openDailySetActivity(cardId)
            else:
                self.openMorePromotionsActivity(cardId)
            self._process_activity_with_heartbeat(activityTitle, activity)
        except Exception:
            logging.error(f"[ACTIVITY] Error doing {activityTitle}", exc_info=True)
        self.browser.utils.resetTabs()

    def _process_activity_with_heartbeat(self, activityTitle: str, activity: dict):
        """Process activity while maintaining heartbeat"""
        try:
            # Create a heartbeat event for this specific activity
            activity_start_time = time.time()
            
            def activity_heartbeat():
                while True:
                    try:
                        current_time = time.time()
                        # Log activity with duration
                        logging.info(f"Activity '{activityTitle}' running for {int(current_time - activity_start_time)}s")
                        
                        # Browser activity simulation
                        if hasattr(self, 'webdriver'):
                            try:
                                # Execute multiple small JavaScript actions
                                self.webdriver.execute_script("window.scrollBy(0, Math.random()*10);")
                                self.webdriver.execute_script(
                                    "document.body.dispatchEvent(new MouseEvent('mousemove', "
                                    "{clientX: Math.random()*500, clientY: Math.random()*500}));"
                                )
                                
                                # Keep the page active
                                self.webdriver.execute_script("window.focus();")
                                
                                # Simulate user interaction
                                self.webdriver.execute_script(
                                    "document.activeElement && document.activeElement.blur();"
                                )
                                
                            except Exception as e:
                                logging.debug(f"Browser simulation error (non-critical): {str(e)}")
                        
                        # Python process activity
                        cpu_work = sum(random.random() for _ in range(1000))
                        
                        # File system activity
                        with open("/tmp/activity_heartbeat", "w") as f:
                            f.write(f"{time.time()}:{cpu_work}")
                            f.flush()
                            os.fsync(f.fileno())
                        
                        # Network activity
                        requests.head("https://huggingface.co", timeout=2)
                        
                    except Exception as e:
                        logging.warning(f"Activity heartbeat error: {str(e)}")
                        
                    time.sleep(1)  # Short sleep between heartbeats
            
            # Start heartbeat in a daemon thread
            import threading
            heartbeat_thread = threading.Thread(target=activity_heartbeat, daemon=True)
            heartbeat_thread.start()
            
            # Original activity processing
            sleep(2)
            try:
                if self.webdriver.find_element(By.XPATH, '//*[@id="modal-host"]/div[2]/button').is_displayed():
                    self.webdriver.find_element(By.XPATH, '//*[@id="modal-host"]/div[2]/button').click()
                    return
                else:
                    self.browser.utils.switchToNewTab()
            except:
                pass
            sleep(2)
            
            with contextlib.suppress(TimeoutException):
                searchbar = self.browser.utils.waitUntilClickable(By.ID, "sb_form_q")
                self.browser.utils.click(searchbar)
                
            logging.info(activityTitle)
            if activityTitle in ACTIVITY_TITLE_TO_SEARCH:
                searchbar.send_keys(ACTIVITY_TITLE_TO_SEARCH[activityTitle])
                sleep(1)
                searchbar.submit()
            elif "poll" in activityTitle:
                logging.info(f"[ACTIVITY] Completing poll of card")
                self.completeSurvey()
            elif activity["promotionType"] == "urlreward":
                self.completeSearch()
            elif activity["promotionType"] == "quiz":
                if activity["pointProgressMax"] == 10:
                    self.completeABC()
                elif activity["pointProgressMax"] in [30, 40]:
                    self.completeQuiz()
                elif activity["pointProgressMax"] == 50:
                    self.completeThisOrThat()
            else:
                self.completeSearch()
                
            # More frequent heartbeats with shorter intervals
            total_sleep = randint(10, 20)  # Reduced sleep time
            chunk_size = 2  # Smaller chunks
            
            for _ in range(0, total_sleep, chunk_size):
                try:
                    # Multiple activity simulations
                    self.webdriver.execute_script("window.scrollBy(0, Math.random()*10);")
                    self.webdriver.execute_script(
                        "document.body.dispatchEvent(new MouseEvent('mousemove', "
                        "{clientX: Math.random()*500, clientY: Math.random()*500}));"
                    )
                    
                    # Keep both Python and browser active
                    cpu_work = sum(random.random() for _ in range(100))
                    with open("/tmp/activity_progress", "w") as f:
                        f.write(f"{time.time()}:{cpu_work}")
                        f.flush()
                    
                except Exception as e:
                    logging.debug(f"Activity simulation error: {str(e)}")
                    
                sleep(chunk_size)
                
        except Exception as e:
            logging.error(f"Error in activity processing: {str(e)}")
            raise

    def completeActivities(self):
        logging.info("[DAILY SET] " + "Trying to complete the Daily Set...")
        dailySetPromotions = self.browser.utils.getDailySetPromotions()
        self.browser.utils.goToRewards()
        for activity in dailySetPromotions:
            self.doActivity(activity, dailySetPromotions)
        logging.info("[DAILY SET] Done")

        logging.info("[MORE PROMOS] " + "Trying to complete More Promotions...")
        morePromotions: list[dict] = self.browser.utils.getMorePromotions()
        self.browser.utils.goToRewards()
        for activity in morePromotions:
            self.doActivity(activity, morePromotions)
        logging.info("[MORE PROMOS] Done")

        # todo Send one email for all accounts?
        # fixme This is falsely considering some activities incomplete when complete
        if (
            CONFIG.get("apprise")
            .get("notify")
            .get("incomplete-activity")
            .get("enabled")
        ):
            incompleteActivities: dict[str, tuple[str, str, str]] = {}
            for activity in (
                self.browser.utils.getDailySetPromotions()
                + self.browser.utils.getMorePromotions()
            ):  # Have to refresh
                if activity["pointProgress"] < activity["pointProgressMax"]:
                    incompleteActivities[cleanupActivityTitle(activity["title"])] = (
                        activity["promotionType"],
                        activity["pointProgress"],
                        activity["pointProgressMax"],
                    )
            for incompleteActivityToIgnore in (
                CONFIG.get("apprise")
                .get("notify")
                .get("incomplete-activity")
                .get("ignore")
            ):
                incompleteActivities.pop(incompleteActivityToIgnore, None)
            if incompleteActivities:
                logging.info(f"incompleteActivities: {incompleteActivities}")
                sendNotification(
                    f"We found some incomplete activities for {self.browser.username}",
                    str(incompleteActivities) + "\n" + REWARDS_URL,
                )


def cleanupActivityTitle(activityTitle: str) -> str:
    return activityTitle.replace("\u200b", "").replace("\xa0", " ")