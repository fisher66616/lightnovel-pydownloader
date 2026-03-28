from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from src.services.text_catalog import get_text_catalog

TEXTS = get_text_catalog()


class BookshelfPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setSpacing(6)
        self.title_label = QtWidgets.QLabel(TEXTS.get_text("group.bookshelf"))
        self.title_label.setStyleSheet("font-weight: 600;")
        header_row.addWidget(self.title_label)
        self.selection_stats_label = QtWidgets.QLabel(TEXTS.get_text("text.bookshelf_selection_stats", selected=0, visible=0, total=0))
        self.selection_stats_label.setStyleSheet("color: #666;")
        header_row.addWidget(self.selection_stats_label)
        header_row.addStretch()
        self.filter_label = QtWidgets.QLabel(TEXTS.get_text("label.bookshelf_filter"))
        self.category_filter_combo = QtWidgets.QComboBox()
        self.category_filter_combo.setMinimumWidth(150)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(TEXTS.get_text("placeholder.bookshelf_search"))
        self.search_edit.setMinimumWidth(190)
        header_row.addWidget(self.filter_label)
        header_row.addWidget(self.category_filter_combo)
        header_row.addWidget(self.search_edit, 1)
        layout.addLayout(header_row)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(4)
        self.add_button = QtWidgets.QPushButton(TEXTS.get_text("button.add"))
        self.edit_button = QtWidgets.QPushButton(TEXTS.get_text("button.edit"))
        self.quick_edit_category_button = QtWidgets.QPushButton(TEXTS.get_text("button.quick_edit_category"))
        self.bulk_edit_category_button = QtWidgets.QPushButton(TEXTS.get_text("button.bulk_edit_category"))
        self.delete_button = QtWidgets.QPushButton(TEXTS.get_text("button.delete"))
        self.bulk_delete_button = QtWidgets.QPushButton(TEXTS.get_text("button.bulk_delete"))
        self.select_all_button = QtWidgets.QPushButton(TEXTS.get_text("button.select_all"))
        self.clear_selection_button = QtWidgets.QPushButton(TEXTS.get_text("button.clear_selection"))
        self.invert_selection_button = QtWidgets.QPushButton(TEXTS.get_text("button.invert_selection"))
        self.move_up_button = QtWidgets.QPushButton(TEXTS.get_text("button.move_up"))
        self.move_down_button = QtWidgets.QPushButton(TEXTS.get_text("button.move_down"))
        self.fill_task_button = QtWidgets.QPushButton(TEXTS.get_text("button.fill_task"))
        for button in (
            self.add_button,
            self.edit_button,
            self.quick_edit_category_button,
            self.bulk_edit_category_button,
            self.delete_button,
            self.bulk_delete_button,
            self.select_all_button,
            self.clear_selection_button,
            self.invert_selection_button,
            self.move_up_button,
            self.move_down_button,
            self.fill_task_button,
        ):
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed)
            button.setStyleSheet("padding: 2px 6px;")
            button_row.addWidget(button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.empty_hint_label = QtWidgets.QLabel(TEXTS.get_text("text.bookshelf_empty"))
        self.empty_hint_label.setStyleSheet("color: #666;")
        layout.addWidget(self.empty_hint_label)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                TEXTS.get_text("label.bookshelf_name"),
                TEXTS.get_text("label.bookshelf_category"),
                TEXTS.get_text("label.update_strategy"),
                TEXTS.get_text("label.bookshelf_updated_at"),
            ]
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.detail_frame = QtWidgets.QFrame()
        self.detail_frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.detail_frame.setStyleSheet("QFrame { border: 1px solid palette(midlight); border-radius: 6px; }")
        detail_layout = QtWidgets.QGridLayout(self.detail_frame)
        detail_layout.setContentsMargins(8, 6, 8, 6)
        detail_layout.setHorizontalSpacing(8)
        detail_layout.setVerticalSpacing(4)

        self.selection_summary_value = QtWidgets.QLabel("-")
        self.selection_summary_value.setStyleSheet("font-weight: 600;")
        self.selection_summary_value.hide()

        url_title = QtWidgets.QLabel(TEXTS.get_text("label.bookshelf_url"))
        category_title = QtWidgets.QLabel(TEXTS.get_text("label.bookshelf_category"))
        note_title = QtWidgets.QLabel(TEXTS.get_text("label.bookshelf_note"))
        created_title = QtWidgets.QLabel(TEXTS.get_text("label.bookshelf_created_at"))
        updated_title = QtWidgets.QLabel(TEXTS.get_text("label.bookshelf_updated_at"))
        for label in (url_title, category_title, note_title, created_title, updated_title):
            label.setStyleSheet("color: #666;")

        self.url_value = QtWidgets.QLabel("-")
        self.url_value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.category_value = QtWidgets.QLabel("-")
        self.note_value = QtWidgets.QLabel("-")
        self.note_value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.created_value = QtWidgets.QLabel("-")
        self.updated_value = QtWidgets.QLabel("-")

        detail_layout.addWidget(self.selection_summary_value, 0, 0, 1, 6)
        detail_layout.addWidget(url_title, 1, 0)
        detail_layout.addWidget(self.url_value, 1, 1)
        detail_layout.addWidget(category_title, 1, 2)
        detail_layout.addWidget(self.category_value, 1, 3)
        detail_layout.addWidget(note_title, 2, 0)
        detail_layout.addWidget(self.note_value, 2, 1)
        detail_layout.addWidget(created_title, 2, 2)
        detail_layout.addWidget(self.created_value, 2, 3)
        detail_layout.addWidget(updated_title, 2, 4)
        detail_layout.addWidget(self.updated_value, 2, 5)
        detail_layout.setColumnStretch(1, 1)
        detail_layout.setColumnStretch(3, 0)
        detail_layout.setColumnStretch(5, 0)

        layout.addWidget(self.detail_frame)
