from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.config.models import SCRAPING_TYPE_SITE_FIELDS, FieldPriorityConfig, str_to_list
from mdcx.crawlers import get_registered_crawler_site_values
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig

from .style import build_scrollbar_style, get_theme_tokens

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


@dataclass
class TypeWebsiteUi:
    scraping_type: FixedScrapingType
    title: str
    line_edit: QLineEdit
    row: int
    edit_button: QPushButton | None = None
    priority_button: QPushButton | None = None


TYPE_TITLES = {
    FixedScrapingType.YOUMA: "有码",
    FixedScrapingType.WUMA: "无码",
    FixedScrapingType.SUREN: "素人",
    FixedScrapingType.FC2: "FC2",
    FixedScrapingType.OUMEI: "欧美",
    FixedScrapingType.GUOCHAN: "国产",
}


FIELD_TITLES = {
    CrawlerResultFields.TITLE: "标题",
    CrawlerResultFields.ORIGINALTITLE: "原标题",
    CrawlerResultFields.OUTLINE: "简介",
    CrawlerResultFields.ORIGINALPLOT: "原简介",
    CrawlerResultFields.ACTORS: "演员",
    CrawlerResultFields.ALL_ACTORS: "全部演员",
    CrawlerResultFields.THUMB: "缩略图",
    CrawlerResultFields.POSTER: "海报",
    CrawlerResultFields.EXTRAFANART: "剧照",
    CrawlerResultFields.TAGS: "标签",
    CrawlerResultFields.RELEASE: "发行日期",
    CrawlerResultFields.RUNTIME: "时长",
    CrawlerResultFields.SCORE: "评分",
    CrawlerResultFields.DIRECTORS: "导演",
    CrawlerResultFields.SERIES: "系列",
    CrawlerResultFields.STUDIO: "片商",
    CrawlerResultFields.PUBLISHER: "发行商",
    CrawlerResultFields.TRAILER: "预告片",
    CrawlerResultFields.WANTED: "想看",
}

FIELD_PRIORITY_FIELDS = (
    CrawlerResultFields.TITLE,
    CrawlerResultFields.ORIGINALTITLE,
    CrawlerResultFields.OUTLINE,
    CrawlerResultFields.ORIGINALPLOT,
    CrawlerResultFields.ACTORS,
    CrawlerResultFields.ALL_ACTORS,
    CrawlerResultFields.THUMB,
    CrawlerResultFields.POSTER,
    CrawlerResultFields.EXTRAFANART,
    CrawlerResultFields.TRAILER,
    CrawlerResultFields.TAGS,
    CrawlerResultFields.RELEASE,
    CrawlerResultFields.RUNTIME,
    CrawlerResultFields.SCORE,
    CrawlerResultFields.DIRECTORS,
    CrawlerResultFields.SERIES,
    CrawlerResultFields.STUDIO,
    CrawlerResultFields.PUBLISHER,
    CrawlerResultFields.WANTED,
)


def _sync_field_sites_after_type_sites_changed(
    current_sites: list[Website],
    previous_type_sites: list[Website],
    new_type_sites: list[Website],
) -> list[Website]:
    if not current_sites:
        return []
    new_type_set = set(new_type_sites)
    kept_sites = [site for site in current_sites if site in new_type_set]
    previous_type_set = set(previous_type_sites)
    added_sites = [site for site in new_type_sites if site not in previous_type_set and site not in kept_sites]
    return kept_sites + added_sites


def _parse_sites(text: str) -> list[Website]:
    return list(dict.fromkeys(Website(site) for site in str_to_list(text, ",") if site in Website))


def _sites_text(sites: list[Website]) -> str:
    return ",".join(site.value for site in sites)


def _site_priority_colors(dark: bool) -> dict[str, str]:
    tokens = get_theme_tokens(dark)
    if dark:
        return {
            "window": tokens["window"],
            "surface": "#18222D",
            "surface_muted": "#202B37",
            "surface_hover": "#263442",
            "surface_pressed": "#303D4B",
            "text": tokens["text"],
            "text_muted": tokens["text_muted"],
            "border": tokens["border"],
            "border_active": "#657384",
        }
    return {
        "window": tokens["window"],
        "surface": "#FFFFFF",
        "surface_muted": "#F8FAFC",
        "surface_hover": "#F3F4F6",
        "surface_pressed": "#E5E7EB",
        "text": tokens["text"],
        "text_muted": tokens["text_muted"],
        "border": tokens["border"],
        "border_active": "#9CA3AF",
    }


def _list_sites(list_widget: QListWidget) -> list[Website]:
    return [
        Website(item.data(Qt.ItemDataRole.UserRole))
        for row in range(list_widget.count())
        if (item := list_widget.item(row)) is not None and item.data(Qt.ItemDataRole.UserRole) in Website
    ]


def _selected_sites(list_widget: QListWidget) -> list[Website]:
    items = list_widget.selectedItems()
    if not items and list_widget.currentItem():
        items = [list_widget.currentItem()]
    return [
        Website(item.data(Qt.ItemDataRole.UserRole)) for item in items if item.data(Qt.ItemDataRole.UserRole) in Website
    ]


def _make_site_item(site: Website) -> QListWidgetItem:
    item = QListWidgetItem(site.value)
    item.setData(Qt.ItemDataRole.UserRole, site.value)
    item.setToolTip(site.value)
    item.setFlags(
        item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    )
    return item


def _setup_site_list(list_widget: QListWidget, sites: list[Website]) -> None:
    list_widget.clear()
    for site in sites:
        list_widget.addItem(_make_site_item(site))


def _set_site_summary(line_edit: QLineEdit) -> None:
    sites = _parse_sites(line_edit.text())
    line_edit.setText(_sites_text(sites))
    line_edit.setToolTip(" -> ".join(site.value for site in sites))
    line_edit.setCursorPosition(0)


def _style_config_line_edit(line_edit: QLineEdit, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    line_edit.setReadOnly(True)
    line_edit.setCursorPosition(0)
    line_edit.setToolTip(line_edit.text())
    line_edit.setStyleSheet(
        f"""
        QLineEdit {{
            font: "Courier";
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 8px;
            padding: 3px 8px;
            background: {colors["surface"]};
        }}
        """
    )


def _style_site_list(list_widget: QListWidget, min_height: int, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    list_widget.setMinimumHeight(min_height)
    list_widget.setStyleSheet(
        f"""
        QListWidget {{
            color: {colors["text"]};
            selection-color: {colors["text"]};
            selection-background-color: {colors["surface_pressed"]};
            border: 1px solid {colors["border"]};
            border-radius: 8px;
            padding: 5px;
            background: {colors["surface"]};
        }}
        QListWidget::item {{
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 7px;
            padding: 5px 9px;
            margin: 3px;
            background: {colors["surface_muted"]};
        }}
        QListWidget::item:hover {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_hover"]};
        }}
        QListWidget::item:selected,
        QListWidget::item:selected:active,
        QListWidget::item:selected:!active,
        QListWidget::item:selected:hover {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_pressed"]};
        }}
        """
    )


def _style_dialog(dialog: QDialog, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    dialog.setStyleSheet(
        f"""
        QDialog {{
            color: {colors["text"]};
            background: {colors["window"]};
        }}
        QScrollArea {{
            border: 0;
            background: {colors["window"]};
        }}
        {build_scrollbar_style(dark)}
        """
    )


def _localize_dialog_buttons(buttons: QDialogButtonBox) -> None:
    if ok_button := buttons.button(QDialogButtonBox.StandardButton.Ok):
        ok_button.setText("保存")
    if cancel_button := buttons.button(QDialogButtonBox.StandardButton.Cancel):
        cancel_button.setText("取消")


class SitePaletteList(QListWidget):
    def __init__(
        self,
        sites: list[Website],
        parent: QWidget | None = None,
        *,
        removable_source=None,
        dark: bool = False,
    ):
        super().__init__(parent)
        self._removable_source = removable_source
        self.on_removed = None
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        _style_site_list(self, 82, dark)
        _setup_site_list(self, sites)

    def _removable_drop_source(self, source) -> QListWidget | None:
        if self._removable_source is not None:
            return self._removable_source if source is self._removable_source else None
        return source if isinstance(source, PrioritySiteList) else None

    def dragEnterEvent(self, event) -> None:
        if event.source() is self:
            event.ignore()
            return
        if self._removable_drop_source(event.source()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            event.ignore()
            return
        if self._removable_drop_source(event.source()) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.source() is self:
            event.ignore()
            return
        removable_source = self._removable_drop_source(event.source())
        if removable_source is not None:
            removed_sites = set(getattr(removable_source, "drag_sites", []) or _selected_sites(removable_source))
            if not removed_sites and removable_source.currentItem() is not None:
                site_value = removable_source.currentItem().data(Qt.ItemDataRole.UserRole)
                removed_sites = {Website(site_value)} if site_value in Website else set()
            _setup_site_list(
                removable_source,
                [site for site in _list_sites(removable_source) if site not in removed_sites],
            )
            if self.on_removed is not None:
                self.on_removed()
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class PrioritySiteList(QListWidget):
    def __init__(
        self, allowed_sites: list[Website], height: int = 74, parent: QWidget | None = None, dark: bool = False
    ):
        super().__init__(parent)
        self._allowed_sites = list(dict.fromkeys(allowed_sites))
        self.drag_sites: list[Website] = []
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFixedHeight(height)
        _style_site_list(self, height, dark)

    def dragEnterEvent(self, event) -> None:
        if isinstance(event.source(), QListWidget):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if isinstance(event.source(), QListWidget):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        source = event.source()
        if isinstance(source, QListWidget) and source is not self:
            sites = _selected_sites(source)
            self._insert_sites(sites, self._drop_row(event))
            event.acceptProposedAction()
            return
        super().dropEvent(event)
        self.normalize()

    def mimeData(self, items: list[QListWidgetItem]):
        self.drag_sites = _selected_sites(self)
        return super().mimeData(items)

    def normalize(self) -> None:
        allowed_set = set(self._allowed_sites)
        _setup_site_list(self, [site for site in _list_sites(self) if site in allowed_set])

    def _drop_row(self, event) -> int:
        try:
            row = self.indexAt(event.position().toPoint()).row()
        except AttributeError:
            row = self.indexAt(event.pos()).row()
        return self.count() if row < 0 else row

    def _insert_sites(self, sites: list[Website], row: int) -> None:
        allowed_set = set(self._allowed_sites)
        inserted = [site for site in sites if site in allowed_set]
        if not inserted:
            return
        current = [site for site in _list_sites(self) if site not in inserted]
        row = max(0, min(row, len(current)))
        _setup_site_list(self, current[:row] + inserted + current[row:])


class SiteListEditorDialog(QDialog):
    def __init__(
        self, title: str, selected_sites: list[Website], all_sites: list[Website], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(780, 540)
        self._dark = bool(getattr(parent, "dark_mode", False))
        _style_dialog(self, self._dark)
        self._all_sites = list(dict.fromkeys(all_sites))
        self._selected_sites = list(dict.fromkeys(selected_sites))

        layout = QVBoxLayout(self)

        self.selected_list = PrioritySiteList(self._all_sites, 168, self, self._dark)
        self.available_list = SitePaletteList(
            self._all_sites, self, removable_source=self.selected_list, dark=self._dark
        )
        self.available_list.on_removed = self._sync_selected_from_list

        layout.addWidget(self._build_panel("可用网站", self.available_list))
        layout.addWidget(self._build_panel("启用网站（从左到右优先级递减）", self.selected_list), 1)

        actions = QHBoxLayout()
        add_button = QPushButton("添加选中")
        remove_button = QPushButton("移除选中")
        add_all_button = QPushButton("全部添加")
        clear_button = QPushButton("清空")
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addWidget(add_all_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        for button in (add_button, remove_button, add_all_button, clear_button):
            _style_inline_button(button, self._dark)

        add_button.clicked.connect(self._add_selected)
        remove_button.clicked.connect(self._remove_selected)
        add_all_button.clicked.connect(self._add_all)
        clear_button.clicked.connect(self._clear_selected)
        self.available_list.itemDoubleClicked.connect(lambda _item: self._add_selected())
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for button in buttons.buttons():
            _style_inline_button(button, self._dark)

        self._refresh_lists()

    def selected_sites(self) -> list[Website]:
        return _list_sites(self.selected_list)

    def _sync_selected_from_list(self) -> None:
        self._selected_sites = self.selected_sites()

    def _build_panel(self, title: str, list_widget: QListWidget) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        label = QLabel(title)
        label.setStyleSheet(f"font-weight: bold; color: {get_theme_tokens(self._dark)['text']};")
        layout.addWidget(label)
        layout.addWidget(list_widget)
        return panel

    def _refresh_lists(self) -> None:
        _setup_site_list(self.available_list, self._all_sites)
        _setup_site_list(self.selected_list, self._selected_sites)

    def _add_selected(self) -> None:
        self._selected_sites = self.selected_sites()
        for site in _selected_sites(self.available_list):
            if site not in self._selected_sites:
                self._selected_sites.append(site)
        self._refresh_lists()

    def _remove_selected(self) -> None:
        selected = set(_selected_sites(self.selected_list))
        self._selected_sites = [site for site in self.selected_sites() if site not in selected]
        self._refresh_lists()

    def _add_all(self) -> None:
        self._selected_sites = list(self._all_sites)
        self._refresh_lists()

    def _clear_selected(self) -> None:
        self._selected_sites = []
        self._refresh_lists()


class FieldPriorityDialog(QDialog):
    def __init__(
        self,
        title: str,
        scraping_type: FixedScrapingType,
        type_sites: list[Website],
        field_configs: dict[CrawlerResultFields, FieldPriorityConfig],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 680)
        self._dark = bool(getattr(parent, "dark_mode", False))
        _style_dialog(self, self._dark)
        self._scraping_type = scraping_type
        self._type_sites = list(dict.fromkeys(type_sites))
        self._field_configs = field_configs
        self._field_lists: dict[CrawlerResultFields, QListWidget] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_palette_panel())

        quick_actions = QHBoxLayout()
        reset_button = QPushButton("全部使用类型顺序")
        keep_button = QPushButton("只保留已启用网站")
        clear_button = QPushButton("清空全部字段")
        quick_actions.addWidget(reset_button)
        quick_actions.addWidget(keep_button)
        quick_actions.addWidget(clear_button)
        quick_actions.addStretch(1)
        layout.addLayout(quick_actions)
        for button in (reset_button, keep_button, clear_button):
            _style_inline_button(button, self._dark)

        reset_button.clicked.connect(self._reset_all)
        keep_button.clicked.connect(self._keep_enabled_only)
        clear_button.clicked.connect(self._clear_all)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        for row, field in enumerate(FIELD_PRIORITY_FIELDS):
            label = QLabel(FIELD_TITLES.get(field, field.value))
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setMinimumWidth(88)
            label.setStyleSheet(f"color: {get_theme_tokens(self._dark)['text']};")
            list_widget = PrioritySiteList(self._type_sites, 58, self, self._dark)
            configured = self._field_configs.get(field, FieldPriorityConfig()).site_prority
            sites = [site for site in configured if site in self._type_sites]
            _setup_site_list(list_widget, sites)
            remove_button = QPushButton("移除")
            reset_field_button = QPushButton("重置")
            _style_inline_button(remove_button, self._dark)
            _style_inline_button(reset_field_button, self._dark)
            remove_button.clicked.connect(partial(self._remove_from_field, field))
            reset_field_button.clicked.connect(partial(self._reset_field, field))

            button_layout = QHBoxLayout()
            button_layout.addWidget(remove_button)
            button_layout.addWidget(reset_field_button)

            grid.addWidget(label, row, 0)
            grid.addWidget(list_widget, row, 1)
            grid.addLayout(button_layout, row, 2)
            self._field_lists[field] = list_widget

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for button in buttons.buttons():
            _style_inline_button(button, self._dark)

    def field_configs(self) -> dict[CrawlerResultFields, FieldPriorityConfig]:
        return {
            field: FieldPriorityConfig(site_prority=_list_sites(list_widget))
            for field, list_widget in self._field_lists.items()
        }

    def _build_palette_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        label = QLabel("可用网站（拖到下方字段中；字段内从左到右优先级递减）")
        label.setStyleSheet(f"font-weight: bold; color: {get_theme_tokens(self._dark)['text']};")
        panel_layout.addWidget(label)
        panel_layout.addWidget(SitePaletteList(self._type_sites, self, dark=self._dark))
        return panel

    def _remove_from_field(self, field: CrawlerResultFields) -> None:
        list_widget = self._field_lists[field]
        selected = set(_selected_sites(list_widget))
        _setup_site_list(list_widget, [site for site in _list_sites(list_widget) if site not in selected])

    def _reset_field(self, field: CrawlerResultFields) -> None:
        _setup_site_list(self._field_lists[field], self._type_sites)

    def _reset_all(self) -> None:
        for list_widget in self._field_lists.values():
            _setup_site_list(list_widget, self._type_sites)

    def _keep_enabled_only(self) -> None:
        type_site_set = set(self._type_sites)
        for list_widget in self._field_lists.values():
            _setup_site_list(list_widget, [site for site in _list_sites(list_widget) if site in type_site_set])

    def _clear_all(self) -> None:
        for list_widget in self._field_lists.values():
            list_widget.clear()


def setup_site_priority_ui(window: "MyMAinWindow") -> None:
    ui = window.Ui
    window._type_website_ui = {
        FixedScrapingType.YOUMA: TypeWebsiteUi(FixedScrapingType.YOUMA, "有码", ui.lineEdit_website_youma, 0),
        FixedScrapingType.WUMA: TypeWebsiteUi(FixedScrapingType.WUMA, "无码", ui.lineEdit_website_wuma, 2),
        FixedScrapingType.SUREN: TypeWebsiteUi(FixedScrapingType.SUREN, "素人", ui.lineEdit_website_suren, 4),
        FixedScrapingType.FC2: TypeWebsiteUi(FixedScrapingType.FC2, "FC2", ui.lineEdit_website_fc2, 6),
        FixedScrapingType.OUMEI: TypeWebsiteUi(FixedScrapingType.OUMEI, "欧美", ui.lineEdit_website_oumei, 8),
        FixedScrapingType.GUOCHAN: TypeWebsiteUi(FixedScrapingType.GUOCHAN, "国产", ui.lineEdit_website_guochan, 10),
    }
    for info in window._type_website_ui.values():
        edit_button = _make_inline_button("编辑网站")
        priority_button = _make_inline_button("字段优先级")
        info.edit_button = edit_button
        info.priority_button = priority_button
        edit_button.clicked.connect(partial(_open_site_editor, window, info.scraping_type))
        priority_button.clicked.connect(partial(_open_priority_editor, window, info.scraping_type))
        ui.gridLayout_36.addWidget(edit_button, info.row, 2)
        ui.gridLayout_36.addWidget(priority_button, info.row, 3)

    _hide_legacy_field_website_group(window)
    apply_site_priority_theme(window)


def apply_site_priority_theme(window: "MyMAinWindow") -> None:
    dark = bool(getattr(window, "dark_mode", False))
    for info in getattr(window, "_type_website_ui", {}).values():
        _style_config_line_edit(info.line_edit, dark)
        if info.edit_button is not None:
            _style_inline_button(info.edit_button, dark)
        if info.priority_button is not None:
            _style_inline_button(info.priority_button, dark)


def refresh_site_priority_ui(window: "MyMAinWindow") -> None:
    for info in getattr(window, "_type_website_ui", {}).values():
        _set_site_summary(info.line_edit)


def _style_inline_button(button: QPushButton, dark: bool = False) -> None:
    colors = _site_priority_colors(dark)
    button.setStyleSheet(
        f"""
        QPushButton {{
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 7px;
            padding: 3px 8px;
            background: {colors["surface"]};
        }}
        QPushButton:hover {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_hover"]};
        }}
        QPushButton:pressed {{
            color: {colors["text"]};
            border: 1px solid {colors["border_active"]};
            background: {colors["surface_pressed"]};
        }}
        """
    )


def _make_inline_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumHeight(28)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    _style_inline_button(button)
    return button


def _open_site_editor(window: "MyMAinWindow", scraping_type: FixedScrapingType) -> None:
    info = window._type_website_ui[scraping_type]
    selected_sites = _parse_sites(info.line_edit.text())
    registered_sites = [Website(site) for site in get_registered_crawler_site_values() if site in Website]
    all_sites = list(dict.fromkeys(selected_sites + registered_sites))
    dialog = SiteListEditorDialog(f"编辑{info.title}网站源", selected_sites, all_sites, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    sites = dialog.selected_sites()
    if not sites:
        QMessageBox.warning(window, "网站源不能为空", f"{info.title}至少需要保留一个网站。")
        return
    info.line_edit.setText(_sites_text(sites))
    _set_site_summary(info.line_edit)
    from mdcx.config.manager import manager

    manager.config.fill_missing_type_field_configs()
    previous_sites = manager.config.get_type_sites(scraping_type)
    setattr(manager.config, SCRAPING_TYPE_SITE_FIELDS[scraping_type], sites)
    for field in ManualConfig.REDUCED_FIELDS:
        current = manager.config.type_field_configs.setdefault(scraping_type, {}).setdefault(
            field, FieldPriorityConfig()
        )
        current.site_prority = _sync_field_sites_after_type_sites_changed(
            current.site_prority,
            previous_sites,
            sites,
        )
    manager.config.fill_missing_type_field_configs()
    refresh_site_priority_ui(window)


def _open_priority_editor(window: "MyMAinWindow", scraping_type: FixedScrapingType) -> None:
    info = window._type_website_ui[scraping_type]
    type_sites = _parse_sites(info.line_edit.text())
    if not type_sites:
        QMessageBox.warning(window, "没有可用网站", f"请先为{info.title}配置至少一个网站。")
        return

    from mdcx.config.manager import manager

    setattr(manager.config, SCRAPING_TYPE_SITE_FIELDS[scraping_type], type_sites)
    manager.config.fill_missing_type_field_configs()
    dialog = FieldPriorityDialog(
        f"{info.title}字段优先级",
        scraping_type,
        type_sites,
        manager.config.type_field_configs.get(scraping_type, {}),
        window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    manager.config.type_field_configs[scraping_type] = dialog.field_configs()
    manager.config.fill_missing_type_field_configs()
    refresh_site_priority_ui(window)


def _hide_legacy_field_website_group(window: "MyMAinWindow") -> None:
    window.Ui.groupBox_35.hide()
    window.Ui.layoutWidget2.hide()
    window.Ui.scrollAreaWidgetContents_guaxiaowangzhan.setMinimumHeight(1330)
    window.Ui.scrollAreaWidgetContents_guaxiaowangzhan.resize(
        window.Ui.scrollAreaWidgetContents_guaxiaowangzhan.width(),
        1330,
    )
