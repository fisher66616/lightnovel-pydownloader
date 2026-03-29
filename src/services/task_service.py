from __future__ import annotations

from datetime import datetime
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Callable, Optional

from src.app.runtime import run_sync
from src.core.cancellation import TaskCancelled
from src.services.config_service import ConfigService
from src.services.models import LoginMode, TaskForm, TaskMode, TaskState, TaskStatus, UpdateStrategy
from src.utils.log import log


class TaskService:
    FIELD_LABELS = {
        "site": "站点",
        "task_name": "任务名称",
        "task_mode": "任务模式",
        "page_range": "页面范围",
        "update_strategy": "单本更新策略",
        "login_mode": "登录方式",
        "output_root": "输出目录",
        "started_at": "开始时间",
        "ended_at": "结束时间",
        "duration": "总耗时",
        "success_exports": "成功导出书籍数",
        "skip_events": "跳过事件数",
        "failure_events": "失败事件数",
        "book": "书籍",
        "chapter": "章节",
        "reason": "原因",
    }

    def __init__(self, config_service: Optional[ConfigService] = None):
        self.config_service = config_service or ConfigService()
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._status = TaskStatus()
        self._stop_event = Event()
        self._on_state: Optional[Callable[[TaskStatus], None]] = None
        self._running_site = ""

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> TaskStatus:
        return self._status

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> bool:
        with self._lock:
            if not self.is_running():
                return False
            if self._stop_event.is_set():
                return True
            self._stop_event.set()
            callback = self._on_state
            site = self._running_site or self._status.site
        log.info(self._structured_message("TASK", "收到结束任务请求", site=site))
        self._update_state(
            TaskState.CANCELLING,
            "正在结束任务...",
            site,
            callback,
        )
        return True

    def start_task(
        self,
        form: TaskForm,
        on_log: Optional[Callable[[str], None]] = None,
        on_state: Optional[Callable[[TaskStatus], None]] = None,
        on_finished: Optional[Callable[[bool], None]] = None,
    ):
        with self._lock:
            if self.is_running():
                raise RuntimeError("当前已有任务正在运行。")

            errors = self.config_service.validate_form(form)
            if errors:
                raise ValueError("\n".join(errors))
            self._stop_event.clear()
            self._on_state = on_state
            self._running_site = form.site

            worker = Thread(
                target=self._run_task,
                args=(form, on_log, on_state, on_finished),
                daemon=True,
            )
            self._thread = worker
            worker.start()

    def _run_task(
        self,
        form: TaskForm,
        on_log: Optional[Callable[[str], None]],
        on_state: Optional[Callable[[TaskStatus], None]],
        on_finished: Optional[Callable[[bool], None]],
    ):
        summary = {
            "success_exports": 0,
            "skip_events": 0,
            "failure_events": 0,
            "started_at": self._now_text(),
            "timer_started": perf_counter(),
        }
        unsubscribe = log.subscribe(
            lambda line: self._handle_log_line(line, on_log, on_state, summary)
        )
        success = False
        cancelled = False
        try:
            runtime_config = self.config_service.save_form(form)
            if self._stop_event.is_set():
                raise TaskCancelled()
            self._update_state(
                TaskState.RUNNING,
                "任务运行中",
                form.site,
                on_state,
                book="-",
                chapter="-",
            )
            log.info(self._structured_message("TASK", "任务开始", site=form.site))
            log.info(
                self._structured_message(
                    "TASK",
                    "任务摘要",
                    site=form.site,
                    task_name=form.task_name or "-",
                    task_mode=self._task_mode_label(form.task_mode),
                    page_range=self._page_range_label(form),
                    update_strategy=self._update_strategy_label(form.update_strategy),
                    login_mode=self._login_mode_label(form),
                    output_root=str(runtime_config.get("output_root") or form.output_root or self.config_service.get_output_dir()),
                    started_at=summary["started_at"],
                )
            )
            success = run_sync(
                config_data=runtime_config,
                enable_scheduler=False,
                cancel_event=self._stop_event,
            )
            if self._stop_event.is_set():
                cancelled = True
                success = False
                self._update_state(TaskState.CANCELLED, "任务已取消", form.site, on_state)
            elif success:
                self._update_state(TaskState.SUCCESS, "任务已完成", form.site, on_state)
            else:
                self._update_state(TaskState.FAILED, "任务失败，请查看日志", form.site, on_state)
        except TaskCancelled:
            cancelled = True
            success = False
            log.info(self._structured_message("TASK", "任务已取消", site=form.site))
            self._update_state(TaskState.CANCELLED, "任务已取消", form.site, on_state)
        except Exception as exc:
            if self._stop_event.is_set():
                cancelled = True
                success = False
                log.info(self._structured_message("TASK", "任务已取消", site=form.site))
                self._update_state(TaskState.CANCELLED, "任务已取消", form.site, on_state)
            else:
                log.error(self._structured_message("ERROR", "任务启动失败", site=form.site, reason=str(exc)))
                self._update_state(TaskState.FAILED, str(exc), form.site, on_state)
        finally:
            ended_at = self._now_text()
            duration = f"{perf_counter() - summary['timer_started']:.1f}秒"
            log.info(
                self._structured_message(
                    "SUMMARY",
                    "任务结束",
                    success_exports=summary["success_exports"],
                    skip_events=summary["skip_events"],
                    failure_events=summary["failure_events"],
                    ended_at=ended_at,
                    duration=duration,
                )
            )
            unsubscribe()
            if on_finished:
                on_finished(success)
            with self._lock:
                self._thread = None
                self._on_state = None
                self._running_site = ""

    def _handle_log_line(
        self,
        formatted_line: str,
        on_log: Optional[Callable[[str], None]],
        on_state: Optional[Callable[[TaskStatus], None]],
        summary: dict,
    ):
        if on_log:
            on_log(formatted_line)
        payload = formatted_line.split(" - ", 1)[1] if " - " in formatted_line else formatted_line
        parsed = self._parse_structured_message(payload)
        if not parsed:
            return
        prefix, _, fields = parsed
        site = fields.get("站点") or self._status.site
        book = fields.get("书籍") or self._status.book
        chapter = fields.get("章节") or self._status.chapter

        if prefix == "EXPORT":
            summary["success_exports"] += 1
        elif prefix == "SKIP":
            summary["skip_events"] += 1
        elif prefix == "ERROR":
            summary["failure_events"] += 1

        if prefix in {"TASK", "BOOK", "CHAPTER", "SKIP", "EXPORT", "ERROR"}:
            self._status = TaskStatus(
                state=self._status.state,
                message=self._status.message,
                site=site,
                book=book,
                chapter=chapter,
            )
            if on_state:
                on_state(self._status)

    def _update_state(
        self,
        state: TaskState,
        message: str,
        site: str,
        callback: Optional[Callable[[TaskStatus], None]],
        *,
        book: Optional[str] = None,
        chapter: Optional[str] = None,
    ):
        self._status = TaskStatus(
            state=state,
            message=message,
            site=site,
            book=self._status.book if book is None else book,
            chapter=self._status.chapter if chapter is None else chapter,
        )
        if callback:
            callback(self._status)

    def _structured_message(self, prefix: str, message: str, **fields) -> str:
        parts = [f"[{prefix}] {message}"]
        for key, value in fields.items():
            if value is None or value == "":
                continue
            parts.append(f"{self.FIELD_LABELS.get(key, key)}={value}")
        return " | ".join(parts)

    def _parse_structured_message(self, payload: str):
        if not payload.startswith("[") or "]" not in payload:
            return None
        prefix, rest = payload[1:].split("]", 1)
        prefix = prefix.strip().upper()
        segments = [segment.strip() for segment in rest.strip().split("|") if segment.strip()]
        if not segments:
            return None
        message = segments[0]
        fields = {}
        for segment in segments[1:]:
            if "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            fields[key.strip()] = value.strip()
        return prefix, message, fields

    def _task_mode_label(self, mode: TaskMode) -> str:
        labels = {
            TaskMode.SINGLE_LINK: "单本链接",
            TaskMode.COLLECTION_PAGE: "收藏页抓取",
            TaskMode.PAGE_RANGE: "页码范围抓取",
        }
        return labels.get(mode, mode.value)

    def _update_strategy_label(self, strategy: UpdateStrategy) -> str:
        labels = {
            UpdateStrategy.ONLY_NEW: "只提取新章节",
            UpdateStrategy.REFRESH_CHANGED: "更新变化章节",
            UpdateStrategy.FULL_REFETCH: "整本重新提取",
        }
        return labels.get(strategy, strategy.value)

    def _login_mode_label(self, form: TaskForm) -> str:
        if form.site == "lk":
            return "账号密码"
        if form.site == "yuri":
            return "Cookie"
        return "账号密码" if form.login_mode == LoginMode.ACCOUNT_PASSWORD else "Cookie"

    def _page_range_label(self, form: TaskForm) -> str:
        if form.task_mode == TaskMode.SINGLE_LINK:
            return "-"
        return f"{form.start_page}-{form.end_page}"

    def _now_text(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
