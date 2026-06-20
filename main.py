# main.py
import os
import asyncio
import time
import json
import random
import datetime
import openpyxl
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class InstagramParser:
    def __init__(self, cookies_file='cookies.json'):
        self.cookies_file = cookies_file
        self.driver = None
        self.collected_usernames = set()

    def setup_driver(self):
        print("[SETUP] Запуск браузера...")
        options = Options()
        
        # HEADLESS режим для Railway
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--remote-debugging-port=9222')
        
        # Для Railway/Docker
        options.binary_location = os.getenv('GOOGLE_CHROME_BIN', '/usr/bin/chromium')
        
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        try:
            # Пробуем использовать chromedriver из системы
            chromedriver_path = os.getenv('CHROMEDRIVER_PATH', '/usr/bin/chromedriver')
            if os.path.exists(chromedriver_path):
                service = Service(chromedriver_path)
                print(f"[SETUP] Используем системный chromedriver: {chromedriver_path}")
            else:
                # Fallback на webdriver-manager (локально)
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                print("[SETUP] Используем webdriver-manager")
            
            self.driver = webdriver.Chrome(service=service, options=options)
            print("[SETUP] Драйвер готов (headless режим)")
        except Exception as e:
            print(f"[ERROR] Не удалось запустить браузер: {e}")
            raise

    def teardown(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            print("[DONE] Браузер закрыт")

    def load_cookies(self):
        print(f"[COOKIES] Загрузка cookies из {self.cookies_file}")
        try:
            with open(self.cookies_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
        except Exception as e:
            print(f"[ERROR] Не удалось загрузить cookies: {e}")
            return False

        self.driver.get("https://www.instagram.com/")
        time.sleep(3)

        added = 0
        for c in cookies:
            try:
                if 'instagram' not in c.get('domain', ''):
                    continue
                self.driver.add_cookie({
                    'name': c.get('name'),
                    'value': c.get('value'),
                    'domain': '.instagram.com'
                })
                added += 1
            except Exception:
                pass

        print(f"[COOKIES] Добавлено {added} cookies")
        self.driver.refresh()
        time.sleep(3)
        return True

    def go_to_profile(self, username: str):
        url = f"https://www.instagram.com/{username}/"
        print(f"[NAVIGATION] Открываю профиль: {url}")
        self.driver.get(url)
        time.sleep(3)

    def open_modal(self, mode: str):
        print(f"[MODAL] Открываю список: {mode}")
        try:
            if mode == "followers":
                btn = WebDriverWait(self.driver, 12).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, '/followers')]"))
                )
            else:
                try:
                    btn = WebDriverWait(self.driver, 8).until(
                        EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, '/following')]"))
                    )
                except TimeoutException:
                    btn = WebDriverWait(self.driver, 8).until(
                        EC.element_to_be_clickable((By.XPATH,
                          "/html/body/div[1]/div/div/div[2]/div/div/div[1]/div[2]/div[1]/section/main/div/div/header/div/section[2]/div/div[3]/div[3]/a"))
                    )
            btn.click()
            time.sleep(3)
            WebDriverWait(self.driver, 12).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
            )
            print("[MODAL] Модалка открыта")
            return True
        except Exception as e:
            print(f"[ERROR] Не удалось открыть окно: {e}")
            return False

    def _get_scroll_container(self, mode: str):
        print(f"[SCROLL] Поиск контейнера для режима: {mode}")
        xpaths = []

        if mode == "followers":
            xpaths = [
                "//div[@role='dialog']//div[contains(@class,'x7r02ix')]",
                "//div[@role='dialog']//div[@class='_aano']",
                "/html/body/div[4]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div/div[2]/div/div/div[3]",
            ]
        else:
            xpaths = [
                "/html/body/div[4]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div/div[2]/div/div/div[3]",
                "//div[@role='dialog']//div[contains(@class,'x7r02ix')]",
                "//div[@role='dialog']//div[@class='_aano']",
            ]

        for i, xpath in enumerate(xpaths, 1):
            try:
                container = self.driver.find_element(By.XPATH, xpath)
                print(f"[SCROLL] ✓ Контейнер найден (вариант {i})")
                is_scrollable = self.driver.execute_script("""
                    const el = arguments[0];
                    const hasScroll = el.scrollHeight > el.clientHeight;
                    const style = window.getComputedStyle(el);
                    const isOverflow = style.overflowY === 'auto' || style.overflowY === 'scroll';
                    return hasScroll && isOverflow;
                """, container)
                if is_scrollable:
                    print(f"[SCROLL] ✓ Контейнер подтверждён как скроллируемый")
                    return container
                else:
                    print(f"[SCROLL] ⚠ Контейнер не скроллируется. Пробуем следующий...")
            except NoSuchElementException:
                print(f"[SCROLL] ✗ Вариант {i} не найден")
                continue

        print("[SCROLL] Пытаемся найти через JavaScript...")
        try:
            container = self.driver.execute_script("""
                const dialog = document.querySelector('div[role="dialog"]');
                if (!dialog) return null;
                function findScrollable(element, depth = 0) {
                    if (depth > 10) return null;
                    const style = window.getComputedStyle(element);
                    const hasOverflow = style.overflowY === 'auto' || style.overflowY === 'scroll';
                    const hasScroll = element.scrollHeight > element.clientHeight;
                    if (hasOverflow && hasScroll) return element;
                    for (let child of element.children) {
                        const found = findScrollable(child, depth + 1);
                        if (found) return found;
                    }
                    return null;
                }
                return findScrollable(dialog);
            """)
            if container:
                print("[SCROLL] ✓ Контейнер найден через JavaScript")
                return container
        except Exception as e:
            print(f"[SCROLL] JS поиск не удался: {e}")

        print("[ERROR] ✗ Контейнер для скролла не найден")
        return None

    def extract_usernames(self) -> int:
        new_count = 0
        try:
            users = self.driver.find_elements(
                By.XPATH,
                "//a[contains(@href, '/') and contains(@class, '_a6hd')]"
            )
            for u in users:
                href = u.get_attribute('href')
                if href:
                    username = href.rstrip('/').split('/')[-1]
                    if username not in self.collected_usernames:
                        self.collected_usernames.add(username)
                        new_count += 1
        except Exception as e:
            print(f"[ERROR] Ошибка при извлечении имён: {e}")
        return new_count

    def _has_recommendations_block(self) -> bool:
        try:
            block = self.driver.find_elements(
                By.XPATH, "//h4[contains(text(), 'Рекомендации для вас')]"
            )
            return len(block) > 0
        except Exception:
            return False

    def scroll_and_collect(self, mode: str):
        print("[SCROLL] Старт сбора…")
        self.collected_usernames.clear()

        container = self._get_scroll_container(mode)
        if not container:
            print("[ERROR] Невозможно продолжить без контейнера")
            return

        no_new, iteration = 0, 0

        while True:
            iteration += 1
            new_found = self.extract_usernames()
            total = len(self.collected_usernames)
            print(f"[ИТЕРАЦИЯ {iteration}] Новых: {new_found} | Всего: {total}")

            if self._has_recommendations_block():
                print("[INFO] Найден блок 'Рекомендации для вас' — стоп.")
                break

            if new_found == 0:
                no_new += 1
                if no_new >= 15:
                    print("[SCROLL] 15 итераций без новых — стоп")
                    break
            else:
                no_new = 0

            scroll_success = False
            try:
                self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", container)
                scroll_success = True
            except Exception as e:
                print(f"[DEBUG] Метод 1 не сработал: {e}")

            if not scroll_success:
                try:
                    self.driver.execute_script("arguments[0].scrollBy(0, arguments[0].clientHeight)", container)
                    scroll_success = True
                except Exception as e:
                    print(f"[DEBUG] Метод 2 не сработал: {e}")

            if not scroll_success:
                try:
                    from selenium.webdriver.common.action_chains import ActionChains
                    actions = ActionChains(self.driver)
                    actions.move_to_element(container).perform()
                    self.driver.execute_script(
                        "arguments[0].dispatchEvent(new WheelEvent('wheel', {deltaY: 500}))", container
                    )
                    scroll_success = True
                except Exception as e:
                    print(f"[DEBUG] Метод 3 не сработал: {e}")

            if not scroll_success:
                print("[ERROR] ВСЕ методы скролла не сработали!")
                break

            time.sleep(random.uniform(0.1, 0.4))
            time.sleep(3)

        print(f"[РЕЗУЛЬТАТ] Собрано {len(self.collected_usernames)} username'ов")

    def save_excel(self, username: str, mode: str) -> Path:
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        fname = f"{mode}_{username}_{now}.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Users"
        ws.append(["Username"])
        for name in sorted(self.collected_usernames):
            ws.append([name])
        wb.save(fname)
        print(f"[SAVE] {len(self.collected_usernames)} имён сохранено в {fname}")
        return Path(fname)

    def run_once(self, username: str, mode: str) -> Path | None:
        try:
            self.setup_driver()
            if not self.load_cookies():
                print("[ERROR] Cookies не загружены")
            self.go_to_profile(username)
            if not self.open_modal(mode):
                return None
            self.scroll_and_collect(mode)
            if self.collected_usernames:
                return self.save_excel(username, mode)
            else:
                print("[WARNING] Не собрано ни одного имени")
                return None
        finally:
            self.teardown()


# ====================== TELEGRAM BOT ======================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Укажи BOT_TOKEN в переменных окружения")

router = Router()


class ParseStates(StatesGroup):
    waiting_username = State()


@router.message(Command("start"))
async def cmd_start(msg: types.Message):
    text = (
        "Привет! Я парсю Instagram (headless режим для Railway).\n\n"
        "Команды:\n"
        "/parse — ввести username (без @). Бот соберёт подписчиков и подписки.\n\n"
        "⚠️ Нужны валидные cookies.json"
    )
    await msg.answer(text, parse_mode="Markdown")


@router.message(Command("parse"))
async def cmd_parse(msg: types.Message, state: FSMContext):
    await state.set_state(ParseStates.waiting_username)
    await msg.answer("Введи username профиля (без @):", parse_mode="Markdown")


@router.message(ParseStates.waiting_username)
async def handle_username(msg: types.Message, state: FSMContext):
    username = (msg.text or "").strip().lstrip("@")
    if not username:
        await msg.reply("Нужно указать username")
        return

    await state.clear()
    await msg.answer(f"Начинаю парсинг: @{username}", parse_mode="Markdown")

    loop = asyncio.get_running_loop()

    async def run_mode_and_send(mode: str, title: str):
        await msg.answer(f"▶️ {title}…")

        def runner():
            parser = InstagramParser(cookies_file="cookies.json")
            return parser.run_once(username=username, mode=mode)

        path: Path | None = await loop.run_in_executor(None, runner)
        if path and path.exists():
            await msg.answer_document(
                types.FSInputFile(path),
                caption=f"{title} — готово"
            )
            # Удаляем файл после отправки
            try:
                path.unlink()
            except:
                pass
        else:
            await msg.answer(f"⚠️ {title}: ничего не собрано")

    await run_mode_and_send("followers", "Подписчики")
    await run_mode_and_send("following", "Подписки")

    await msg.answer("✅ Готово")


async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    print("[BOT] Запуск бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("[BOT] Остановлен")
