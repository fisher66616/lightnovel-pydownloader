import aiohttp
from threading import Event
from typing import Optional

from src.core.cancellation import raise_if_cancelled
from src.db.book import get_book_by_id, get_all_book, get_books_by_ids
from src.db.chapter import get_chapter, get_chapter_list, get_nopay_chapters
from src.db.pic import clear_all_pic, fail_pic_list, update_pic, get_pic_list
from src.epub.epub import build_epub
from src.epub.txt import build_txt
from src.sites.esj import Esj
from src.sites.fish import Fish
from src.sites.lk import LK
from src.sites.masiro import Masiro
from src.sites.yuri import Yuri
from src.utils import request
from src.utils.config import read_config
from src.utils.log import log


class Process(object):
    def __init__(self, cancel_event: Optional[Event] = None):
        self.cancel_event = cancel_event

    def check_cancel_requested(self):
        raise_if_cancelled(self.cancel_event)

    async def run(self):
        flag = True
        self.check_cancel_requested()
        if read_config("clear_pic_table"):
            # 删图片库
            await self.clear_pic_table()
            flag = False
            self.check_cancel_requested()
        if read_config("download_pic_again"):
            # 重新下载图片
            await self.download_pic_again()
            flag = False
            self.check_cancel_requested()
        if read_config("export_epub_again"):
            # 重新导出epub
            await self.export_epub_again()
            flag = False
            self.check_cancel_requested()
        if not flag:
            return
        site_map = {
            "esj": Esj,
            "lk": LK,
            "masiro": Masiro,
            "yuri": Yuri,
            "fish": Fish,
        }
        for site in read_config("sites"):
            self.check_cancel_requested()
            log.info(f"[TASK] 开始请求站点 | 站点={site}")
            jar = aiohttp.CookieJar()
            conn = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=conn, cookie_jar=jar) as session:
                if site in site_map:
                    site_instance = site_map[site](session)
                    site_instance.cancel_event = self.cancel_event
                    await site_instance.run()
            self.check_cancel_requested()
        log.info("本次爬取任务结束")

    async def clear_pic_table(self):
        self.check_cancel_requested()
        log.info("开始清空全部图片数据...")
        await clear_all_pic()
        log.info("图片数据已清空")

    async def download_pic_again(self):
        pic_list = await fail_pic_list()
        if not pic_list:
            return
        log.info("开始重新下载图片...")
        pic_header = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": read_config("ua")
        }
        jar = aiohttp.CookieJar()
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn, cookie_jar=jar) as session:
            for pic in pic_list:
                self.check_cancel_requested()
                # 获取章节
                chapter = await get_chapter(pic.chapter_table_id)
                # 获取书籍
                book = await get_book_by_id(chapter.book_table_id)
                # 下载图片
                save_path = f"{read_config('image_dir')}/{book.source}/{book.book_id}/{chapter.chapter_id}"
                pic_path = await request.download_pic(pic.pic_url, pic_header, save_path, session)
                if pic_path:
                    pic.pic_path = pic_path
                    # 数据库更新图片保存路径
                    await update_pic(pic)
        log.info("重新下载图片结束")

    async def export_epub_again(self):
        books = await get_all_book()
        if not books:
            return
        log.info("开始重新导出epub...")
        for book in books:
            self.check_cancel_requested()
            # 查询对应章节
            chapters = await get_chapter_list(book.id)
            if not chapters:
                book.chapters = []
                continue
            book.chapters = chapters
            for chapter in chapters:
                self.check_cancel_requested()
                chapter.pics = []
                # 查对应图片
                pics = await get_pic_list(chapter.id)
                if not pics:
                    continue
                chapter.pics = pics
            self.check_cancel_requested()
            # epub
            build_epub(book)
            # txt
            if read_config("convert_txt"):
                build_txt(book)
            self.check_cancel_requested()
        log.info("重新导出epub结束")
