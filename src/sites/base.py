import asyncio
import traceback
from abc import ABC, abstractmethod
from asyncio import Semaphore
from threading import Event
from typing import List, Dict
from typing import Optional

from aiohttp import ClientSession

from src.core.cancellation import TaskCancelled, raise_if_cancelled
from src.db import cookie
from src.epub.epub import build_epub
from src.epub.txt import build_txt
from src.models.book import Book
from src.models.chapter import Chapter
from src.models.cookie import Cookie
from src.services.models import UpdateStrategy
from src.utils.config import read_config
from src.utils.log import log


class BaseSite(ABC):
    FIELD_LABELS = {
        "site": "站点",
        "book": "书籍",
        "chapter": "章节",
        "reason": "原因",
    }

    def __init__(self, session: ClientSession):
        self.site: str = None
        self.session: ClientSession = session
        self.cancel_event: Optional[Event] = None
        self.cookie: Cookie = None
        self.books: List[Book] = []
        self._had_task_failures: bool = False
        # 默认线程 最大写死8线程别把网站玩崩了
        thread_counts = 8 if read_config("max_thread") > 8 else read_config("max_thread")
        if read_config("push_calibre")["enabled"] or read_config("max_thread") < 1:
            thread_counts = 1
        self.threads: Semaphore = asyncio.Semaphore(thread_counts)
        try:
            self.update_strategy = UpdateStrategy(str(read_config("update_strategy") or UpdateStrategy.ONLY_NEW.value))
        except ValueError:
            self.update_strategy = UpdateStrategy.ONLY_NEW
        # 白名单
        self.white_list: List[str] = [] if len(read_config("sites")) > 1 else read_config("white_list")
        # 默认请求头
        self.header: Dict[str, str] = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": read_config("ua")
        }
        # 图片下载请求头
        self.pic_header: Dict[str, str] = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": read_config("ua")
        }
        # 爬取范围
        self.start_page: int = 1 if read_config("start_page") < 1 else read_config("start_page")
        self.end_page: int = 1 if read_config("end_page") < 1 else read_config("end_page")
        if self.end_page < self.start_page:
            self.end_page = self.start_page

    def is_only_new(self) -> bool:
        return self.update_strategy == UpdateStrategy.ONLY_NEW

    def is_refresh_changed(self) -> bool:
        return self.update_strategy == UpdateStrategy.REFRESH_CHANGED

    def is_full_refetch(self) -> bool:
        return self.update_strategy == UpdateStrategy.FULL_REFETCH

    def log_event(self, prefix: str, message: str, **fields):
        parts = [f"[{prefix}] {message}"]
        for key, value in fields.items():
            if value is None or value == "":
                continue
            label = self.FIELD_LABELS.get(key, key)
            parts.append(f"{label}={value}")
        text = " | ".join(parts)
        if prefix == "ERROR":
            log.error(text)
        else:
            log.info(text)

    async def fetch_chapter_content(self, book: Book, chapter: Chapter):
        self.check_cancel_requested()
        self.log_event(
            "CHAPTER",
            "开始处理章节",
            site=self.site,
            book=book.book_name or book.book_id,
            chapter=chapter.chapter_name,
        )
        await self.build_content(chapter)
        self.check_cancel_requested()

    def check_cancel_requested(self):
        raise_if_cancelled(self.cancel_event)

    def _should_reuse_persisted_cookie(self) -> bool:
        if self.site == "lk":
            return False
        if self.site == "yuri":
            return True
        if self.site in ("esj", "masiro"):
            login_info = (read_config("login_info") or {}).get(self.site, {})
            username = str(login_info.get("username", "") or "").strip()
            password = str(login_info.get("password", "") or "").strip()
            return not (username and password)
        return True

    async def run(self):
        try:
            self.check_cancel_requested()
            # 仅在 Cookie 模式下优先复用数据库中的旧 cookie/token
            is_effective_cookie = False
            if self._should_reuse_persisted_cookie():
                self.cookie = await cookie.get_cookie(self.site)
                if self.cookie and self.cookie.cookie:
                    self.header["Cookie"] = self.cookie.cookie
                is_effective_cookie = False if not self.cookie else await self.valid_cookie()
            self.check_cancel_requested()
            if not is_effective_cookie:
                # 登录
                log.info(f"{self.site}开始登录...")
                await self.login()
                log.info(f"{self.site}登录成功")
            self.check_cancel_requested()
            # 获取书籍列表
            await self.get_book_list()
            self.check_cancel_requested()
            if not self.books:
                self.log_event("SKIP", "跳过站点", site=self.site, reason="未获取到书籍")
                return
            # 多线程开启爬虫
            self.check_cancel_requested()
            tasks = [asyncio.create_task(self.start_task(book)) for book in self.books]
            await asyncio.gather(*tasks, return_exceptions=True)
            self.check_cancel_requested()
            # 签到
            if read_config("sign"):
                self.check_cancel_requested()
                await self.sign()
                self.check_cancel_requested()
            if self.cancel_event and self.cancel_event.is_set():
                raise TaskCancelled()
            if self._had_task_failures:
                raise RuntimeError(f"{self.site}存在书籍处理失败")
        except TaskCancelled:
            raise
        except Exception as e:
            self.log_event("ERROR", "站点处理失败", site=self.site, reason=str(e))
            log.debug(traceback.format_exc())
            raise

    async def start_task(self, book: Book):
        try:
            loop = asyncio.get_running_loop()
            self.check_cancel_requested()
            async with self.threads:
                self.check_cancel_requested()
                # 构造完整书籍信息
                self.check_cancel_requested()
                await self.build_book_info(book)
                self.check_cancel_requested()
                self.log_event("BOOK", "开始处理书籍", site=self.site, book=book.book_name or book.book_id)
                log.info(f"{book.book_name} {self.site}书籍信息已获取")
                # 构造章节列表
                log.info(f"{self.site}开始获取章节列表...")
                self.check_cancel_requested()
                await self.build_chapter_list(book)
                self.check_cancel_requested()
                if not book.chapters:
                    self.log_event("SKIP", "跳过书籍", site=self.site, book=book.book_name or book.book_id, reason="未获取到章节")
                    return
                log.info(f"{book.book_name} {self.site}章节信息已全部获取")
                # 构造图片
                for chapter in book.chapters:
                    self.check_cancel_requested()
                    if chapter.content:
                        await self.build_pic_list(chapter)
                        self.check_cancel_requested()
                # epub
                self.check_cancel_requested()
                await loop.run_in_executor(None, build_epub, book)
                # txt
                if read_config("convert_txt"):
                    await loop.run_in_executor(None, build_txt, book)
                self.log_event("EXPORT", "导出完成", site=self.site, book=book.book_name or book.book_id)
        except TaskCancelled:
            raise
        except Exception as e:
            self._had_task_failures = True
            self.log_event("ERROR", "书籍处理失败", site=self.site, book=book.book_name or book.book_id, reason=str(e))
            log.debug(traceback.format_exc())

    @abstractmethod
    async def valid_cookie(self) -> bool:
        pass

    @abstractmethod
    async def login(self):
        pass

    @abstractmethod
    async def get_book_list(self):
        pass

    @abstractmethod
    async def build_book_info(self, book: Book):
        pass

    @abstractmethod
    async def build_chapter_list(self, book: Book):
        pass

    @abstractmethod
    async def build_pic_list(self, chapter: Chapter):
        pass

    @abstractmethod
    async def build_content(self, chapter: Chapter):
        pass

    @abstractmethod
    async def sign(self):
        pass
