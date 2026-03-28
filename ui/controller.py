from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from src.bookshelf import BookshelfService
from src.bookshelf.models import BookshelfBook
from src.services.config_service import ConfigService
from src.services.models import (
    LoginMode,
    TaskForm,
    TaskMode,
    TaskState,
    TaskStatus,
    UpdateStrategy,
)
from src.services.task_service import TaskService
from src.services.text_catalog import get_text_catalog
from ui.book_editor_dialog import BookEditorDialog
from ui.main_window import MainWindow


class MainController(QtCore.QObject):
    log_signal = QtCore.Signal(str)
    state_signal = QtCore.Signal(object)
    finished_signal = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()
        self.config_service = ConfigService()
        self.task_service = TaskService(self.config_service)
        self.bookshelf_service = BookshelfService()
        self.texts = get_text_catalog()
        self.window = MainWindow()
        self._selected_bookshelf_ids: list[int] = []
        self._bookshelf_filter_key = "__all__"
        self._bookshelf_total_count = 0
        self._bookshelf_visible_count = 0

        self.log_signal.connect(self.window.log_text.appendPlainText)
        self.state_signal.connect(self._apply_status)
        self.finished_signal.connect(self._task_finished)

        self.window.site_combo.currentTextChanged.connect(self._handle_site_changed)
        self.window.task_mode_combo.currentIndexChanged.connect(self._refresh_task_mode_ui)
        self.window.login_mode_combo.currentIndexChanged.connect(self._refresh_login_ui)
        self.window.purchase_checkbox.toggled.connect(self._refresh_login_ui)
        self.window.remember_account_checkbox.toggled.connect(self._handle_remember_account_toggled)
        self.window.remember_password_checkbox.toggled.connect(self._handle_remember_password_toggled)
        self.window.start_button.clicked.connect(self._start_task)
        self.window.open_output_button.clicked.connect(self._open_output_dir)
        self.window.open_log_button.clicked.connect(self._open_log_dir)
        self.window.output_root_button.clicked.connect(self._choose_output_dir)
        self.window.chrome_path_button.clicked.connect(self._choose_chrome_path)
        self.window.bookshelf_panel.table.itemSelectionChanged.connect(self._sync_bookshelf_detail)
        self.window.bookshelf_panel.table.itemDoubleClicked.connect(self._edit_bookshelf_book_from_item)
        self.window.bookshelf_panel.category_filter_combo.currentIndexChanged.connect(self._handle_bookshelf_filter_changed)
        self.window.bookshelf_panel.search_edit.textChanged.connect(self._handle_bookshelf_search_changed)
        self.window.bookshelf_panel.add_button.clicked.connect(self._add_bookshelf_book)
        self.window.bookshelf_panel.edit_button.clicked.connect(self._edit_bookshelf_book)
        self.window.bookshelf_panel.quick_edit_category_button.clicked.connect(self._quick_edit_bookshelf_category)
        self.window.bookshelf_panel.bulk_edit_category_button.clicked.connect(self._bulk_edit_bookshelf_category)
        self.window.bookshelf_panel.delete_button.clicked.connect(self._delete_bookshelf_book)
        self.window.bookshelf_panel.bulk_delete_button.clicked.connect(self._bulk_delete_bookshelf)
        self.window.bookshelf_panel.select_all_button.clicked.connect(self._select_all_visible_bookshelf)
        self.window.bookshelf_panel.clear_selection_button.clicked.connect(self._clear_bookshelf_selection)
        self.window.bookshelf_panel.invert_selection_button.clicked.connect(self._invert_bookshelf_selection)
        self.window.bookshelf_panel.move_up_button.clicked.connect(self._move_bookshelf_book_up)
        self.window.bookshelf_panel.move_down_button.clicked.connect(self._move_bookshelf_book_down)
        self.window.bookshelf_panel.fill_task_button.clicked.connect(self._fill_task_from_bookshelf)

        self._bookshelf_search_text = ""
        self._load_initial_form()
        self._refresh_task_mode_ui()
        self._refresh_login_ui()
        self._refresh_bookshelf()

    def show(self):
        self.window.show()

    def _load_initial_form(self):
        form = self.config_service.load_form()
        self.window.site_combo.setCurrentText(form.site)
        self.window.task_name_edit.setText(form.task_name)
        self._set_task_mode(form.task_mode)
        self._set_update_strategy(form.update_strategy)
        self.window.single_url_edit.setText(form.single_url)
        self.window.start_page_spin.setValue(form.start_page)
        self.window.end_page_spin.setValue(form.end_page)
        self.window.chrome_path_edit.setText(form.chrome_path)
        self.window.output_root_edit.setText(form.output_root)
        self.window.purchase_checkbox.setChecked(form.is_purchase)
        self.window.max_purchase_spin.setValue(form.max_purchase)
        self.window.convert_hans_checkbox.setChecked(form.convert_hans)
        self.window.proxy_edit.setText(form.proxy_url)
        self.window.convert_txt_checkbox.setChecked(form.convert_txt)
        self.window.site_value.setText(form.site)
        self._apply_login_bundle(
            form.site,
            form.login_mode,
            form.username,
            form.password,
            form.cookie,
            form.remember_account,
            form.remember_password,
        )

    def _set_task_mode(self, task_mode: TaskMode):
        index = self.window.task_mode_combo.findData(task_mode.value)
        if index >= 0:
            self.window.task_mode_combo.setCurrentIndex(index)

    def _set_login_mode(self, login_mode: LoginMode):
        index = self.window.login_mode_combo.findData(login_mode.value)
        if index >= 0:
            self.window.login_mode_combo.setCurrentIndex(index)

    def _set_update_strategy(self, update_strategy: UpdateStrategy):
        index = self.window.update_strategy_combo.findData(update_strategy.value)
        if index >= 0:
            self.window.update_strategy_combo.setCurrentIndex(index)

    def _current_task_mode(self) -> TaskMode:
        return TaskMode(self.window.task_mode_combo.currentData())

    def _current_login_mode(self) -> LoginMode:
        return LoginMode(self.window.login_mode_combo.currentData())

    def _current_update_strategy(self) -> UpdateStrategy:
        return UpdateStrategy(self.window.update_strategy_combo.currentData())

    def _current_site(self) -> str:
        return self.window.site_combo.currentText()

    def _refresh_task_mode_ui(self):
        is_single_link = self._current_task_mode() == TaskMode.SINGLE_LINK
        self.window.single_url_edit.setVisible(is_single_link)
        self.window.page_range_widget.setVisible(not is_single_link)
        single_link_label = self.window.task_form_layout.labelForField(self.window.single_url_edit)
        page_range_label = self.window.task_form_layout.labelForField(self.window.page_range_widget)
        if single_link_label:
            single_link_label.setVisible(is_single_link)
        if page_range_label:
            page_range_label.setVisible(not is_single_link)
        self.window.update_strategy_combo.setEnabled(is_single_link)

    def _refresh_login_ui(self):
        site = self._current_site()
        login_mode = self._current_login_mode()
        password_storage_available = self.config_service.is_password_storage_available()

        if site == "lk":
            self.window.login_mode_combo.hide()
            self.window.login_stack.setCurrentWidget(self.window.account_form)
            self.window.login_hint_label.hide()
        elif site == "yuri":
            self.window.login_mode_combo.hide()
            self.window.login_stack.setCurrentWidget(self.window.cookie_form)
            self.window.login_hint_label.hide()
        else:
            self.window.login_mode_combo.show()
            if login_mode == LoginMode.COOKIE:
                self.window.login_stack.setCurrentWidget(self.window.cookie_form)
            else:
                self.window.login_stack.setCurrentWidget(self.window.account_form)
            if site == "masiro" and login_mode == LoginMode.ACCOUNT_PASSWORD:
                self.window.login_hint_label.setText(self.texts.get_text("text.login_hint_masiro_account"))
                self.window.login_hint_label.show()
            else:
                self.window.login_hint_label.hide()

        purchase_supported = site in ("lk", "masiro")
        self.window.purchase_checkbox.setEnabled(purchase_supported)
        self.window.max_purchase_spin.setEnabled(purchase_supported and self.window.purchase_checkbox.isChecked())
        self.window.chrome_path_edit.setEnabled(site == "masiro")
        self.window.chrome_path_button.setEnabled(site == "masiro")
        account_site = site in ("esj", "masiro", "lk")
        account_mode_active = account_site and (site == "lk" or login_mode == LoginMode.ACCOUNT_PASSWORD)
        self.window.remember_account_checkbox.setVisible(account_mode_active)
        self.window.remember_password_checkbox.setVisible(account_mode_active)
        self.window.remember_password_checkbox.setEnabled(account_mode_active and password_storage_available)
        self.window.keychain_status_label.setVisible(account_mode_active and not password_storage_available)
        self.window.site_value.setText(site)
        self._refresh_bookshelf()

    def _collect_form(self) -> TaskForm:
        site = self._current_site()
        login_mode = self._current_login_mode() if site in ("esj", "masiro") else (
            LoginMode.ACCOUNT_PASSWORD if site == "lk" else LoginMode.COOKIE
        )
        return TaskForm(
            site=site,
            task_name=self.window.task_name_edit.text().strip(),
            task_mode=self._current_task_mode(),
            single_url=self.window.single_url_edit.text().strip(),
            start_page=self.window.start_page_spin.value(),
            end_page=self.window.end_page_spin.value(),
            update_strategy=self._current_update_strategy(),
            login_mode=login_mode,
            remember_account=self.window.remember_account_checkbox.isChecked(),
            remember_password=self.window.remember_password_checkbox.isChecked(),
            username=self.window.username_edit.text().strip(),
            password=self.window.password_edit.text(),
            cookie=self.window.cookie_edit.toPlainText().strip(),
            chrome_path=self.window.chrome_path_edit.text().strip(),
            output_root=self.window.output_root_edit.text().strip(),
            is_purchase=self.window.purchase_checkbox.isChecked(),
            max_purchase=self.window.max_purchase_spin.value(),
            convert_hans=self.window.convert_hans_checkbox.isChecked(),
            proxy_url=self.window.proxy_edit.text().strip(),
            convert_txt=self.window.convert_txt_checkbox.isChecked(),
        )

    def _start_task(self):
        form = self._collect_form()
        self.window.log_text.clear()
        self.window.book_value.setText("-")
        self.window.chapter_value.setText("-")
        self.window.site_value.setText(form.site)
        try:
            self.task_service.start_task(
                form,
                on_log=self.log_signal.emit,
                on_state=self.state_signal.emit,
                on_finished=self.finished_signal.emit,
            )
            self.window.start_button.setEnabled(False)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(
                self.window,
                self.texts.get_text("dialog.incomplete_info_title"),
                self._friendly_validation_message(str(exc), form),
            )
        except RuntimeError as exc:
            QtWidgets.QMessageBox.information(
                self.window,
                self.texts.get_text("dialog.task_running_title"),
                self.texts.get_text("dialog.task_running_body", message=str(exc)),
            )

    def _apply_status(self, status: TaskStatus):
        if not isinstance(status, TaskStatus):
            return
        text_map = {
            TaskState.IDLE: self.texts.get_text("status.idle"),
            TaskState.RUNNING: self.texts.get_text("status.running"),
            TaskState.SUCCESS: self.texts.get_text("status.success"),
            TaskState.FAILED: self.texts.get_text("status.failed"),
        }
        self.window.status_value.setText(text_map.get(status.state, status.message))
        self.window.site_value.setText(status.site or "-")
        self.window.book_value.setText(status.book or "-")
        self.window.chapter_value.setText(status.chapter or "-")

    def _task_finished(self, success: bool):
        self.window.start_button.setEnabled(True)
        if not success:
            self.window.status_value.setText(self.texts.get_text("status.failed"))
            QtWidgets.QMessageBox.warning(
                self.window,
                self.texts.get_text("dialog.task_failed_title"),
                self._friendly_runtime_message(self.task_service.get_status().message),
            )

    def _open_output_dir(self):
        self._open_local_path(self.config_service.get_output_dir())

    def _open_log_dir(self):
        self._open_local_path(self.config_service.get_log_dir())

    def _open_local_path(self, path: str):
        Path(path).mkdir(parents=True, exist_ok=True)
        url = QtCore.QUrl.fromLocalFile(path)
        if not QtGui.QDesktopServices.openUrl(url):
            QtWidgets.QMessageBox.warning(
                self.window,
                self.texts.get_text("dialog.open_failed_title"),
                self.texts.get_text("dialog.open_failed_body", path=path),
            )

    def _choose_output_dir(self):
        current_path = self.window.output_root_edit.text().strip()
        selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            self.texts.get_text("dialog.choose_output_dir_title"),
            current_path or str(Path.home() / "Documents"),
        )
        if selected_dir:
            self.window.output_root_edit.setText(selected_dir)

    def _choose_chrome_path(self):
        current_path = self.window.chrome_path_edit.text().strip()
        selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            self.texts.get_text("dialog.choose_chrome_path_title"),
            str(Path(current_path).parent) if current_path else "/Applications",
        )
        if selected_path:
            self.window.chrome_path_edit.setText(selected_path)

    def _friendly_validation_message(self, raw_message: str, form: TaskForm) -> str:
        lines = [self.texts.get_text(line) for line in raw_message.splitlines() if line.strip()]
        if form.site == "masiro" and form.login_mode == LoginMode.ACCOUNT_PASSWORD:
            lines.append(self.texts.get_text("text.login_hint_masiro_account"))
        return "\n\n".join(lines)

    def _friendly_runtime_message(self, raw_message: str) -> str:
        if "未配置登录信息" in raw_message:
            return self.texts.get_text("dialog.task_failed_no_login")
        if "cookie失效" in raw_message:
            return self.texts.get_text("dialog.task_failed_cookie_invalid")
        if "Chrome" in raw_message or "chrome" in raw_message:
            return self.texts.get_text("dialog.task_failed_chrome_missing")
        if "登录失败" in raw_message:
            return self.texts.get_text("dialog.task_failed_login")
        return self.texts.get_text("dialog.task_failed_generic")

    def _refresh_bookshelf(self, selected_book_ids: Optional[list[int]] = None):
        site = self._current_site()
        panel = self.window.bookshelf_panel
        books = self.bookshelf_service.list_books(site)
        self._refresh_category_filter(site, books)
        visible_books = self._filter_books(books)
        self._bookshelf_total_count = len(books)
        self._bookshelf_visible_count = len(visible_books)
        panel.title_label.setText(self.texts.get_text("text.bookshelf_title_site", site=site))
        panel.empty_hint_label.setVisible(not visible_books)
        if visible_books:
            panel.empty_hint_label.clear()
        elif books:
            panel.empty_hint_label.setText(self.texts.get_text("text.bookshelf_empty_filtered"))
        else:
            panel.empty_hint_label.setText(self.texts.get_text("text.bookshelf_empty_actionable"))
        table = panel.table
        table.blockSignals(True)
        table.setRowCount(len(visible_books))
        for row, book in enumerate(visible_books):
            self._set_table_item(row, 0, book.custom_name, book.id)
            self._set_table_item(row, 1, book.category or "-", book.id)
            self._set_table_item(row, 2, self._strategy_label(book.update_strategy), book.id)
            self._set_table_item(row, 3, self._format_timestamp(book.updated_at), book.id)
        target_book_ids = selected_book_ids if selected_book_ids is not None else self._selected_bookshelf_ids
        restored_ids = self._restore_bookshelf_selection(target_book_ids)
        table.blockSignals(False)
        self._selected_bookshelf_ids = restored_ids
        self._sync_bookshelf_detail()

    def _set_table_item(self, row: int, column: int, text: str, book_id: int):
        item = QtWidgets.QTableWidgetItem(text)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, book_id)
        self.window.bookshelf_panel.table.setItem(row, column, item)

    def _selected_bookshelf_ids_in_view(self) -> list[int]:
        table = self.window.bookshelf_panel.table
        selection_model = table.selectionModel()
        if selection_model is None:
            self._selected_bookshelf_ids = []
            return []
        selected_indexes = sorted(selection_model.selectedRows(0), key=lambda index: index.row())
        selected_ids: list[int] = []
        seen: set[int] = set()
        for index in selected_indexes:
            item = table.item(index.row(), 0)
            if item is None:
                continue
            book_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not book_id:
                continue
            normalized_id = int(book_id)
            if normalized_id in seen:
                continue
            seen.add(normalized_id)
            selected_ids.append(normalized_id)
        self._selected_bookshelf_ids = selected_ids
        return selected_ids

    def _selected_bookshelf_book(self) -> Optional[BookshelfBook]:
        selected_ids = self._selected_bookshelf_ids_in_view()
        if len(selected_ids) != 1:
            return None
        return self.bookshelf_service.get_book(selected_ids[0])

    def _visible_bookshelf_ids(self) -> list[int]:
        table = self.window.bookshelf_panel.table
        visible_ids: list[int] = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            book_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not book_id:
                continue
            visible_ids.append(int(book_id))
        return visible_ids

    def _apply_bookshelf_selection(self, book_ids: list[int]):
        table = self.window.bookshelf_panel.table
        table.blockSignals(True)
        restored_ids = self._restore_bookshelf_selection(book_ids)
        table.blockSignals(False)
        self._selected_bookshelf_ids = restored_ids
        self._sync_bookshelf_detail()

    def _update_bookshelf_selection_stats(self, selected_count: int):
        self.window.bookshelf_panel.selection_stats_label.setText(
            self.texts.get_text(
                "text.bookshelf_selection_stats",
                selected=selected_count,
                visible=self._bookshelf_visible_count,
                total=self._bookshelf_total_count,
            )
        )

    def _sync_bookshelf_detail(self):
        panel = self.window.bookshelf_panel
        selected_ids = self._selected_bookshelf_ids_in_view()
        selected_count = len(selected_ids)
        single_selected = selected_count == 1
        multi_selected = selected_count > 1
        has_visible_rows = self._bookshelf_visible_count > 0
        panel.edit_button.setEnabled(single_selected)
        panel.quick_edit_category_button.setEnabled(single_selected)
        panel.delete_button.setEnabled(single_selected)
        panel.move_up_button.setEnabled(single_selected)
        panel.move_down_button.setEnabled(single_selected)
        panel.fill_task_button.setEnabled(single_selected)
        panel.bulk_edit_category_button.setEnabled(multi_selected)
        panel.bulk_delete_button.setEnabled(multi_selected)
        panel.select_all_button.setEnabled(has_visible_rows)
        panel.invert_selection_button.setEnabled(has_visible_rows)
        panel.clear_selection_button.setEnabled(selected_count > 0)
        self._update_bookshelf_selection_stats(selected_count)
        if not single_selected:
            if multi_selected:
                panel.selection_summary_value.setText(
                    self.texts.get_text("text.bookshelf_multi_selected", count=selected_count)
                )
                panel.selection_summary_value.show()
            else:
                panel.selection_summary_value.hide()
            self._set_detail_text(panel.url_value, "-")
            self._set_detail_text(panel.category_value, "-")
            self._set_detail_text(panel.note_value, "-")
            self._set_detail_text(panel.created_value, "-")
            self._set_detail_text(panel.updated_value, "-")
            return
        panel.selection_summary_value.hide()
        book = self.bookshelf_service.get_book(selected_ids[0])
        if book is None:
            self._set_detail_text(panel.url_value, "-")
            self._set_detail_text(panel.category_value, "-")
            self._set_detail_text(panel.note_value, "-")
            self._set_detail_text(panel.created_value, "-")
            self._set_detail_text(panel.updated_value, "-")
            return
        self._set_detail_text(panel.url_value, book.url or "-", 76)
        self._set_detail_text(panel.category_value, book.category or "-", 18)
        self._set_detail_text(panel.note_value, book.note or "-", 40)
        self._set_detail_text(panel.created_value, self._format_timestamp(book.created_at))
        self._set_detail_text(panel.updated_value, self._format_timestamp(book.updated_at))

    def _refresh_category_filter(self, site: str, books: list[BookshelfBook]):
        counts: dict[str, int] = {}
        ordered_categories: list[str] = []
        uncategorized_count = 0
        for book in books:
            category = (book.category or "").strip()
            if category:
                if category not in counts:
                    ordered_categories.append(category)
                counts[category] = counts.get(category, 0) + 1
            else:
                uncategorized_count += 1

        items = [
            (
                self.texts.get_text("filter.all_with_count", count=len(books)),
                "__all__",
            )
        ]
        if uncategorized_count:
            items.append(
                (
                    self.texts.get_text("filter.uncategorized_with_count", count=uncategorized_count),
                    "__uncategorized__",
                )
            )
        for category in ordered_categories:
            items.append(
                (
                    self.texts.get_text("filter.category_with_count", name=category, count=counts[category]),
                    category,
                )
            )

        combo = self.window.bookshelf_panel.category_filter_combo
        current_key = self._bookshelf_filter_key
        valid_keys = {item[1] for item in items}
        if current_key not in valid_keys:
            current_key = "__all__"
            self._bookshelf_filter_key = current_key

        combo.blockSignals(True)
        combo.clear()
        for text, value in items:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(combo.findData(current_key), 0))
        combo.blockSignals(False)

    def _filter_books(self, books: list[BookshelfBook]) -> list[BookshelfBook]:
        if self._bookshelf_filter_key == "__all__":
            filtered_books = books
        elif self._bookshelf_filter_key == "__uncategorized__":
            filtered_books = [book for book in books if not (book.category or "").strip()]
        else:
            filtered_books = [book for book in books if (book.category or "").strip() == self._bookshelf_filter_key]
        keyword = self._bookshelf_search_text.casefold()
        if not keyword:
            return filtered_books
        return [book for book in filtered_books if keyword in book.custom_name.casefold()]

    def _handle_bookshelf_filter_changed(self):
        self._bookshelf_filter_key = str(self.window.bookshelf_panel.category_filter_combo.currentData() or "__all__")
        self._refresh_bookshelf(selected_book_ids=self._selected_bookshelf_ids)

    def _handle_bookshelf_search_changed(self, text: str):
        self._bookshelf_search_text = text.strip()
        self._refresh_bookshelf(selected_book_ids=self._selected_bookshelf_ids)

    def _add_bookshelf_book(self):
        site = self._current_site()
        dialog = BookEditorDialog(
            site=site,
            categories=self.bookshelf_service.list_categories(site),
            parent=self.window,
            book=BookshelfBook(
                site=site,
                custom_name=self.window.task_name_edit.text().strip(),
                url=self.window.single_url_edit.text().strip(),
                update_strategy=self._current_update_strategy().value,
                category="",
                note="",
            ),
        )
        dialog.setWindowTitle(self.texts.get_text("button.add"))
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        try:
            created = self.bookshelf_service.create_book(dialog.build_book())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self.window, self.texts.get_text("dialog.save_to_bookshelf_failed_title"), self.texts.get_text(str(exc), default=str(exc)))
            return
        self._refresh_bookshelf(selected_book_ids=[created.id])

    def _edit_bookshelf_book(self):
        book = self._selected_bookshelf_book()
        if book is None:
            return
        self._edit_bookshelf_book_by_id(book.id)

    def _edit_bookshelf_book_from_item(self, item: QtWidgets.QTableWidgetItem):
        book_id = self._book_id_from_table_item(item)
        if book_id is None:
            return
        self._edit_bookshelf_book_by_id(book_id)

    def _edit_bookshelf_book_by_id(self, book_id: Optional[int]):
        if book_id is None:
            return
        book = self.bookshelf_service.get_book(book_id)
        if book is None:
            return
        dialog = BookEditorDialog(
            site=book.site,
            categories=self.bookshelf_service.list_categories(book.site),
            parent=self.window,
            book=book,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        try:
            updated = self.bookshelf_service.update_book(dialog.build_book())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self.window, self.texts.get_text("dialog.update_bookshelf_failed_title"), self.texts.get_text(str(exc), default=str(exc)))
            return
        self._refresh_bookshelf(selected_book_ids=[updated.id])

    def _book_id_from_table_item(self, item: Optional[QtWidgets.QTableWidgetItem]) -> Optional[int]:
        if item is None:
            return None
        row_item = self.window.bookshelf_panel.table.item(item.row(), 0) or item
        book_id = row_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not book_id:
            return None
        return int(book_id)

    def _quick_edit_bookshelf_category(self):
        book = self._selected_bookshelf_book()
        if book is None:
            return
        books = self.bookshelf_service.list_books(book.site)
        categories = self._ordered_categories(books)
        current_category = (book.category or "").strip()
        if not current_category:
            categories = ["", *categories]
        if current_category and current_category not in categories:
            categories = [current_category, *categories]
        value, accepted = QtWidgets.QInputDialog.getItem(
            self.window,
            self.texts.get_text("dialog.quick_category_title"),
            self.texts.get_text("dialog.quick_category_label"),
            categories,
            max(categories.index(current_category), 0) if current_category in categories else 0,
            True,
        )
        if not accepted:
            return
        updated_book = self.bookshelf_service.get_book(book.id)
        if updated_book is None:
            return
        updated_book.category = value.strip()
        try:
            updated = self.bookshelf_service.update_book(updated_book)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(
                self.window,
                self.texts.get_text("dialog.update_bookshelf_failed_title"),
                self.texts.get_text(str(exc), default=str(exc)),
            )
            return
        self._refresh_bookshelf(selected_book_ids=[updated.id])

    def _bulk_edit_bookshelf_category(self):
        selected_ids = self._selected_bookshelf_ids_in_view()
        if len(selected_ids) < 2:
            return
        site = self._current_site()
        books = self.bookshelf_service.list_books(site)
        categories = self._ordered_categories(books)
        value, accepted = QtWidgets.QInputDialog.getItem(
            self.window,
            self.texts.get_text("dialog.bulk_category_title"),
            self.texts.get_text("dialog.bulk_category_label"),
            categories,
            0,
            True,
        )
        if not accepted:
            return
        self.bookshelf_service.update_books_category(site, selected_ids, value.strip())
        self._refresh_bookshelf(selected_book_ids=selected_ids)

    def _delete_bookshelf_book(self):
        book = self._selected_bookshelf_book()
        if book is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self.window,
            self.texts.get_text("dialog.delete_bookshelf_title"),
            self.texts.get_text("dialog.delete_bookshelf_body", name=book.custom_name),
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.bookshelf_service.delete_book(book.id)
        self._refresh_bookshelf(selected_book_ids=[])

    def _bulk_delete_bookshelf(self):
        selected_ids = self._selected_bookshelf_ids_in_view()
        if len(selected_ids) < 2:
            return
        books: list[BookshelfBook] = []
        for book_id in selected_ids:
            book = self.bookshelf_service.get_book(book_id)
            if book is not None:
                books.append(book)
        if not books:
            self._refresh_bookshelf(selected_book_ids=[])
            return
        preview_names = [f"• {book.custom_name}" for book in books[:5]]
        ellipsis = "\n……" if len(books) > 5 else ""
        reply = QtWidgets.QMessageBox.question(
            self.window,
            self.texts.get_text("dialog.bulk_delete_title"),
            self.texts.get_text(
                "dialog.bulk_delete_body",
                count=len(books),
                names="\n".join(preview_names),
                ellipsis=ellipsis,
            ),
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.bookshelf_service.delete_books(self._current_site(), [book.id for book in books if book.id is not None])
        self._refresh_bookshelf(selected_book_ids=[])

    def _select_all_visible_bookshelf(self):
        self._apply_bookshelf_selection(self._visible_bookshelf_ids())

    def _clear_bookshelf_selection(self):
        self._apply_bookshelf_selection([])

    def _invert_bookshelf_selection(self):
        visible_ids = self._visible_bookshelf_ids()
        selected_ids = set(self._selected_bookshelf_ids_in_view())
        inverted_ids = [book_id for book_id in visible_ids if book_id not in selected_ids]
        self._apply_bookshelf_selection(inverted_ids)

    def _move_bookshelf_book_up(self):
        self._move_bookshelf_book("up")

    def _move_bookshelf_book_down(self):
        self._move_bookshelf_book("down")

    def _move_bookshelf_book(self, direction: str):
        book = self._selected_bookshelf_book()
        if book is None:
            return
        all_books = self.bookshelf_service.list_books(self._current_site())
        visible_books = self._filter_books(all_books)
        visible_ids = [item.id for item in visible_books if item.id is not None]
        if book.id not in visible_ids:
            return
        current_index = visible_ids.index(book.id)
        target_index = current_index - 1 if direction == "up" else current_index + 1
        if target_index < 0 or target_index >= len(visible_ids):
            return
        visible_ids[current_index], visible_ids[target_index] = visible_ids[target_index], visible_ids[current_index]
        visible_id_set = set(visible_ids)
        reordered_visible = iter(visible_ids)
        ordered_ids = [
            next(reordered_visible) if item.id in visible_id_set else item.id
            for item in all_books
            if item.id is not None
        ]
        self.bookshelf_service.reorder_site(self._current_site(), ordered_ids)
        self._refresh_bookshelf(selected_book_ids=[book.id])

    def _fill_task_from_bookshelf(self):
        book = self._selected_bookshelf_book()
        if book is None:
            return
        self.window.task_name_edit.setText(book.custom_name)
        self.window.single_url_edit.setText(book.url)
        self._set_task_mode(TaskMode.SINGLE_LINK)
        self._set_update_strategy(UpdateStrategy(book.update_strategy))
        self._refresh_task_mode_ui()
        QtWidgets.QMessageBox.information(
            self.window,
            self.texts.get_text("dialog.fill_task_title"),
            self.texts.get_text("dialog.fill_task_body"),
        )

    def _restore_bookshelf_selection(self, book_ids: Optional[list[int]]) -> list[int]:
        table = self.window.bookshelf_panel.table
        table.clearSelection()
        table.setCurrentItem(None)
        if not book_ids:
            return []
        ordered_ids: list[int] = []
        seen: set[int] = set()
        for book_id in book_ids:
            normalized_id = int(book_id)
            if normalized_id in seen:
                continue
            seen.add(normalized_id)
            ordered_ids.append(normalized_id)
        wanted_ids = set(ordered_ids)
        selection_model = table.selectionModel()
        if selection_model is None:
            return []
        restored_ids: list[int] = []
        first_item: Optional[QtWidgets.QTableWidgetItem] = None
        first_index: Optional[QtCore.QModelIndex] = None
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            book_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if book_id not in wanted_ids:
                continue
            restored_ids.append(int(book_id))
            model_index = table.model().index(row, 0)
            selection_model.select(
                model_index,
                QtCore.QItemSelectionModel.SelectionFlag.Select
                | QtCore.QItemSelectionModel.SelectionFlag.Rows,
            )
            if first_item is None:
                first_item = item
                first_index = model_index
        if first_item is not None:
            if first_index is not None:
                selection_model.setCurrentIndex(
                    first_index,
                    QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                )
            table.scrollToItem(first_item)
        return restored_ids

    def _strategy_label(self, update_strategy: str) -> str:
        try:
            return self.texts.get_text(f"strategy.{UpdateStrategy(update_strategy).value}")
        except ValueError:
            return update_strategy

    def _set_detail_text(self, label: QtWidgets.QLabel, value: str, limit: int = 0):
        text = value or "-"
        display_text = self._compact_text(text, limit) if limit else text
        label.setText(display_text)
        label.setToolTip("" if text == "-" else text)

    def _compact_text(self, text: str, limit: int) -> str:
        if not limit or len(text) <= limit:
            return text
        return f"{text[: limit - 1]}…"

    def _format_timestamp(self, value: str) -> str:
        if not value:
            return "-"
        text = value.replace("T", " ")
        return text.split(".")[0].replace("+00:00", " UTC")

    def _handle_site_changed(self, site: str):
        self._bookshelf_filter_key = "__all__"
        self._selected_bookshelf_ids = []
        self.window.bookshelf_panel.search_edit.blockSignals(True)
        self.window.bookshelf_panel.search_edit.clear()
        self.window.bookshelf_panel.search_edit.blockSignals(False)
        self._bookshelf_search_text = ""
        self._load_site_credentials(site)
        self._refresh_login_ui()

    def _ordered_categories(self, books: list[BookshelfBook]) -> list[str]:
        categories: list[str] = []
        seen: set[str] = set()
        for book in books:
            category = (book.category or "").strip()
            if not category or category in seen:
                continue
            seen.add(category)
            categories.append(category)
        return categories

    def _load_site_credentials(self, site: str):
        bundle = self.config_service.load_login_bundle(site)
        self._apply_login_bundle(
            site,
            bundle["login_mode"],
            bundle["username"],
            bundle["password"],
            bundle["cookie"],
            bundle["remember_account"],
            bundle["remember_password"],
        )

    def _apply_login_bundle(
        self,
        site: str,
        login_mode: LoginMode,
        username: str,
        password: str,
        cookie: str,
        remember_account: bool,
        remember_password: bool,
    ):
        _ = site
        self._set_login_mode(login_mode)
        self.window.username_edit.setText(username)
        self.window.password_edit.setText(password)
        self.window.cookie_edit.setPlainText(cookie)
        self._set_checkbox(self.window.remember_account_checkbox, remember_account)
        self._set_checkbox(self.window.remember_password_checkbox, remember_password)

    def _set_checkbox(self, checkbox: QtWidgets.QCheckBox, checked: bool):
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    def _handle_remember_account_toggled(self, checked: bool):
        if not checked and self.window.remember_password_checkbox.isChecked():
            self._set_checkbox(self.window.remember_password_checkbox, False)

    def _handle_remember_password_toggled(self, checked: bool):
        if not checked:
            return
        self._set_checkbox(self.window.remember_account_checkbox, True)
        if self.config_service.is_password_storage_available():
            return
        self._set_checkbox(self.window.remember_password_checkbox, False)
        QtWidgets.QMessageBox.information(
            self.window,
            self.texts.get_text("dialog.keychain_unavailable_title"),
            self.texts.get_text("dialog.keychain_unavailable_body"),
        )
