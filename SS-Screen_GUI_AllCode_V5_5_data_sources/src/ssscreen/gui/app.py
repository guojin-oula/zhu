"""PySide6 desktop workbench for ``ss-screen``.

The desktop application is deliberately a GUI wrapper over the existing Click
surface rather than a second scientific implementation.  Command pages are
built from Click metadata at runtime, and jobs are executed in a subprocess via
``python -m ssscreen.cli.app``.  That keeps command validation, defaults,
scientific algorithms, output schemas, and exit codes identical between CLI and
GUI.
"""

from __future__ import annotations

import csv
import json
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import click

try:
    from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl, Signal
    from PySide6.QtGui import QDesktopServices, QFont, QTextCursor
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFileSystemModel,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTreeView,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised only without GUI extra
    raise RuntimeError(
        "SS-Screen GUI requires PySide6. Install it with `pip install -e \".[gui]\"` "
        "or `pip install \"ss-screen[gui]\"`."
    ) from exc

from .. import __version__
from ..cli.app import cli
from .metadata import COMMANDS, PATH_PRESETS, STAGES, CommandPresentation


APP_TITLE = f"SS-Screen V{__version__} · Materials Engineering Workbench"
PROJECT_DIRS = tuple(directory for _sid, _name, directory in STAGES if directory) + (
    "logs",
    "models",
)


@dataclass
class RunRecord:
    """Small in-memory summary of a GUI-launched CLI process."""

    started: str
    command: str
    exit_code: int | None = None


class ValueEditor(QWidget):
    """Qt editor that can serialize one Click option back to argv tokens."""

    changed = Signal()

    def __init__(
        self,
        option: click.Option,
        preset: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.option = option
        self._path_type = option.type if isinstance(option.type, click.Path) else None
        option_names = [*option.opts, *option.secondary_opts]
        self._semantic_directory = bool(
            self._path_type is not None
            and (
                (self._path_type.dir_okay and not self._path_type.file_okay)
                or option.name.endswith(("_dir", "_dirs"))
                or any(name.endswith(("-dir", "-dirs")) for name in option_names)
            )
        )
        self._default = option.default
        self._preset = preset
        self._mode = "text"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if option.is_bool_flag:
            self._mode = "bool"
            self.widget = QCheckBox()
            self.widget.setChecked(bool(option.default))
            self.widget.toggled.connect(self.changed)
            layout.addWidget(self.widget)
            layout.addStretch(1)
            return

        if isinstance(option.type, click.Choice) and not option.multiple:
            self._mode = "choice"
            self.widget = QComboBox()
            if option.default is None and not option.required:
                self.widget.addItem("")
            for choice in option.type.choices:
                self.widget.addItem(str(choice))
            value = self._initial_value()
            if value is not None:
                self.widget.setCurrentText(str(value))
            self.widget.currentTextChanged.connect(self.changed)
            layout.addWidget(self.widget, 1)
            return

        if option.multiple:
            self._mode = "multi"
            self.widget = QPlainTextEdit()
            self.widget.setMaximumHeight(82)
            self.widget.setPlaceholderText("每行一个值；运行时会重复传递该选项")
            initial = self._initial_value()
            if initial:
                if isinstance(initial, (list, tuple)):
                    self.widget.setPlainText("\n".join(str(x) for x in initial))
                else:
                    self.widget.setPlainText(str(initial))
            self.widget.textChanged.connect(self.changed)
            layout.addWidget(self.widget, 1)
            if self._path_type is not None:
                if self._path_type.file_okay:
                    file_btn = QPushButton("添加文件")
                    file_btn.clicked.connect(self._add_files)
                    layout.addWidget(file_btn)
                if self._path_type.dir_okay:
                    dir_btn = QPushButton("添加目录")
                    dir_btn.clicked.connect(self._add_directory)
                    layout.addWidget(dir_btn)
            return

        self.widget = QLineEdit()
        initial = self._initial_value()
        if initial is not None:
            self.widget.setText(str(initial))
        self.widget.textChanged.connect(self.changed)
        layout.addWidget(self.widget, 1)

        if self._path_type is not None:
            browse_btn = QPushButton("浏览…")
            browse_btn.clicked.connect(self._browse_single)
            layout.addWidget(browse_btn)

    def _initial_value(self) -> Any:
        if self._preset is not None:
            return self._preset
        if self.option.default is None:
            return None
        return self.option.default

    def reset(self) -> None:
        """Restore Click default, falling back to a GUI path preset."""
        value = self._initial_value()
        if self._mode == "bool":
            self.widget.setChecked(bool(value))
        elif self._mode == "choice":
            self.widget.setCurrentText("" if value is None else str(value))
        elif self._mode == "multi":
            if value is None:
                self.widget.clear()
            elif isinstance(value, (tuple, list)):
                self.widget.setPlainText("\n".join(str(x) for x in value))
            else:
                self.widget.setPlainText(str(value))
        else:
            self.widget.setText("" if value is None else str(value))

    def _browse_single(self) -> None:
        path_type = self._path_type
        if path_type is None:
            return
        current = self.widget.text().strip() or str(Path.cwd())
        if self._semantic_directory:
            value = QFileDialog.getExistingDirectory(self, "选择目录", current)
        elif path_type.exists:
            value, _ = QFileDialog.getOpenFileName(self, "选择文件", current)
        else:
            value, _ = QFileDialog.getSaveFileName(self, "选择输出文件", current)
        if value:
            self.widget.setText(value)

    def _add_files(self) -> None:
        values, _ = QFileDialog.getOpenFileNames(self, "添加文件")
        if values:
            old = self.widget.toPlainText().strip()
            merged = ([old] if old else []) + values
            self.widget.setPlainText("\n".join(merged))

    def _add_directory(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "添加目录")
        if value:
            old = self.widget.toPlainText().strip()
            self.widget.setPlainText("\n".join(([old] if old else []) + [value]))

    def is_empty(self) -> bool:
        if self._mode == "bool":
            return False
        if self._mode == "choice":
            return not self.widget.currentText().strip()
        if self._mode == "multi":
            return not self.widget.toPlainText().strip()
        return not self.widget.text().strip()

    def values(self) -> list[str]:
        if self._mode == "choice":
            value = self.widget.currentText().strip()
            return [value] if value else []
        if self._mode == "multi":
            return [line.strip() for line in self.widget.toPlainText().splitlines() if line.strip()]
        if self._mode == "text":
            value = self.widget.text().strip()
            return [value] if value else []
        return []

    def argv(self) -> list[str]:
        """Serialize this editor using the Click option's actual flag names."""
        option = self.option
        if self._mode == "bool":
            value = self.widget.isChecked()
            default = bool(option.default)
            if value == default:
                return []
            if value:
                return [option.opts[0]]
            if option.secondary_opts:
                return [option.secondary_opts[0]]
            return []

        values = self.values()
        if not values:
            return []
        flag = option.opts[0]
        out: list[str] = []
        if option.multiple:
            for value in values:
                out.extend([flag, value])
        else:
            out.extend([flag, values[0]])
        return out


class CommandPage(QWidget):
    """One generated form for one existing Click command."""

    run_requested = Signal(list, str)

    def __init__(
        self,
        presentation: CommandPresentation,
        command: click.Command,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.presentation = presentation
        self.command = command
        self.editors: list[tuple[click.Option, ValueEditor]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        title = QLabel(presentation.title)
        title.setObjectName("pageTitle")
        root.addWidget(title)

        command_name = "ss-screen " + " ".join(presentation.command_path)
        command_label = QLabel(command_name)
        command_label.setObjectName("commandName")
        root.addWidget(command_label)

        description = QLabel(command.help or command.short_help or "")
        description.setWordWrap(True)
        description.setObjectName("pageDescription")
        root.addWidget(description)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 4)

        options_box = QGroupBox("Parameters / 参数")
        form = QFormLayout(options_box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(9)

        presets = PATH_PRESETS.get(presentation.command_path, {})
        for param in command.params:
            if not isinstance(param, click.Option):
                continue
            if param.name == "help":
                continue
            preset = None
            for opt_name in param.opts:
                if opt_name in presets:
                    preset = presets[opt_name]
                    break
            editor = ValueEditor(param, preset=preset)
            editor.changed.connect(self.refresh_preview)
            self.editors.append((param, editor))

            flag_text = param.opts[0] if param.opts else param.name
            if param.secondary_opts:
                flag_text += " / " + param.secondary_opts[0]
            if param.required:
                flag_text += "  *"
            label = QLabel(flag_text)
            label.setToolTip(param.help or "")
            editor.setToolTip(param.help or "")
            form.addRow(label, editor)

            if param.help:
                help_label = QLabel(param.help)
                help_label.setWordWrap(True)
                help_label.setObjectName("optionHelp")
                form.addRow("", help_label)

        body_layout.addWidget(options_box)

        advanced_box = QGroupBox("Advanced / 附加参数")
        advanced_layout = QVBoxLayout(advanced_box)
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("可选：直接追加 CLI 参数，例如 --limit 1")
        self.extra_args.textChanged.connect(self.refresh_preview)
        advanced_layout.addWidget(self.extra_args)
        body_layout.addWidget(advanced_box)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        preview_label = QLabel("Command Preview / 命令预览")
        preview_label.setObjectName("sectionLabel")
        root.addWidget(preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(72)
        self.preview.setObjectName("commandPreview")
        root.addWidget(self.preview)

        actions = QHBoxLayout()
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self.reset)
        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(self.copy_command)
        run_btn = QPushButton("运行任务")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(self.emit_run)
        actions.addWidget(reset_btn)
        actions.addStretch(1)
        actions.addWidget(copy_btn)
        actions.addWidget(run_btn)
        root.addLayout(actions)

        self.refresh_preview()

    def reset(self) -> None:
        for _option, editor in self.editors:
            editor.reset()
        self.extra_args.clear()
        self.refresh_preview()

    def argv(self) -> list[str]:
        argv = list(self.presentation.command_path)
        for _option, editor in self.editors:
            argv.extend(editor.argv())
        extra = self.extra_args.text().strip()
        if extra:
            argv.extend(shlex.split(extra))
        return argv

    def missing_required(self) -> list[str]:
        missing = []
        for option, editor in self.editors:
            if option.required and editor.is_empty():
                missing.append(option.opts[0] if option.opts else option.name)
        return missing

    def refresh_preview(self) -> None:
        try:
            text = shlex.join(["ss-screen", *self.argv()])
        except ValueError as exc:
            text = f"参数解析错误：{exc}"
        self.preview.setPlainText(text)

    def copy_command(self) -> None:
        QApplication.clipboard().setText(self.preview.toPlainText())

    def emit_run(self) -> None:
        missing = self.missing_required()
        if missing:
            QMessageBox.warning(
                self,
                "缺少必填参数",
                "请先填写以下参数：\n" + "\n".join(f"• {x}" for x in missing),
            )
            return
        try:
            argv = self.argv()
        except ValueError as exc:
            QMessageBox.warning(self, "附加参数错误", str(exc))
            return
        self.run_requested.emit(argv, self.presentation.title)






def _wrap_in_scroll_area(
    content: QWidget,
    *,
    min_width: int = 760,
    min_height: int = 620,
) -> QScrollArea:
    """Keep engineering forms readable instead of letting Qt squash them.

    On smaller screens or Windows display scaling, the content keeps its
    natural minimum size and the tab becomes scrollable.
    """
    content.setMinimumWidth(min_width)
    content.setMinimumHeight(min_height)
    content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(content)
    return scroll




class DatasetSourcePage(QWidget):
    """Engineering GUI for Stage 01 external data sources.

    Materials Project and WBM are represented as external sources.  Their
    normalized local DataFrame outputs are the project objects consumed by
    later SS-Screen stages.
    """

    run_requested = Signal(list, str)

    def __init__(self, project_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_provider = project_provider

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("数据源 / Data Sources")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        badge = QLabel("Stage 01")
        badge.setObjectName("stateBadge")
        header.addWidget(badge)
        root.addLayout(header)

        subtitle = QLabel(
            "Materials Project 和 WBM 在这里作为外部材料数据源管理。"
            "SS-Screen 获取或导入数据后，将其规范化为工程内的本地 DataFrame；"
            "后续组成模板筛选、结构描述和结构匹配使用这些本地数据，而不是把外部数据库当作计算模块。"
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageDescription")
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(520)
        self.tabs.addTab(self._build_mp_tab(), "Materials Project")
        self.tabs.addTab(self._build_wbm_tab(), "WBM Dataset")
        self.tabs.addTab(self._build_local_tab(), "Local Datasets / 本地数据")
        root.addWidget(self.tabs, 1)

        boundary = QGroupBox("Data Boundary / 数据边界")
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.setContentsMargins(8, 8, 8, 8)
        note = QLabel(
            "外部数据源负责提供初始材料记录；SS-Screen 负责数据获取、规范化、"
            "本地保存和后续筛选。Materials Project 的 API Key 仅通过右侧 Properties "
            "中的 Connection 设置注入当前任务进程，不写入项目输出文件。"
        )
        note.setWordWrap(True)
        note.setObjectName("optionHelp")
        boundary_layout.addWidget(note)
        root.addWidget(boundary)

        self.refresh_sources()
        self._refresh_mp_preview()
        self._refresh_wbm_preview()

    # ------------------------------------------------------------------
    # Common helpers
    # ------------------------------------------------------------------

    def _project_root(self) -> Path:
        return Path(self.project_provider()).expanduser().resolve()

    def _resolve(self, text: str) -> Path:
        path = Path(text.strip()).expanduser()
        if not path.is_absolute():
            path = self._project_root() / path
        return path

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self._project_root()))
        except Exception:
            return str(path)

    def _path_editor(
        self,
        default: str,
        *,
        save_file: bool = False,
    ) -> tuple[QWidget, QLineEdit]:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        edit = QLineEdit(default)
        browse = QPushButton("…")
        browse.setMaximumWidth(34)

        def choose() -> None:
            base = str(self._project_root())
            if save_file:
                value, _ = QFileDialog.getSaveFileName(
                    self,
                    "选择输出文件",
                    base,
                )
            else:
                value, _ = QFileDialog.getOpenFileName(
                    self,
                    "选择文件",
                    base,
                )
            if value:
                edit.setText(self._display_path(Path(value)))

        browse.clicked.connect(choose)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return host, edit

    def _format_size(self, path: Path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return "—"
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.1f} MB"

    # ------------------------------------------------------------------
    # Materials Project
    # ------------------------------------------------------------------

    def _build_mp_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        identity = QGroupBox("Source Identity / 数据源说明")
        identity_form = QFormLayout(identity)
        identity_form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        identity_form.setHorizontalSpacing(12)
        identity_form.setVerticalSpacing(7)

        source_type = QLabel("External materials database / 外部材料数据库")
        source_use = QLabel(
            "用于获取初始材料结构与筛选所需数据库字段，"
            "获取后统一保存为项目内的 01_dataset/mp.df。"
        )
        source_use.setWordWrap(True)
        source_flow = QLabel(
            "Materials Project → SS-Screen 数据获取/规范化 → "
            "01_dataset/mp.df → 组成模板筛选"
        )
        source_flow.setWordWrap(True)

        identity_form.addRow("类型", source_type)
        identity_form.addRow("在 SS-Screen 中的作用", source_use)
        identity_form.addRow("数据流", source_flow)
        layout.addWidget(identity)

        acquire = QGroupBox("Materials Project Acquisition / 数据获取")
        form = QFormLayout(acquire)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.mp_backend = QComboBox()
        self.mp_backend.addItem("API / 在线接口", "api")
        self.mp_backend.addItem("Offline / 离线数据库", "offline")
        form.addRow("数据模式", self.mp_backend)

        offline_host, self.mp_offline_db = self._path_editor("")
        form.addRow("离线数据库", offline_host)

        self.mp_max_e_hull = QLineEdit("0.01")
        self.mp_max_e_hull.setMaximumWidth(180)
        form.addRow("最大凸包距离 (eV/atom)", self.mp_max_e_hull)

        host, self.mp_output = self._path_editor(
            "01_dataset/mp.df",
            save_file=True,
        )
        form.addRow("本地标准化数据", host)

        host, self.mp_provenance = self._path_editor(
            "01_dataset/mp.df.provenance.json",
            save_file=True,
        )
        form.addRow("Provenance / 来源记录", host)

        api_note = QLabel(
            "API 模式下不在命令里保存密钥。请在右侧 Properties → Connection "
            "填写 MP API Key；GUI 只把它注入当前运行进程。"
        )
        api_note.setWordWrap(True)
        api_note.setObjectName("optionHelp")
        form.addRow("API Key", api_note)
        layout.addWidget(acquire)

        result = QGroupBox("Local Result / 本地结果")
        result_form = QFormLayout(result)
        result_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mp_status = QLabel("未生成")
        self.mp_size = QLabel("—")
        self.mp_provenance_status = QLabel("未生成")
        result_form.addRow("mp.df", self.mp_status)
        result_form.addRow("文件大小", self.mp_size)
        result_form.addRow("Provenance", self.mp_provenance_status)
        layout.addWidget(result)

        preview_label = QLabel("Command Preview / 命令预览")
        preview_label.setObjectName("sectionLabel")
        layout.addWidget(preview_label)

        self.mp_preview = QPlainTextEdit()
        self.mp_preview.setReadOnly(True)
        self.mp_preview.setMaximumHeight(82)
        self.mp_preview.setObjectName("commandPreview")
        layout.addWidget(self.mp_preview)

        actions = QHBoxLayout()
        refresh = QPushButton("检查本地结果")
        refresh.clicked.connect(self.refresh_sources)
        copy = QPushButton("复制命令")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.mp_preview.toPlainText()
            )
        )
        run = QPushButton("获取 Materials Project 数据")
        run.setObjectName("primaryButton")
        run.clicked.connect(self._run_mp)
        actions.addWidget(refresh)
        actions.addStretch(1)
        actions.addWidget(copy)
        actions.addWidget(run)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.mp_backend.currentIndexChanged.connect(
            self._mp_backend_changed
        )
        for editor in (
            self.mp_offline_db,
            self.mp_max_e_hull,
            self.mp_output,
            self.mp_provenance,
        ):
            editor.textChanged.connect(self._refresh_mp_preview)

        self._mp_backend_changed()
        return _wrap_in_scroll_area(page, min_width=840, min_height=680)

    def _mp_backend_changed(self) -> None:
        offline = self.mp_backend.currentData() == "offline"
        self.mp_offline_db.setEnabled(offline)
        self._refresh_mp_preview()

    def _mp_argv(self) -> list[str]:
        argv = [
            "dataset",
            "mp",
            "--backend",
            str(self.mp_backend.currentData()),
        ]
        if (
            self.mp_backend.currentData() == "offline"
            and self.mp_offline_db.text().strip()
        ):
            argv.extend([
                "--offline-db",
                self.mp_offline_db.text().strip(),
            ])

        argv.extend([
            "--max-e-hull",
            self.mp_max_e_hull.text().strip() or "0.01",
            "--output",
            self.mp_output.text().strip(),
            "--provenance",
            self.mp_provenance.text().strip(),
        ])
        return argv

    def _refresh_mp_preview(self) -> None:
        if hasattr(self, "mp_preview"):
            self.mp_preview.setPlainText(
                shlex.join(["ss-screen", *self._mp_argv()])
            )

    def _run_mp(self) -> None:
        if not self.mp_output.text().strip():
            QMessageBox.warning(
                self,
                "缺少输出路径",
                "请设置 Materials Project 本地 DataFrame 输出路径。",
            )
            return
        if (
            self.mp_backend.currentData() == "offline"
            and not self.mp_offline_db.text().strip()
        ):
            QMessageBox.warning(
                self,
                "缺少离线数据库",
                "Offline 模式需要选择离线数据库文件。",
            )
            return
        try:
            if float(self.mp_max_e_hull.text().strip()) < 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(
                self,
                "参数错误",
                "最大凸包距离必须是非负数字。",
            )
            return

        self.run_requested.emit(
            self._mp_argv(),
            "Materials Project 数据获取",
        )

    # ------------------------------------------------------------------
    # WBM
    # ------------------------------------------------------------------

    def _build_wbm_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        identity = QGroupBox("Source Identity / 数据源说明")
        identity_layout = QVBoxLayout(identity)
        intro = QLabel(
            "WBM Dataset 作为另一个规范化材料数据源，与 Materials Project "
            "数据可以在 composition-screen 阶段通过重复 --df 一起参与筛选。"
        )
        intro.setWordWrap(True)
        identity_layout.addWidget(intro)
        layout.addWidget(identity)

        acquire = QGroupBox("WBM Data / 数据获取")
        form = QFormLayout(acquire)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        host, self.wbm_output = self._path_editor(
            "01_dataset/wbm.df",
            save_file=True,
        )
        form.addRow("本地标准化数据", host)
        layout.addWidget(acquire)

        result = QGroupBox("Local Result / 本地结果")
        result_form = QFormLayout(result)
        result_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.wbm_status = QLabel("未生成")
        self.wbm_size = QLabel("—")
        result_form.addRow("wbm.df", self.wbm_status)
        result_form.addRow("文件大小", self.wbm_size)
        layout.addWidget(result)

        self.wbm_preview = QPlainTextEdit()
        self.wbm_preview.setReadOnly(True)
        self.wbm_preview.setMaximumHeight(75)
        self.wbm_preview.setObjectName("commandPreview")
        layout.addWidget(QLabel("Command Preview / 命令预览"))
        layout.addWidget(self.wbm_preview)

        actions = QHBoxLayout()
        refresh = QPushButton("检查本地结果")
        refresh.clicked.connect(self.refresh_sources)
        copy = QPushButton("复制命令")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.wbm_preview.toPlainText()
            )
        )
        run = QPushButton("获取 WBM 数据")
        run.setObjectName("primaryButton")
        run.clicked.connect(self._run_wbm)
        actions.addWidget(refresh)
        actions.addStretch(1)
        actions.addWidget(copy)
        actions.addWidget(run)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.wbm_output.textChanged.connect(self._refresh_wbm_preview)

        return _wrap_in_scroll_area(page, min_width=840, min_height=560)

    def _wbm_argv(self) -> list[str]:
        return [
            "dataset",
            "wbm",
            "--output",
            self.wbm_output.text().strip(),
        ]

    def _refresh_wbm_preview(self) -> None:
        if hasattr(self, "wbm_preview"):
            self.wbm_preview.setPlainText(
                shlex.join(["ss-screen", *self._wbm_argv()])
            )

    def _run_wbm(self) -> None:
        if not self.wbm_output.text().strip():
            QMessageBox.warning(
                self,
                "缺少输出路径",
                "请设置 WBM 本地 DataFrame 输出路径。",
            )
            return
        self.run_requested.emit(
            self._wbm_argv(),
            "WBM 数据获取",
        )

    # ------------------------------------------------------------------
    # Local project data
    # ------------------------------------------------------------------

    def _build_local_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        local_box = QGroupBox("Normalized Local Datasets / 项目本地数据")
        local_layout = QVBoxLayout(local_box)

        self.local_table = QTableWidget(0, 5)
        self.local_table.setHorizontalHeaderLabels(
            ["Data Source", "Local DataFrame", "状态", "大小", "下游用途"]
        )
        self.local_table.verticalHeader().setVisible(False)
        self.local_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.local_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.local_table.horizontalHeader().setStretchLastSection(True)
        self.local_table.setColumnWidth(0, 180)
        self.local_table.setColumnWidth(1, 310)
        self.local_table.setColumnWidth(2, 90)
        self.local_table.setColumnWidth(3, 90)
        self.local_table.setMinimumHeight(150)
        local_layout.addWidget(self.local_table)
        layout.addWidget(local_box)

        provenance_box = QGroupBox(
            "Materials Project Provenance / 来源记录"
        )
        provenance_layout = QVBoxLayout(provenance_box)
        self.provenance_table = QTableWidget(0, 2)
        self.provenance_table.setHorizontalHeaderLabels(["字段", "值"])
        self.provenance_table.verticalHeader().setVisible(False)
        self.provenance_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.provenance_table.horizontalHeader().setStretchLastSection(True)
        self.provenance_table.setMinimumHeight(220)
        provenance_layout.addWidget(self.provenance_table)
        layout.addWidget(provenance_box, 1)

        downstream = QGroupBox("Downstream / 下游连接")
        downstream_layout = QVBoxLayout(downstream)
        downstream_note = QLabel(
            "组成模板筛选可以重复提供 --df，因此 mp.df、wbm.df 或其他规范化 "
            "DataFrame 可以组合使用。Stage 01 的输出是数据对象，Stage 02 才开始组成模板筛选。"
        )
        downstream_note.setWordWrap(True)
        downstream_layout.addWidget(downstream_note)
        layout.addWidget(downstream)

        actions = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_sources)
        open_dir = QPushButton("打开 01_dataset")
        open_dir.clicked.connect(self._open_dataset_dir)
        actions.addWidget(refresh)
        actions.addWidget(open_dir)
        actions.addStretch(1)
        layout.addLayout(actions)

        return _wrap_in_scroll_area(page, min_width=880, min_height=650)

    def refresh_sources(self) -> None:
        if not hasattr(self, "local_table"):
            return

        mp_path = self._resolve(self.mp_output.text())
        wbm_path = self._resolve(self.wbm_output.text())
        provenance_path = self._resolve(self.mp_provenance.text())

        self.mp_status.setText(
            "Ready · " + self._display_path(mp_path)
            if mp_path.exists()
            else "未生成"
        )
        self.mp_size.setText(self._format_size(mp_path))
        self.mp_provenance_status.setText(
            "Ready · " + self._display_path(provenance_path)
            if provenance_path.exists()
            else "未生成"
        )
        self.wbm_status.setText(
            "Ready · " + self._display_path(wbm_path)
            if wbm_path.exists()
            else "未生成"
        )
        self.wbm_size.setText(self._format_size(wbm_path))

        records = [
            (
                "Materials Project",
                mp_path,
                "Ready" if mp_path.exists() else "未生成",
                self._format_size(mp_path),
                "组成模板筛选 / 结构描述",
            ),
            (
                "WBM Dataset",
                wbm_path,
                "Ready" if wbm_path.exists() else "未生成",
                self._format_size(wbm_path),
                "组成模板筛选",
            ),
        ]
        self.local_table.setRowCount(len(records))
        for row, record in enumerate(records):
            for col, value in enumerate(record):
                if isinstance(value, Path):
                    display = self._display_path(value)
                else:
                    display = str(value)
                self.local_table.setItem(
                    row,
                    col,
                    QTableWidgetItem(display),
                )

        self.provenance_table.setRowCount(0)
        if provenance_path.exists():
            try:
                with provenance_path.open(
                    "r",
                    encoding="utf-8",
                ) as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    for key, value in data.items():
                        row = self.provenance_table.rowCount()
                        self.provenance_table.insertRow(row)
                        self.provenance_table.setItem(
                            row,
                            0,
                            QTableWidgetItem(str(key)),
                        )
                        if isinstance(value, (dict, list)):
                            display = json.dumps(
                                value,
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                        else:
                            display = str(value)
                        self.provenance_table.setItem(
                            row,
                            1,
                            QTableWidgetItem(display),
                        )
            except Exception as exc:
                self.provenance_table.insertRow(0)
                self.provenance_table.setItem(
                    0,
                    0,
                    QTableWidgetItem("读取失败"),
                )
                self.provenance_table.setItem(
                    0,
                    1,
                    QTableWidgetItem(str(exc)),
                )

        self._refresh_mp_preview()
        self._refresh_wbm_preview()

    def _open_dataset_dir(self) -> None:
        path = self._project_root() / "01_dataset"
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def select_section(self, section: str) -> None:
        if section in {"mp", "mp_fetch"}:
            self.tabs.setCurrentIndex(0)
        elif section in {"wbm", "wbm_fetch"}:
            self.tabs.setCurrentIndex(1)
        else:
            self.tabs.setCurrentIndex(2)
        self.refresh_sources()



class CompositionScreenPage(QWidget):
    """Engineering GUI for composition template screening.

    This page maps directly to ``ss-screen composition-screen`` while treating
    the two output files as persistent project results:
    ``composition_candidates.csv`` and ``composition_summary.json``.
    """

    run_requested = Signal(list, str)

    def __init__(self, project_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_provider = project_provider
        self._candidate_records: list[dict[str, str]] = []
        self._candidate_fields: list[str] = []
        self._template_field: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("组成模板筛选")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        badge = QLabel("流程第 1 步")
        badge.setObjectName("stateBadge")
        header.addWidget(badge)
        root.addLayout(header)

        subtitle = QLabel(
            "合并一个或多个规范化材料 DataFrame，可选使用价态过滤结果，"
            "再按照元素数、初筛带隙、凸包距离和组成模板条件筛选候选材料。"
            "本阶段的两个核心输出是候选材料表和筛选统计。"
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageDescription")
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(520)
        self.tabs.addTab(self._build_setup_tab(), "筛选设置与执行")
        self.tabs.addTab(self._build_results_tab(), "筛选结果")
        root.addWidget(self.tabs, 1)

        boundary = QGroupBox("Stage Output / 本阶段输出")
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.setContentsMargins(8, 8, 8, 8)
        text = QLabel(
            "输出 1：Composition Candidates / 候选材料表 → "
            "02_composition/composition_candidates.csv；"
            "输出 2：Screening Summary / 筛选统计 → "
            "02_composition/composition_summary.json。"
            "候选表将作为后续结构匹配的 candidates 输入。"
        )
        text.setWordWrap(True)
        text.setObjectName("optionHelp")
        boundary_layout.addWidget(text)
        root.addWidget(boundary)

        self.refresh_inputs()
        self.refresh_results()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _project_root(self) -> Path:
        return Path(self.project_provider()).expanduser().resolve()

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self._project_root()))
        except Exception:
            return str(path)

    def _resolve(self, text: str) -> Path:
        path = Path(text.strip()).expanduser()
        if not path.is_absolute():
            path = self._project_root() / path
        return path

    def _path_editor(
        self,
        default: str,
        *,
        save_file: bool = False,
    ) -> tuple[QWidget, QLineEdit]:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        edit = QLineEdit(default)
        button = QPushButton("…")
        button.setMaximumWidth(34)

        def browse() -> None:
            base = str(self._project_root())
            if save_file:
                value, _ = QFileDialog.getSaveFileName(
                    self,
                    "选择输出文件",
                    base,
                )
            else:
                value, _ = QFileDialog.getOpenFileName(
                    self,
                    "选择文件",
                    base,
                )
            if value:
                edit.setText(self._display_path(Path(value)))

        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return host, edit

    def _check_required(self, items: list[tuple[str, str]]) -> bool:
        missing = [name for name, value in items if not str(value).strip()]
        if not missing:
            return True
        QMessageBox.warning(
            self,
            "缺少必要输入",
            "请先填写：\n" + "\n".join(f"• {name}" for name in missing),
        )
        return False

    # ------------------------------------------------------------------
    # Setup / execution
    # ------------------------------------------------------------------

    def _build_setup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        input_box = QGroupBox("Input DataFrames / 输入规范化数据")
        input_layout = QVBoxLayout(input_box)
        input_layout.setContentsMargins(8, 10, 8, 8)

        self.df_table = QTableWidget(0, 2)
        self.df_table.setHorizontalHeaderLabels(["DataFrame", "状态"])
        self.df_table.verticalHeader().setVisible(False)
        self.df_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.df_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.df_table.horizontalHeader().setStretchLastSection(True)
        self.df_table.setColumnWidth(0, 560)
        self.df_table.setMinimumHeight(110)
        self.df_table.setMaximumHeight(165)
        input_layout.addWidget(self.df_table)

        df_actions = QHBoxLayout()
        add_df = QPushButton("＋ 添加 DataFrame")
        add_df.clicked.connect(self._add_dataframe)
        remove_df = QPushButton("移除所选")
        remove_df.clicked.connect(self._remove_dataframes)
        defaults_df = QPushButton("MP + WBM 默认")
        defaults_df.clicked.connect(self._reset_dataframes)
        check_df = QPushButton("检查输入")
        check_df.clicked.connect(self.refresh_inputs)
        df_actions.addWidget(add_df)
        df_actions.addWidget(remove_df)
        df_actions.addWidget(defaults_df)
        df_actions.addStretch(1)
        df_actions.addWidget(check_df)
        input_layout.addLayout(df_actions)

        valence_host = QWidget()
        valence_layout = QHBoxLayout(valence_host)
        valence_layout.setContentsMargins(0, 0, 0, 0)
        valence_layout.setSpacing(6)

        self.use_valence = QCheckBox("使用价态过滤结果（可选）")
        self.valence_edit = QLineEdit("02_composition/valid_ids.json")
        valence_browse = QPushButton("…")
        valence_browse.setMaximumWidth(34)

        def browse_valence() -> None:
            value, _ = QFileDialog.getOpenFileName(
                self,
                "选择 valid_ids.json",
                str(self._project_root()),
                "JSON (*.json);;All files (*)",
            )
            if value:
                self.valence_edit.setText(self._display_path(Path(value)))

        valence_browse.clicked.connect(browse_valence)
        self.use_valence.toggled.connect(self.valence_edit.setEnabled)
        self.use_valence.toggled.connect(valence_browse.setEnabled)
        valence_layout.addWidget(self.use_valence)
        valence_layout.addWidget(self.valence_edit, 1)
        valence_layout.addWidget(valence_browse)

        input_layout.addWidget(valence_host)
        layout.addWidget(input_box)

        rules_box = QGroupBox("Screening Rules / 筛选规则")
        rules = QFormLayout(rules_box)
        rules.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        rules.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rules.setHorizontalSpacing(12)
        rules.setVerticalSpacing(7)

        self.nelems_edit = QLineEdit("2")
        self.max_bandgap_edit = QLineEdit("1.0")
        self.max_e_hull_edit = QLineEdit("0.01")
        self.min_group_size_edit = QLineEdit("2")
        self.min_x_elements_edit = QLineEdit("2")

        for edit in (
            self.nelems_edit,
            self.max_bandgap_edit,
            self.max_e_hull_edit,
            self.min_group_size_edit,
            self.min_x_elements_edit,
        ):
            edit.setMaximumWidth(180)

        rules.addRow("元素数量", self.nelems_edit)
        rules.addRow("最大初筛带隙 (eV)", self.max_bandgap_edit)
        rules.addRow("最大凸包距离 (eV/atom)", self.max_e_hull_edit)
        rules.addRow("模板最少材料数", self.min_group_size_edit)
        rules.addRow("模板最少可替换元素数", self.min_x_elements_edit)

        rules_note = QLabel(
            "流程：合并规范化 DataFrame → 可选价态过滤 → 元素数筛选 → "
            "带隙/e_hull 筛选 → 按组成模板分组 → 检查组大小与 X 元素数量。"
        )
        rules_note.setWordWrap(True)
        rules_note.setObjectName("optionHelp")
        rules.addRow("", rules_note)
        layout.addWidget(rules_box)

        output_box = QGroupBox("Outputs / 输出")
        outputs = QFormLayout(output_box)
        outputs.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        outputs.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        outputs.setHorizontalSpacing(12)
        outputs.setVerticalSpacing(7)

        host, self.candidates_output = self._path_editor(
            "02_composition/composition_candidates.csv",
            save_file=True,
        )
        outputs.addRow("候选材料表", host)

        host, self.summary_output = self._path_editor(
            "02_composition/composition_summary.json",
            save_file=True,
        )
        outputs.addRow("筛选统计", host)
        layout.addWidget(output_box)

        preview_label = QLabel("Command Preview / 命令预览")
        preview_label.setObjectName("sectionLabel")
        layout.addWidget(preview_label)

        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(82)
        self.command_preview.setObjectName("commandPreview")
        layout.addWidget(self.command_preview)

        actions = QHBoxLayout()
        refresh_button = QPushButton("刷新参数")
        refresh_button.clicked.connect(self._refresh_preview)
        copy_button = QPushButton("复制命令")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.command_preview.toPlainText()
            )
        )
        run_button = QPushButton("开始组成模板筛选")
        run_button.setObjectName("primaryButton")
        run_button.clicked.connect(self._run_screen)

        actions.addWidget(refresh_button)
        actions.addStretch(1)
        actions.addWidget(copy_button)
        actions.addWidget(run_button)
        layout.addLayout(actions)
        layout.addStretch(1)

        # Defaults from the documented example.
        self._reset_dataframes(initial=True)

        for edit in (
            self.valence_edit,
            self.nelems_edit,
            self.max_bandgap_edit,
            self.max_e_hull_edit,
            self.min_group_size_edit,
            self.min_x_elements_edit,
            self.candidates_output,
            self.summary_output,
        ):
            edit.textChanged.connect(self._refresh_preview)
        self.use_valence.toggled.connect(self._refresh_preview)

        return _wrap_in_scroll_area(page, min_width=840, min_height=700)

    def _dataframe_paths(self) -> list[str]:
        values: list[str] = []
        for row in range(self.df_table.rowCount()):
            item = self.df_table.item(row, 0)
            if item is None:
                continue
            values.append(str(item.data(Qt.UserRole) or item.text()))
        return values

    def _append_dataframe(self, path: Path | str) -> None:
        raw = str(path)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            resolved = self._project_root() / candidate
            display = raw
        else:
            resolved = candidate
            display = self._display_path(candidate)

        canonical = str(resolved.resolve())
        if canonical in self._dataframe_paths():
            return

        row = self.df_table.rowCount()
        self.df_table.insertRow(row)

        item = QTableWidgetItem(display)
        item.setData(Qt.UserRole, canonical)
        self.df_table.setItem(row, 0, item)
        self.df_table.setItem(
            row,
            1,
            QTableWidgetItem("Ready" if resolved.exists() else "文件不存在"),
        )
        self._refresh_preview()

    def _reset_dataframes(
        self,
        checked: bool = False,
        initial: bool = False,
    ) -> None:
        self.df_table.setRowCount(0)
        self._append_dataframe("01_dataset/mp.df")
        self._append_dataframe("01_dataset/wbm.df")
        if not initial:
            self.refresh_inputs()

    def _add_dataframe(self) -> None:
        values, _ = QFileDialog.getOpenFileNames(
            self,
            "添加规范化材料 DataFrame",
            str(self._project_root() / "01_dataset"),
            "DataFrame files (*.df *.pkl *.pickle);;All files (*)",
        )
        for value in values:
            self._append_dataframe(Path(value))
        self.refresh_inputs()

    def _remove_dataframes(self) -> None:
        rows = sorted(
            {index.row() for index in self.df_table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self.df_table.removeRow(row)
        self._refresh_preview()

    def refresh_inputs(self) -> None:
        if not hasattr(self, "df_table"):
            return

        for row in range(self.df_table.rowCount()):
            item = self.df_table.item(row, 0)
            if item is None:
                continue
            raw = str(item.data(Qt.UserRole) or item.text())
            path = Path(raw)
            if not path.is_absolute():
                path = self._project_root() / path
            self.df_table.setItem(
                row,
                1,
                QTableWidgetItem("Ready" if path.exists() else "文件不存在"),
            )

        valence_path = self._resolve(self.valence_edit.text())
        # First opening: automatically enable valence filtering only if a
        # valid_ids.json already exists. Afterwards the checkbox is user-owned.
        if not hasattr(self, "_valence_initialized"):
            self.use_valence.setChecked(valence_path.exists())
            self._valence_initialized = True

        self.valence_edit.setEnabled(self.use_valence.isChecked())
        self._refresh_preview()

    def _screen_argv(self) -> list[str]:
        argv = ["composition-screen"]

        for raw in self._dataframe_paths():
            path = Path(raw)
            value = self._display_path(path) if path.is_absolute() else raw
            argv.extend(["--df", value])

        if self.use_valence.isChecked() and self.valence_edit.text().strip():
            argv.extend(["--valence-ids", self.valence_edit.text().strip()])

        argv.extend([
            "--nelems", self.nelems_edit.text().strip() or "2",
            "--max-bandgap", self.max_bandgap_edit.text().strip() or "1.0",
            "--max-e-hull", self.max_e_hull_edit.text().strip() or "0.01",
            "--min-group-size", self.min_group_size_edit.text().strip() or "2",
            "--min-x-elements", self.min_x_elements_edit.text().strip() or "2",
            "--output", self.candidates_output.text().strip(),
            "--summary", self.summary_output.text().strip(),
        ])
        return argv

    def _refresh_preview(self) -> None:
        if hasattr(self, "command_preview"):
            self.command_preview.setPlainText(
                shlex.join(["ss-screen", *self._screen_argv()])
            )

    def _run_screen(self) -> None:
        if not self._check_required([
            ("规范化 DataFrame", ", ".join(self._dataframe_paths())),
            ("候选材料表输出", self.candidates_output.text()),
            ("筛选统计输出", self.summary_output.text()),
        ]):
            return

        # Basic GUI-side type checks; final validation still belongs to Click.
        try:
            if int(self.nelems_edit.text().strip()) < 1:
                raise ValueError
            if int(self.min_group_size_edit.text().strip()) < 1:
                raise ValueError
            if int(self.min_x_elements_edit.text().strip()) < 1:
                raise ValueError
            if float(self.max_bandgap_edit.text().strip()) < 0:
                raise ValueError
            if float(self.max_e_hull_edit.text().strip()) < 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(
                self,
                "筛选参数错误",
                "元素数、组大小和 X 元素数量必须为正整数；"
                "带隙和凸包距离必须为非负数字。",
            )
            return

        self.run_requested.emit(
            self._screen_argv(),
            "组成模板筛选",
        )

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _build_results_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        files_box = QGroupBox("Result Files / 结果文件")
        files_form = QFormLayout(files_box)
        files_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.candidates_file_state = QLabel("未生成")
        self.summary_file_state = QLabel("未生成")
        files_form.addRow(
            "Composition Candidates",
            self.candidates_file_state,
        )
        files_form.addRow(
            "Screening Summary",
            self.summary_file_state,
        )
        layout.addWidget(files_box)

        summary_box = QGroupBox("Screening Summary / 筛选统计")
        summary_form = QFormLayout(summary_box)
        summary_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.input_rows_value = QLabel("—")
        self.selected_rows_value = QLabel("—")
        self.template_count_value = QLabel("—")
        self.candidate_rows_value = QLabel("—")

        summary_form.addRow("输入材料数", self.input_rows_value)
        summary_form.addRow("通过基础筛选", self.selected_rows_value)
        summary_form.addRow("组成模板数", self.template_count_value)
        summary_form.addRow("候选材料记录", self.candidate_rows_value)
        layout.addWidget(summary_box)

        condition_box = QGroupBox("Screening Conditions / 实际筛选条件")
        condition_form = QFormLayout(condition_box)
        condition_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.result_nelems = QLabel("—")
        self.result_max_bandgap = QLabel("—")
        self.result_max_e_hull = QLabel("—")
        self.result_min_group_size = QLabel("—")
        self.result_min_x_elements = QLabel("—")
        self.result_valence = QLabel("—")

        condition_form.addRow("元素数量", self.result_nelems)
        condition_form.addRow("最大初筛带隙", self.result_max_bandgap)
        condition_form.addRow("最大凸包距离", self.result_max_e_hull)
        condition_form.addRow("模板最少材料数", self.result_min_group_size)
        condition_form.addRow("模板最少 X 元素数", self.result_min_x_elements)
        condition_form.addRow("价态过滤", self.result_valence)
        layout.addWidget(condition_box)

        candidates_box = QGroupBox(
            "Composition Candidates / 候选材料表"
        )
        candidates_layout = QVBoxLayout(candidates_box)

        filter_row = QHBoxLayout()
        self.candidate_search = QLineEdit()
        self.candidate_search.setPlaceholderText(
            "搜索 Template / Material ID / Formula / Source ..."
        )
        self.template_filter = QComboBox()
        self.template_filter.addItem("全部模板")
        self.candidate_count_label = QLabel("0 条")

        self.candidate_search.textChanged.connect(
            self._apply_candidate_filter
        )
        self.template_filter.currentTextChanged.connect(
            self._apply_candidate_filter
        )

        filter_row.addWidget(QLabel("搜索"))
        filter_row.addWidget(self.candidate_search, 1)
        filter_row.addWidget(QLabel("Template"))
        filter_row.addWidget(self.template_filter)
        filter_row.addWidget(self.candidate_count_label)
        candidates_layout.addLayout(filter_row)

        self.candidates_table = QTableWidget(0, 0)
        self.candidates_table.verticalHeader().setVisible(False)
        self.candidates_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.candidates_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.candidates_table.setSortingEnabled(False)
        self.candidates_table.setMinimumHeight(275)
        candidates_layout.addWidget(self.candidates_table)
        layout.addWidget(candidates_box, 1)

        raw_summary_box = QGroupBox(
            "Summary JSON Fields / 原始统计字段"
        )
        raw_summary_layout = QVBoxLayout(raw_summary_box)
        self.summary_table = QTableWidget(0, 2)
        self.summary_table.setHorizontalHeaderLabels(["字段", "值"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setMaximumHeight(190)
        raw_summary_layout.addWidget(self.summary_table)
        layout.addWidget(raw_summary_box)

        actions = QHBoxLayout()
        refresh = QPushButton("刷新结果")
        refresh.clicked.connect(self.refresh_results)
        open_candidates = QPushButton("打开候选材料表")
        open_candidates.clicked.connect(self._open_candidates_file)
        open_summary = QPushButton("打开筛选统计")
        open_summary.clicked.connect(self._open_summary_file)

        actions.addWidget(refresh)
        actions.addWidget(open_candidates)
        actions.addWidget(open_summary)
        actions.addStretch(1)
        layout.addLayout(actions)

        return _wrap_in_scroll_area(page, min_width=900, min_height=930)

    def _load_summary(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load_candidates(
        self,
        path: Path,
    ) -> tuple[list[str], list[dict[str, str]]]:
        if not path.exists():
            return [], []

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
        return fields, rows

    def _find_field(
        self,
        fields: list[str],
        candidates: tuple[str, ...],
    ) -> str | None:
        lowered = {field.lower(): field for field in fields}
        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        return None

    def _display_header(self, field: str) -> str:
        aliases = {
            "template": "Template",
            "material_id": "Material ID",
            "mp_id": "Material ID",
            "formula": "Formula",
            "composition": "Composition",
            "x_element": "X Element",
            "band_gap": "Band Gap",
            "e_hull": "E Hull",
            "source": "Source",
        }
        return aliases.get(field.lower(), field)

    def refresh_results(self) -> None:
        if not hasattr(self, "candidates_table"):
            return

        candidate_path = self._resolve(
            self.candidates_output.text()
        )
        summary_path = self._resolve(
            self.summary_output.text()
        )

        self.candidates_file_state.setText(
            self._display_path(candidate_path)
            + (" · 已生成" if candidate_path.exists() else " · 未生成")
        )
        self.summary_file_state.setText(
            self._display_path(summary_path)
            + (" · 已生成" if summary_path.exists() else " · 未生成")
        )

        summary = self._load_summary(summary_path)

        try:
            fields, records = self._load_candidates(candidate_path)
        except Exception as exc:
            fields, records = [], []
            self.candidates_file_state.setText(
                f"{self._display_path(candidate_path)} · 读取失败：{exc}"
            )

        self._candidate_fields = fields
        self._candidate_records = records
        self._template_field = self._find_field(
            fields,
            ("template", "composition_template"),
        )

        # Core statistics: summary.json has priority; CSV-derived values are
        # used only when that exact statistic can be computed safely.
        template_values = set()
        if self._template_field:
            template_values = {
                str(row.get(self._template_field, "")).strip()
                for row in records
                if str(row.get(self._template_field, "")).strip()
            }

        input_rows = summary.get("input_rows", "—")
        selected_rows = summary.get("selected_rows", "—")
        template_count = summary.get(
            "template_count",
            len(template_values) if template_values else "—",
        )
        candidate_rows = summary.get(
            "candidate_rows",
            len(records) if candidate_path.exists() else "—",
        )

        self.input_rows_value.setText(str(input_rows))
        self.selected_rows_value.setText(str(selected_rows))
        self.template_count_value.setText(str(template_count))
        self.candidate_rows_value.setText(str(candidate_rows))

        # Show the actual recorded conditions when summary contains them;
        # otherwise show current GUI settings and mark no extra conclusions.
        self.result_nelems.setText(
            str(summary.get("nelems", self.nelems_edit.text()))
        )
        self.result_max_bandgap.setText(
            str(
                summary.get(
                    "max_bandgap",
                    self.max_bandgap_edit.text(),
                )
            )
            + " eV"
        )
        self.result_max_e_hull.setText(
            str(
                summary.get(
                    "max_e_hull",
                    self.max_e_hull_edit.text(),
                )
            )
            + " eV/atom"
        )
        self.result_min_group_size.setText(
            str(
                summary.get(
                    "min_group_size",
                    self.min_group_size_edit.text(),
                )
            )
        )
        self.result_min_x_elements.setText(
            str(
                summary.get(
                    "min_x_elements",
                    self.min_x_elements_edit.text(),
                )
            )
        )

        valence_path = self._resolve(self.valence_edit.text())
        if "valence_ids" in summary:
            self.result_valence.setText(str(summary["valence_ids"]))
        elif self.use_valence.isChecked():
            self.result_valence.setText(
                "使用：" + self._display_path(valence_path)
            )
        else:
            self.result_valence.setText("未使用")

        # Candidate table.
        self.candidates_table.setSortingEnabled(False)
        self.candidates_table.clear()
        self.candidates_table.setRowCount(len(records))
        self.candidates_table.setColumnCount(len(fields))
        self.candidates_table.setHorizontalHeaderLabels(
            [self._display_header(field) for field in fields]
        )

        for row_index, record in enumerate(records):
            for col_index, field in enumerate(fields):
                value = record.get(field, "")
                self.candidates_table.setItem(
                    row_index,
                    col_index,
                    QTableWidgetItem(str(value)),
                )

        if fields:
            self.candidates_table.horizontalHeader().setStretchLastSection(True)
        self.candidates_table.setSortingEnabled(True)

        # Template filter.
        current_template = self.template_filter.currentText()
        self.template_filter.blockSignals(True)
        self.template_filter.clear()
        self.template_filter.addItem("全部模板")
        for value in sorted(template_values):
            self.template_filter.addItem(value)
        index = self.template_filter.findText(current_template)
        self.template_filter.setCurrentIndex(index if index >= 0 else 0)
        self.template_filter.blockSignals(False)

        # Raw summary fields for auditability.
        self.summary_table.setRowCount(0)
        for key, value in summary.items():
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
            self.summary_table.setItem(
                row,
                0,
                QTableWidgetItem(str(key)),
            )
            if isinstance(value, (dict, list)):
                display = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            else:
                display = str(value)
            self.summary_table.setItem(
                row,
                1,
                QTableWidgetItem(display),
            )

        self._apply_candidate_filter()

    def _apply_candidate_filter(self) -> None:
        if not hasattr(self, "candidates_table"):
            return

        query = self.candidate_search.text().strip().lower()
        template = self.template_filter.currentText()
        visible = 0

        for row_index, record in enumerate(self._candidate_records):
            text_match = True
            if query:
                text_match = any(
                    query in str(value).lower()
                    for value in record.values()
                )

            template_match = True
            if (
                template != "全部模板"
                and self._template_field is not None
            ):
                template_match = (
                    str(record.get(self._template_field, "")).strip()
                    == template
                )

            show = text_match and template_match
            self.candidates_table.setRowHidden(
                row_index,
                not show,
            )
            if show:
                visible += 1

        total = len(self._candidate_records)
        if visible == total:
            self.candidate_count_label.setText(f"{total} 条")
        else:
            self.candidate_count_label.setText(
                f"{visible} / {total} 条"
            )

    def _open_candidates_file(self) -> None:
        path = self._resolve(self.candidates_output.text())
        if path.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))
            )
        else:
            QMessageBox.information(
                self,
                "结果未生成",
                f"候选材料表尚不存在：\n{path}",
            )

    def _open_summary_file(self) -> None:
        path = self._resolve(self.summary_output.text())
        if path.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))
            )
        else:
            QMessageBox.information(
                self,
                "结果未生成",
                f"筛选统计尚不存在：\n{path}",
            )

    def select_section(self, section: str) -> None:
        if section in {"input", "rules", "screen"}:
            self.tabs.setCurrentIndex(0)
            self.refresh_inputs()
        else:
            self.tabs.setCurrentIndex(1)
            self.refresh_results()



class StructureArchivePage(QWidget):
    """Engineering GUI for workflow Step 2: structure description archive."""

    run_requested = Signal(list, str)

    def __init__(self, project_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_provider = project_provider

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("结构描述归档")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        badge = QLabel("流程第 2 步")
        badge.setObjectName("stateBadge")
        header.addWidget(badge)
        root.addLayout(header)

        subtitle = QLabel(
            "通过 condense 调用 robocrys，将 pymatgen 晶体结构转换为机器可读取、可比较、"
            "可审计的局部环境描述，为后续结构匹配与材料分组提供统一结构表达。"
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageDescription")
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(500)
        self.tabs.addTab(self._build_dataframe_tab(), "从 DataFrame 批量生成")
        self.tabs.addTab(self._build_files_tab(), "从结构文件生成")
        self.tabs.addTab(self._build_archive_tab(), "归档 / 索引 / 校验")
        root.addWidget(self.tabs, 1)

        boundary = QGroupBox("Stage Boundary / 本阶段边界")
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.setContentsMargins(8, 8, 8, 8)
        text = QLabel(
            "只读取输入结构，不修改原始 DataFrame、CIF、POSCAR，也不改变元素种类、原子坐标或晶胞参数。"
            "本阶段输出仅用于比较局部结构环境，不单独证明材料能够形成固溶体，"
            "也不提供带隙、混合焓、声子或凸包稳定性结论。"
        )
        text.setWordWrap(True)
        text.setObjectName("optionHelp")
        boundary_layout.addWidget(text)
        root.addWidget(boundary)

        self.refresh_archive()
        self._refresh_df_preview()
        self._refresh_files_preview()

    # ---------- shared helpers ----------

    def _project_root(self) -> Path:
        return Path(self.project_provider()).expanduser().resolve()

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self._project_root()))
        except Exception:
            return str(path)

    def _resolve(self, value: str) -> Path:
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            path = self._project_root() / path
        return path

    def _path_editor(
        self,
        default: str,
        *,
        directory: bool = False,
        save_file: bool = False,
    ) -> tuple[QWidget, QLineEdit]:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        edit = QLineEdit(default)
        button = QPushButton("…")
        button.setMaximumWidth(34)

        def browse() -> None:
            base = str(self._project_root())
            if directory:
                value = QFileDialog.getExistingDirectory(self, "选择目录", base)
            elif save_file:
                value, _ = QFileDialog.getSaveFileName(self, "选择输出文件", base)
            else:
                value, _ = QFileDialog.getOpenFileName(self, "选择文件", base)
            if value:
                edit.setText(self._display_path(Path(value)))

        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return host, edit

    def _check_required(self, items: list[tuple[str, QLineEdit]]) -> bool:
        missing = [name for name, edit in items if not edit.text().strip()]
        if not missing:
            return True
        QMessageBox.warning(
            self,
            "缺少必要输入",
            "请先填写：\n" + "\n".join(f"• {name}" for name in missing),
        )
        return False

    # ---------- DataFrame mode ----------

    def _build_dataframe_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        intro = QLabel(
            "从规范化材料数据库批量读取晶体结构。默认使用 DataFrame index 作为材料 ID；"
            "若材料 ID 位于普通列，可启用“指定材料 ID 字段”。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("pageDescription")
        layout.addWidget(intro)

        input_box = QGroupBox("Input / 输入数据")
        form = QFormLayout(input_box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)

        host, self.df_path = self._path_editor("01_dataset/mp.df")
        form.addRow("DataFrame", host)

        self.structure_column = QLineEdit("structure")
        form.addRow("结构字段", self.structure_column)

        self.use_material_id = QCheckBox("指定材料 ID 字段")
        self.material_id_column = QLineEdit()
        self.material_id_column.setPlaceholderText("默认：使用 DataFrame index")
        self.material_id_column.setEnabled(False)
        self.use_material_id.toggled.connect(self.material_id_column.setEnabled)
        id_host = QWidget()
        id_layout = QHBoxLayout(id_host)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.addWidget(self.use_material_id)
        id_layout.addWidget(self.material_id_column, 1)
        form.addRow("材料 ID", id_host)
        layout.addWidget(input_box)

        output_box = QGroupBox("Archive / 归档输出")
        out_form = QFormLayout(output_box)
        out_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        out_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        out_form.setHorizontalSpacing(12)
        out_form.setVerticalSpacing(7)

        host, self.df_output_dir = self._path_editor("03_condensed/mp", directory=True)
        out_form.addRow("结构描述目录", host)
        host, self.df_manifest = self._path_editor("03_condensed/mp_manifest.jsonl", save_file=True)
        out_form.addRow("Manifest", host)
        host, self.df_index = self._path_editor("03_condensed/mp_index.csv", save_file=True)
        out_form.addRow("Index", host)
        layout.addWidget(output_box)

        settings_box = QGroupBox("Run Settings / 运行设置")
        settings = QFormLayout(settings_box)
        settings.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.df_limit = QLineEdit()
        self.df_limit.setPlaceholderText("留空 = 全量处理")
        self.df_limit.setMaximumWidth(180)
        settings.addRow("处理数量", self.df_limit)
        self.df_stop_on_error = QCheckBox("首个错误即停止；未勾选时保留失败记录并继续批处理")
        settings.addRow("错误策略", self.df_stop_on_error)
        layout.addWidget(settings_box)

        preview_label = QLabel("Command Preview / 命令预览")
        preview_label.setObjectName("sectionLabel")
        layout.addWidget(preview_label)
        self.df_preview = QPlainTextEdit()
        self.df_preview.setReadOnly(True)
        self.df_preview.setMaximumHeight(72)
        self.df_preview.setObjectName("commandPreview")
        layout.addWidget(self.df_preview)

        actions = QHBoxLayout()
        test_button = QPushButton("小批量测试（10 个结构）")
        test_button.clicked.connect(lambda: self._run_dataframe(test_limit=10))
        copy_button = QPushButton("复制命令")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.df_preview.toPlainText())
        )
        run_button = QPushButton("开始全量生成")
        run_button.setObjectName("primaryButton")
        run_button.clicked.connect(self._run_dataframe)
        actions.addWidget(test_button)
        actions.addStretch(1)
        actions.addWidget(copy_button)
        actions.addWidget(run_button)
        layout.addLayout(actions)
        layout.addStretch(1)

        for edit in (
            self.df_path,
            self.structure_column,
            self.material_id_column,
            self.df_output_dir,
            self.df_manifest,
            self.df_index,
            self.df_limit,
        ):
            edit.textChanged.connect(self._refresh_df_preview)
        self.use_material_id.toggled.connect(self._refresh_df_preview)
        self.df_stop_on_error.toggled.connect(self._refresh_df_preview)
        return _wrap_in_scroll_area(page, min_width=820, min_height=650)

    def _df_argv(self, override_limit: int | None = None) -> list[str]:
        argv = [
            "condense",
            "--df", self.df_path.text().strip(),
            "--structure-column", self.structure_column.text().strip() or "structure",
            "--output-dir", self.df_output_dir.text().strip(),
            "--manifest", self.df_manifest.text().strip(),
            "--index", self.df_index.text().strip(),
        ]
        if self.use_material_id.isChecked() and self.material_id_column.text().strip():
            argv.extend(["--material-id-column", self.material_id_column.text().strip()])
        limit = str(override_limit) if override_limit is not None else self.df_limit.text().strip()
        if limit:
            argv.extend(["--limit", limit])
        if self.df_stop_on_error.isChecked():
            argv.append("--stop-on-error")
        return argv

    def _refresh_df_preview(self) -> None:
        if hasattr(self, "df_preview"):
            self.df_preview.setPlainText(shlex.join(["ss-screen", *self._df_argv()]))

    def _run_dataframe(self, checked: bool = False, test_limit: int | None = None) -> None:
        if not self._check_required([
            ("DataFrame", self.df_path),
            ("结构描述目录", self.df_output_dir),
            ("Manifest", self.df_manifest),
            ("Index", self.df_index),
        ]):
            return
        argv = self._df_argv(override_limit=test_limit)
        title = "结构描述归档 · DataFrame"
        if test_limit is not None:
            title += f" · 小批量测试 {test_limit}"
        self.run_requested.emit(argv, title)

    # ---------- direct structure-file mode ----------

    def _build_files_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        intro = QLabel(
            "直接提供 CIF、POSCAR 或其他 pymatgen 可解析的晶体结构文件。"
            "软件使用文件名作为材料 ID，例如 example-a.cif → example-a.json。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("pageDescription")
        layout.addWidget(intro)

        input_box = QGroupBox("Structure Files / 输入结构")
        input_layout = QVBoxLayout(input_box)
        input_layout.setContentsMargins(6, 8, 6, 6)

        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(["文件", "类型", "Material ID", "状态"])
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.setColumnWidth(0, 390)
        self.file_table.setColumnWidth(1, 90)
        self.file_table.setColumnWidth(2, 150)
        self.file_table.setMinimumHeight(210)
        input_layout.addWidget(self.file_table)

        file_actions = QHBoxLayout()
        add_files = QPushButton("＋ 添加文件")
        add_files.clicked.connect(self._add_structure_files)
        add_folder = QPushButton("＋ 添加文件夹")
        add_folder.clicked.connect(self._add_structure_folder)
        remove = QPushButton("移除所选")
        remove.clicked.connect(self._remove_structure_files)
        clear = QPushButton("清空")
        clear.clicked.connect(self._clear_structure_files)
        file_actions.addWidget(add_files)
        file_actions.addWidget(add_folder)
        file_actions.addWidget(remove)
        file_actions.addWidget(clear)
        file_actions.addStretch(1)
        input_layout.addLayout(file_actions)
        layout.addWidget(input_box, 1)

        output_box = QGroupBox("Archive / 归档输出")
        out_form = QFormLayout(output_box)
        out_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        out_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        out_form.setHorizontalSpacing(12)
        out_form.setVerticalSpacing(7)

        host, self.files_output_dir = self._path_editor("03_condensed/user", directory=True)
        out_form.addRow("结构描述目录", host)
        host, self.files_manifest = self._path_editor("03_condensed/user_manifest.jsonl", save_file=True)
        out_form.addRow("Manifest", host)
        host, self.files_index = self._path_editor("03_condensed/user_index.csv", save_file=True)
        out_form.addRow("Index", host)
        self.files_stop_on_error = QCheckBox("首个错误即停止")
        out_form.addRow("错误策略", self.files_stop_on_error)
        layout.addWidget(output_box)

        preview_label = QLabel("Command Preview / 命令预览")
        preview_label.setObjectName("sectionLabel")
        layout.addWidget(preview_label)
        self.files_preview = QPlainTextEdit()
        self.files_preview.setReadOnly(True)
        self.files_preview.setMaximumHeight(72)
        self.files_preview.setObjectName("commandPreview")
        layout.addWidget(self.files_preview)

        actions = QHBoxLayout()
        copy_button = QPushButton("复制命令")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.files_preview.toPlainText())
        )
        run_button = QPushButton("生成结构描述")
        run_button.setObjectName("primaryButton")
        run_button.clicked.connect(self._run_files)
        actions.addStretch(1)
        actions.addWidget(copy_button)
        actions.addWidget(run_button)
        layout.addLayout(actions)

        for edit in (self.files_output_dir, self.files_manifest, self.files_index):
            edit.textChanged.connect(self._refresh_files_preview)
        self.files_stop_on_error.toggled.connect(self._refresh_files_preview)
        return _wrap_in_scroll_area(page, min_width=820, min_height=700)

    def _structure_file_rows(self) -> list[str]:
        values: list[str] = []
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, 0)
            if item is not None:
                values.append(str(item.data(Qt.UserRole) or item.text()))
        return values

    def _material_id_for_path(self, path: Path) -> str:
        upper = path.name.upper()
        if upper.startswith(("POSCAR", "CONTCAR")):
            return path.parent.name or path.name
        return path.stem

    def _file_type(self, path: Path) -> str:
        upper = path.name.upper()
        if upper.startswith("POSCAR"):
            return "POSCAR"
        if upper.startswith("CONTCAR"):
            return "CONTCAR"
        return path.suffix.lstrip(".").upper() or "STRUCTURE"

    def _append_structure_file(self, path: Path) -> None:
        canonical = str(path.resolve())
        existing = set(self._structure_file_rows())
        if canonical in existing:
            return

        row = self.file_table.rowCount()
        self.file_table.insertRow(row)

        item = QTableWidgetItem(self._display_path(path))
        item.setData(Qt.UserRole, canonical)
        self.file_table.setItem(row, 0, item)
        self.file_table.setItem(row, 1, QTableWidgetItem(self._file_type(path)))
        self.file_table.setItem(row, 2, QTableWidgetItem(self._material_id_for_path(path)))
        self.file_table.setItem(row, 3, QTableWidgetItem("Ready"))
        self._refresh_files_preview()

    def _add_structure_files(self) -> None:
        values, _ = QFileDialog.getOpenFileNames(
            self,
            "选择晶体结构文件",
            str(self._project_root()),
            "Structure files (*.cif *.vasp *.poscar *.json);;All files (*)",
        )
        for value in values:
            self._append_structure_file(Path(value))

    def _add_structure_folder(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self,
            "选择结构文件目录",
            str(self._project_root()),
        )
        if not value:
            return

        folder = Path(value)
        supported = {".cif", ".vasp", ".poscar", ".json"}
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() in supported or path.name.upper().startswith(("POSCAR", "CONTCAR")):
                self._append_structure_file(path)

    def _remove_structure_files(self) -> None:
        rows = sorted(
            {index.row() for index in self.file_table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self.file_table.removeRow(row)
        self._refresh_files_preview()

    def _clear_structure_files(self) -> None:
        self.file_table.setRowCount(0)
        self._refresh_files_preview()

    def _files_argv(self) -> list[str]:
        argv = ["condense"]
        for value in self._structure_file_rows():
            argv.extend(["--input", value])
        argv.extend([
            "--output-dir", self.files_output_dir.text().strip(),
            "--manifest", self.files_manifest.text().strip(),
            "--index", self.files_index.text().strip(),
        ])
        if self.files_stop_on_error.isChecked():
            argv.append("--stop-on-error")
        return argv

    def _refresh_files_preview(self) -> None:
        if hasattr(self, "files_preview"):
            self.files_preview.setPlainText(shlex.join(["ss-screen", *self._files_argv()]))

    def _run_files(self) -> None:
        if not self._structure_file_rows():
            QMessageBox.warning(
                self,
                "没有结构文件",
                "请先添加至少一个 CIF、POSCAR 或其他晶体结构文件。",
            )
            return
        if not self._check_required([
            ("结构描述目录", self.files_output_dir),
            ("Manifest", self.files_manifest),
            ("Index", self.files_index),
        ]):
            return
        self.run_requested.emit(self._files_argv(), "结构描述归档 · 结构文件")

    # ---------- archive / index / validation ----------

    def _build_archive_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        summary_box = QGroupBox("Archive Status / 归档状态")
        summary = QFormLayout(summary_box)
        summary.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.archive_count = QLabel("0")
        self.manifest_state = QLabel("未生成")
        self.index_state = QLabel("未生成")
        self.validation_state = QLabel("未执行")
        summary.addRow("结构描述数量", self.archive_count)
        summary.addRow("Manifest", self.manifest_state)
        summary.addRow("Index", self.index_state)
        summary.addRow("Validation", self.validation_state)
        layout.addWidget(summary_box)

        archive_box = QGroupBox("Structure Description Archive / 结构描述库")
        archive_layout = QVBoxLayout(archive_box)
        self.archive_table = QTableWidget(0, 4)
        self.archive_table.setHorizontalHeaderLabels(["Material ID", "来源", "JSON", "状态"])
        self.archive_table.verticalHeader().setVisible(False)
        self.archive_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.archive_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_table.horizontalHeader().setStretchLastSection(True)
        self.archive_table.setColumnWidth(0, 180)
        self.archive_table.setColumnWidth(1, 100)
        self.archive_table.setColumnWidth(2, 420)
        self.archive_table.setMinimumHeight(230)
        archive_layout.addWidget(self.archive_table)
        layout.addWidget(archive_box, 1)

        tools_box = QGroupBox("Archive Tools / 归档工具")
        tools = QFormLayout(tools_box)
        tools.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        tools.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        host, self.archive_dir_edit = self._path_editor("03_condensed/mp", directory=True)
        tools.addRow("归档目录", host)
        host, self.archive_index_output = self._path_editor("03_condensed/mp_index.csv", save_file=True)
        tools.addRow("索引输出", host)
        host, self.archive_validation_output = self._path_editor("03_condensed/validation.csv", save_file=True)
        tools.addRow("校验输出", host)
        layout.addWidget(tools_box)

        actions = QHBoxLayout()
        refresh = QPushButton("刷新归档")
        refresh.clicked.connect(self.refresh_archive)
        open_dir = QPushButton("打开归档目录")
        open_dir.clicked.connect(self._open_archive_dir)
        rebuild = QPushButton("建立 / 重建 Index")
        rebuild.clicked.connect(self._run_index)
        validate = QPushButton("校验归档")
        validate.setObjectName("primaryButton")
        validate.clicked.connect(self._run_validation)
        actions.addWidget(refresh)
        actions.addWidget(open_dir)
        actions.addStretch(1)
        actions.addWidget(rebuild)
        actions.addWidget(validate)
        layout.addLayout(actions)
        return _wrap_in_scroll_area(page, min_width=820, min_height=660)

    def _find_archive_json(self) -> list[tuple[str, Path]]:
        base = self._project_root() / "03_condensed"
        result: list[tuple[str, Path]] = []
        for source in ("mp", "user"):
            folder = base / source
            if not folder.exists():
                continue
            for path in sorted(folder.glob("*.json")):
                result.append((source.upper(), path))
        return result

    def refresh_archive(self) -> None:
        if not hasattr(self, "archive_table"):
            return

        items = self._find_archive_json()
        self.archive_table.setRowCount(0)
        for source, path in items:
            row = self.archive_table.rowCount()
            self.archive_table.insertRow(row)
            self.archive_table.setItem(row, 0, QTableWidgetItem(path.stem))
            self.archive_table.setItem(row, 1, QTableWidgetItem(source))
            self.archive_table.setItem(row, 2, QTableWidgetItem(self._display_path(path)))
            self.archive_table.setItem(row, 3, QTableWidgetItem("OK"))
        self.archive_count.setText(str(len(items)))

        base = self._project_root() / "03_condensed"
        manifests = list(base.glob("*manifest*.jsonl")) if base.exists() else []
        indexes = list(base.glob("*index*.csv")) if base.exists() else []
        validations = list(base.glob("*validation*.csv")) if base.exists() else []

        self.manifest_state.setText(
            "未生成" if not manifests else "已生成：" + ", ".join(path.name for path in manifests)
        )
        self.index_state.setText(
            "未生成" if not indexes else "已生成：" + ", ".join(path.name for path in indexes)
        )
        self.validation_state.setText(
            "未执行" if not validations else "已生成：" + ", ".join(path.name for path in validations)
        )

    def select_section(self, section: str) -> None:
        if section in {"input", "dataframe"}:
            self.tabs.setCurrentIndex(0)
        elif section == "files":
            self.tabs.setCurrentIndex(1)
        else:
            self.tabs.setCurrentIndex(2)
        self.refresh_archive()

    def _open_archive_dir(self) -> None:
        path = self._resolve(self.archive_dir_edit.text())
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "目录不存在", f"归档目录尚不存在：\n{path}")

    def _run_index(self) -> None:
        if not self._check_required([
            ("归档目录", self.archive_dir_edit),
            ("索引输出", self.archive_index_output),
        ]):
            return
        argv = [
            "condense-index",
            "--condensed-dir", self.archive_dir_edit.text().strip(),
            "--output", self.archive_index_output.text().strip(),
        ]
        self.run_requested.emit(argv, "结构描述归档 · 建立索引")

    def _run_validation(self) -> None:
        if not self._check_required([
            ("归档目录", self.archive_dir_edit),
            ("校验输出", self.archive_validation_output),
        ]):
            return
        argv = [
            "condense-validate",
            "--condensed-dir", self.archive_dir_edit.text().strip(),
            "--output", self.archive_validation_output.text().strip(),
        ]
        self.run_requested.emit(argv, "结构描述归档 · 校验")




class StructureMatchPage(QWidget):
    """Engineering GUI for workflow Step 3: structure matching and grouping.

    The page treats the structure group as a persistent engineering object.
    ``structure-match`` is an operation performed on the candidate table and
    one or more validated robocrys description archives.
    """

    run_requested = Signal(list, str)

    def __init__(self, project_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_provider = project_provider
        self._last_group_records: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("结构匹配与材料分组")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        badge = QLabel("流程第 3 步")
        badge.setObjectName("stateBadge")
        header.addWidget(badge)
        root.addLayout(header)

        subtitle = QLabel(
            "以上一步通过校验的 robocrys 结构描述归档为结构证据，以组成候选表为筛选范围，"
            "将可变元素重标记为占位符 X 后比较局部环境，并把结构原型相近的材料组织为 Structure Groups。"
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageDescription")
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(520)
        self.tabs.addTab(self._build_match_tab(), "匹配设置与执行")
        self.tabs.addTab(self._build_results_tab(), "Structure Groups / 结构组结果")
        root.addWidget(self.tabs, 1)

        boundary = QGroupBox("Algorithm Boundary / 算法边界")
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.setContentsMargins(8, 8, 8, 8)
        note = QLabel(
            "匹配依据是组成模板和 robocrys 局部结构环境，包括配位数、几何类型和连接关系等表达。"
            "软件不会仅凭化学式或空间群判断结构相同；结构环境相似也不等同于已经证明能够形成固溶体。"
            "热力学和动力学稳定性仍需后续混合焓、声子和凸包等证据。"
        )
        note.setWordWrap(True)
        note.setObjectName("optionHelp")
        boundary_layout.addWidget(note)
        root.addWidget(boundary)

        self.refresh_inputs()
        self.refresh_results()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _project_root(self) -> Path:
        return Path(self.project_provider()).expanduser().resolve()

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self._project_root()))
        except Exception:
            return str(path)

    def _resolve(self, text: str) -> Path:
        path = Path(text.strip()).expanduser()
        if not path.is_absolute():
            path = self._project_root() / path
        return path

    def _path_editor(
        self,
        default: str,
        *,
        directory: bool = False,
        save_file: bool = False,
    ) -> tuple[QWidget, QLineEdit]:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        edit = QLineEdit(default)
        button = QPushButton("…")
        button.setMaximumWidth(34)

        def browse() -> None:
            base = str(self._project_root())
            if directory:
                value = QFileDialog.getExistingDirectory(self, "选择目录", base)
            elif save_file:
                value, _ = QFileDialog.getSaveFileName(self, "选择输出文件", base)
            else:
                value, _ = QFileDialog.getOpenFileName(self, "选择文件", base)
            if value:
                edit.setText(self._display_path(Path(value)))

        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return host, edit

    def _check_required(self, items: list[tuple[str, str]]) -> bool:
        missing = [name for name, value in items if not str(value).strip()]
        if not missing:
            return True
        QMessageBox.warning(
            self,
            "缺少必要输入",
            "请先填写：\n" + "\n".join(f"• {name}" for name in missing),
        )
        return False

    # ------------------------------------------------------------------
    # Match setup tab
    # ------------------------------------------------------------------

    def _build_match_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        # Inputs
        input_box = QGroupBox("Match Inputs / 匹配输入")
        input_layout = QVBoxLayout(input_box)
        input_layout.setContentsMargins(8, 10, 8, 8)

        candidate_form = QFormLayout()
        candidate_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        candidate_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        candidate_form.setHorizontalSpacing(12)
        candidate_form.setVerticalSpacing(7)

        host, self.candidates_edit = self._path_editor(
            "02_composition/composition_candidates.csv"
        )
        candidate_form.addRow("组成候选表", host)

        candidate_status_host = QWidget()
        candidate_status_layout = QHBoxLayout(candidate_status_host)
        candidate_status_layout.setContentsMargins(0, 0, 0, 0)
        candidate_status_layout.setSpacing(12)
        self.candidate_rows_label = QLabel("记录：—")
        self.template_count_label = QLabel("组成模板：—")
        self.candidate_input_state = QLabel("未检查")
        candidate_status_layout.addWidget(self.candidate_rows_label)
        candidate_status_layout.addWidget(self.template_count_label)
        candidate_status_layout.addWidget(self.candidate_input_state)
        candidate_status_layout.addStretch(1)
        candidate_form.addRow("候选状态", candidate_status_host)

        input_layout.addLayout(candidate_form)

        archive_label = QLabel("结构描述归档（可添加多个，运行时重复传递 --condensed-dir）")
        archive_label.setObjectName("sectionLabel")
        input_layout.addWidget(archive_label)

        self.archive_table = QTableWidget(0, 4)
        self.archive_table.setHorizontalHeaderLabels(
            ["归档目录", "JSON 数量", "Validation", "状态"]
        )
        self.archive_table.verticalHeader().setVisible(False)
        self.archive_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.archive_table.horizontalHeader().setStretchLastSection(True)
        self.archive_table.setColumnWidth(0, 430)
        self.archive_table.setColumnWidth(1, 85)
        self.archive_table.setColumnWidth(2, 120)
        self.archive_table.setMinimumHeight(135)
        self.archive_table.setMaximumHeight(190)
        input_layout.addWidget(self.archive_table)

        archive_actions = QHBoxLayout()
        add_archive = QPushButton("＋ 添加描述归档")
        add_archive.clicked.connect(self._add_archive)
        remove_archive = QPushButton("移除所选")
        remove_archive.clicked.connect(self._remove_archives)
        reset_archives = QPushButton("恢复默认")
        reset_archives.clicked.connect(self._reset_archives)
        check_inputs = QPushButton("检查输入")
        check_inputs.clicked.connect(self.refresh_inputs)
        archive_actions.addWidget(add_archive)
        archive_actions.addWidget(remove_archive)
        archive_actions.addWidget(reset_archives)
        archive_actions.addStretch(1)
        archive_actions.addWidget(check_inputs)
        input_layout.addLayout(archive_actions)

        layout.addWidget(input_box)

        # Algorithm rules are deliberately read-only except min-x-elements,
        # because the current CLI does not expose separate switches for each
        # environment feature.
        rule_box = QGroupBox("Matching Rules / 匹配规则")
        rule_form = QFormLayout(rule_box)
        rule_form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        rule_form.setHorizontalSpacing(12)
        rule_form.setVerticalSpacing(7)

        self.min_x_edit = QLineEdit("2")
        self.min_x_edit.setMaximumWidth(100)
        rule_form.addRow("最少可替换元素数", self.min_x_edit)

        x_flow = QLabel(
            "组成模板 → 识别可变元素位点 → 可变元素重标记为 X → 比较 robocrys 局部环境 → Structure Group"
        )
        x_flow.setWordWrap(True)
        rule_form.addRow("X 占位符处理", x_flow)

        basis = QLabel(
            "配位数 · 配位几何 · 最近邻/多面体表达 · 组分连接关系"
        )
        basis.setWordWrap(True)
        rule_form.addRow("环境匹配依据", basis)

        limitation = QLabel(
            "这些匹配依据由当前算法固定使用，并非可独立开关的 CLI 参数。"
        )
        limitation.setWordWrap(True)
        limitation.setObjectName("optionHelp")
        rule_form.addRow("", limitation)

        layout.addWidget(rule_box)

        # Outputs
        output_box = QGroupBox("Outputs / 输出")
        output_form = QFormLayout(output_box)
        output_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        output_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        output_form.setHorizontalSpacing(12)
        output_form.setVerticalSpacing(7)

        host, self.groups_output = self._path_editor(
            "04_groups/groups.json",
            save_file=True,
        )
        output_form.addRow("Structure Groups", host)

        host, self.summary_output = self._path_editor(
            "04_groups/structure_match_summary.json",
            save_file=True,
        )
        output_form.addRow("阶段汇总", host)

        layout.addWidget(output_box)

        # Preview
        preview_label = QLabel("Command Preview / 命令预览")
        preview_label.setObjectName("sectionLabel")
        layout.addWidget(preview_label)

        self.match_preview = QPlainTextEdit()
        self.match_preview.setReadOnly(True)
        self.match_preview.setMaximumHeight(76)
        self.match_preview.setObjectName("commandPreview")
        layout.addWidget(self.match_preview)

        actions = QHBoxLayout()
        copy_button = QPushButton("复制命令")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.match_preview.toPlainText()
            )
        )
        refresh_button = QPushButton("刷新参数")
        refresh_button.clicked.connect(self._refresh_preview)
        run_button = QPushButton("开始结构匹配")
        run_button.setObjectName("primaryButton")
        run_button.clicked.connect(self._run_match)

        actions.addWidget(refresh_button)
        actions.addStretch(1)
        actions.addWidget(copy_button)
        actions.addWidget(run_button)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.candidates_edit.textChanged.connect(self._refresh_preview)
        self.min_x_edit.textChanged.connect(self._refresh_preview)
        self.groups_output.textChanged.connect(self._refresh_preview)
        self.summary_output.textChanged.connect(self._refresh_preview)

        self._reset_archives(initial=True)
        return _wrap_in_scroll_area(page, min_width=820, min_height=760)

    def _archive_paths(self) -> list[str]:
        values: list[str] = []
        for row in range(self.archive_table.rowCount()):
            item = self.archive_table.item(row, 0)
            if item is None:
                continue
            values.append(str(item.data(Qt.UserRole) or item.text()))
        return values

    def _append_archive(self, path: Path) -> None:
        canonical = str(path.resolve())
        if canonical in self._archive_paths():
            return

        row = self.archive_table.rowCount()
        self.archive_table.insertRow(row)

        item = QTableWidgetItem(self._display_path(path))
        item.setData(Qt.UserRole, canonical)
        self.archive_table.setItem(row, 0, item)
        self.archive_table.setItem(row, 1, QTableWidgetItem("—"))
        self.archive_table.setItem(row, 2, QTableWidgetItem("—"))
        self.archive_table.setItem(row, 3, QTableWidgetItem("未检查"))
        self._refresh_preview()

    def _reset_archives(self, checked: bool = False, initial: bool = False) -> None:
        self.archive_table.setRowCount(0)
        default = self._project_root() / "03_condensed" / "mp"
        self._append_archive(default)
        if not initial:
            self.refresh_inputs()

    def _add_archive(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self,
            "添加 robocrys 结构描述归档",
            str(self._project_root() / "03_condensed"),
        )
        if value:
            self._append_archive(Path(value))
            self.refresh_inputs()

    def _remove_archives(self) -> None:
        rows = sorted(
            {index.row() for index in self.archive_table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self.archive_table.removeRow(row)
        self._refresh_preview()

    def _candidate_stats(self, path: Path) -> tuple[int, int]:
        if not path.exists():
            return 0, 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            templates = {
                str(row.get("template", "")).strip()
                for row in rows
                if str(row.get("template", "")).strip()
            }
            return len(rows), len(templates)
        except Exception:
            return 0, 0

    def _validation_state_for_archive(self, archive: Path) -> str:
        parent = archive.parent
        candidates = [
            parent / "validation.csv",
            parent / f"{archive.name}_validation.csv",
        ]
        for path in candidates:
            if path.exists():
                return path.name
        return "未发现"

    def refresh_inputs(self) -> None:
        if not hasattr(self, "archive_table"):
            return

        candidate_path = self._resolve(self.candidates_edit.text())
        rows, templates = self._candidate_stats(candidate_path)
        self.candidate_rows_label.setText(f"记录：{rows if candidate_path.exists() else '—'}")
        self.template_count_label.setText(
            f"组成模板：{templates if candidate_path.exists() else '—'}"
        )
        self.candidate_input_state.setText(
            "Ready" if candidate_path.exists() else "文件不存在"
        )

        for row in range(self.archive_table.rowCount()):
            item = self.archive_table.item(row, 0)
            if item is None:
                continue
            raw = str(item.data(Qt.UserRole) or item.text())
            archive = Path(raw)
            if not archive.is_absolute():
                archive = self._project_root() / archive

            if archive.exists() and archive.is_dir():
                json_count = len(list(archive.glob("*.json")))
                validation = self._validation_state_for_archive(archive)
                state = "Ready" if json_count else "目录为空"
            else:
                json_count = 0
                validation = "—"
                state = "目录不存在"

            self.archive_table.setItem(row, 1, QTableWidgetItem(str(json_count)))
            self.archive_table.setItem(row, 2, QTableWidgetItem(validation))
            self.archive_table.setItem(row, 3, QTableWidgetItem(state))

        self._refresh_preview()

    def _match_argv(self) -> list[str]:
        argv = [
            "structure-match",
            "--candidates", self.candidates_edit.text().strip(),
        ]

        for archive in self._archive_paths():
            display = archive
            try:
                display = self._display_path(Path(archive))
            except Exception:
                pass
            argv.extend(["--condensed-dir", display])

        argv.extend([
            "--min-x-elements", self.min_x_edit.text().strip() or "2",
            "--output", self.groups_output.text().strip(),
            "--summary", self.summary_output.text().strip(),
        ])
        return argv

    def _refresh_preview(self) -> None:
        if hasattr(self, "match_preview"):
            self.match_preview.setPlainText(
                shlex.join(["ss-screen", *self._match_argv()])
            )

    def _run_match(self) -> None:
        if not self._check_required([
            ("组成候选表", self.candidates_edit.text()),
            ("结构描述归档", ", ".join(self._archive_paths())),
            ("Structure Groups 输出", self.groups_output.text()),
            ("阶段汇总", self.summary_output.text()),
        ]):
            return

        try:
            min_x = int(self.min_x_edit.text().strip())
            if min_x < 1:
                raise ValueError
        except ValueError:
            QMessageBox.warning(
                self,
                "参数错误",
                "“最少可替换元素数”必须是大于等于 1 的整数。",
            )
            return

        self.run_requested.emit(
            self._match_argv(),
            "结构匹配与材料分组",
        )

    # ------------------------------------------------------------------
    # Results tab
    # ------------------------------------------------------------------

    def _build_results_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        summary_box = QGroupBox("Match Summary / 匹配汇总")
        summary_grid = QFormLayout(summary_box)
        summary_grid.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.result_candidate_rows = QLabel("—")
        self.result_template_count = QLabel("—")
        self.result_group_count = QLabel("0")
        self.result_grouped_members = QLabel("0")
        self.result_missing = QLabel("—")
        self.result_invalid = QLabel("—")
        self.result_min_x = QLabel("—")

        summary_grid.addRow("候选记录", self.result_candidate_rows)
        summary_grid.addRow("组成模板", self.result_template_count)
        summary_grid.addRow("Structure Groups", self.result_group_count)
        summary_grid.addRow("组内材料总数", self.result_grouped_members)
        summary_grid.addRow("缺失结构描述", self.result_missing)
        summary_grid.addRow("无效结构描述", self.result_invalid)
        summary_grid.addRow("min X elements", self.result_min_x)
        layout.addWidget(summary_box)

        groups_box = QGroupBox("Structure Groups / 结构组")
        groups_layout = QVBoxLayout(groups_box)

        self.groups_table = QTableWidget(0, 6)
        self.groups_table.setHorizontalHeaderLabels(
            [
                "Group",
                "Members",
                "Compositions",
                "X Elements",
                "Material IDs",
                "Band Gaps",
            ]
        )
        self.groups_table.verticalHeader().setVisible(False)
        self.groups_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.groups_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.groups_table.horizontalHeader().setStretchLastSection(True)
        self.groups_table.setColumnWidth(0, 90)
        self.groups_table.setColumnWidth(1, 75)
        self.groups_table.setColumnWidth(2, 220)
        self.groups_table.setColumnWidth(3, 145)
        self.groups_table.setColumnWidth(4, 270)
        self.groups_table.setMinimumHeight(245)
        self.groups_table.itemSelectionChanged.connect(
            self._refresh_group_detail
        )
        groups_layout.addWidget(self.groups_table)
        layout.addWidget(groups_box, 1)

        detail_box = QGroupBox("Selected Group / 组内成员")
        detail_layout = QVBoxLayout(detail_box)

        self.group_detail_title = QLabel("未选择结构组")
        self.group_detail_title.setObjectName("sectionLabel")
        detail_layout.addWidget(self.group_detail_title)

        self.member_table = QTableWidget(0, 5)
        self.member_table.setHorizontalHeaderLabels(
            ["#", "Composition", "X Element", "Material ID", "Band Gap"]
        )
        self.member_table.verticalHeader().setVisible(False)
        self.member_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.member_table.horizontalHeader().setStretchLastSection(True)
        self.member_table.setMinimumHeight(125)
        self.member_table.setMaximumHeight(190)
        detail_layout.addWidget(self.member_table)

        self.group_algorithm_note = QLabel(
            "Material ID 可能来自不同数据源；GUI 不依据历史字段名 mp_ids 推断其全部来自 Materials Project。"
        )
        self.group_algorithm_note.setWordWrap(True)
        self.group_algorithm_note.setObjectName("optionHelp")
        detail_layout.addWidget(self.group_algorithm_note)

        layout.addWidget(detail_box)

        actions = QHBoxLayout()
        refresh = QPushButton("刷新结果")
        refresh.clicked.connect(self.refresh_results)
        open_groups = QPushButton("打开 groups.json")
        open_groups.clicked.connect(self._open_groups_file)
        open_summary = QPushButton("打开 summary.json")
        open_summary.clicked.connect(self._open_summary_file)
        actions.addWidget(refresh)
        actions.addWidget(open_groups)
        actions.addWidget(open_summary)
        actions.addStretch(1)
        layout.addLayout(actions)

        return _wrap_in_scroll_area(page, min_width=820, min_height=760)

    def _load_group_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]

        # Support the column-oriented DataFrame JSON layout accepted by the
        # real SS-Screen loader.
        if isinstance(data, dict) and "entry_idx" in data:
            columns = {
                key: value for key, value in data.items()
                if isinstance(value, dict)
            }
            row_keys: list[str] = []
            seen: set[str] = set()
            for values in columns.values():
                for key in values:
                    key_text = str(key)
                    if key_text not in seen:
                        seen.add(key_text)
                        row_keys.append(key_text)

            def sort_key(value: str):
                try:
                    return (0, int(value))
                except ValueError:
                    return (1, value)

            records: list[dict[str, Any]] = []
            for row_key in sorted(row_keys, key=sort_key):
                record = {}
                for column, values in columns.items():
                    if row_key in values:
                        record[column] = values[row_key]
                    elif str(row_key) in values:
                        record[column] = values[str(row_key)]
                records.append(record)
            return records

        return []

    def _load_summary(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _compact_list(self, value: Any, limit: int = 5) -> str:
        if value is None:
            return ""
        if not isinstance(value, (list, tuple)):
            return str(value)
        parts = [str(item) for item in value]
        if len(parts) <= limit:
            return ", ".join(parts)
        return ", ".join(parts[:limit]) + f" … (+{len(parts) - limit})"

    def refresh_results(self) -> None:
        if not hasattr(self, "groups_table"):
            return

        groups_path = self._resolve(self.groups_output.text())
        summary_path = self._resolve(self.summary_output.text())

        try:
            records = self._load_group_records(groups_path)
        except Exception as exc:
            records = []
            self.result_group_count.setText(f"读取失败：{exc}")
        self._last_group_records = records

        summary = self._load_summary(summary_path)

        self.result_candidate_rows.setText(str(summary.get("candidate_rows", "—")))
        self.result_template_count.setText(str(summary.get("template_count", "—")))
        self.result_group_count.setText(
            str(summary.get("group_count", len(records)))
        )
        self.result_grouped_members.setText(
            str(
                summary.get(
                    "grouped_members",
                    sum(int(row.get("group_size", 0) or 0) for row in records),
                )
            )
        )
        self.result_missing.setText(
            str(summary.get("missing_descriptions", "—"))
        )
        self.result_invalid.setText(
            str(summary.get("invalid_descriptions", "—"))
        )
        self.result_min_x.setText(str(summary.get("min_x_elements", "—")))

        self.groups_table.setRowCount(0)
        for index, record in enumerate(records):
            row = self.groups_table.rowCount()
            self.groups_table.insertRow(row)

            group_id = f"G{index + 1:04d}"
            group_size = record.get(
                "group_size",
                len(record.get("mp_ids", []) or []),
            )

            values = [
                group_id,
                str(group_size),
                self._compact_list(record.get("compositions", [])),
                self._compact_list(record.get("X_element", [])),
                self._compact_list(record.get("mp_ids", [])),
                self._compact_list(record.get("band_gaps", [])),
            ]
            for col, value in enumerate(values):
                self.groups_table.setItem(row, col, QTableWidgetItem(value))

        if records:
            self.groups_table.selectRow(0)
        else:
            self.member_table.setRowCount(0)
            self.group_detail_title.setText("未生成结构组")

    def _refresh_group_detail(self) -> None:
        rows = self.groups_table.selectionModel().selectedRows()
        if not rows:
            return

        row_index = rows[0].row()
        if row_index >= len(self._last_group_records):
            return

        record = self._last_group_records[row_index]
        group_id = f"G{row_index + 1:04d}"
        compositions = list(record.get("compositions", []) or [])
        x_elements = list(record.get("X_element", []) or [])
        material_ids = list(record.get("mp_ids", []) or [])
        band_gaps = list(record.get("band_gaps", []) or [])

        member_count = max(
            len(compositions),
            len(x_elements),
            len(material_ids),
            len(band_gaps),
            int(record.get("group_size", 0) or 0),
        )

        self.group_detail_title.setText(
            f"{group_id} · {member_count} members · "
            f"A elements: {self._compact_list(record.get('A_elements', []))}"
        )

        self.member_table.setRowCount(member_count)
        for i in range(member_count):
            values = [
                str(i + 1),
                str(compositions[i]) if i < len(compositions) else "",
                str(x_elements[i]) if i < len(x_elements) else "",
                str(material_ids[i]) if i < len(material_ids) else "",
                str(band_gaps[i]) if i < len(band_gaps) else "",
            ]
            for col, value in enumerate(values):
                self.member_table.setItem(
                    i,
                    col,
                    QTableWidgetItem(value),
                )

    def _open_groups_file(self) -> None:
        path = self._resolve(self.groups_output.text())
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(
                self,
                "结果不存在",
                f"尚未生成结构组文件：\n{path}",
            )

    def _open_summary_file(self) -> None:
        path = self._resolve(self.summary_output.text())
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(
                self,
                "结果不存在",
                f"尚未生成阶段汇总：\n{path}",
            )

    def select_section(self, section: str) -> None:
        if section in {"input", "rules", "match"}:
            self.tabs.setCurrentIndex(0)
            self.refresh_inputs()
        else:
            self.tabs.setCurrentIndex(1)
            self.refresh_results()



@dataclass
class ProjectRecord:
    """One project shown as a top-level root in the project explorer."""

    name: str
    path: Path


# Engineering-style logical groups. Stage numbering remains unchanged so it
# still maps 1:1 to the SS-Screen project directories and CLI workflow.
STAGE_GROUPS = (
    ("数据与结构", ("01", "02", "03", "04")),
    ("电子结构", ("05", "06")),
    ("合金模型", ("07", "08")),
    ("稳定性分析", ("09", "10", "11")),
    ("结果与报告", ("12",)),
)

COMPOSITION_SCREEN_OBJECTS = (
    ("input", "筛选输入"),
    ("rules", "筛选规则"),
    ("candidates", "Composition Candidates / 候选材料表"),
    ("summary", "Screening Summary / 筛选统计"),
)

STRUCTURE_ARCHIVE_OBJECTS = (
    ("input", "输入结构"),
    ("archive", "结构描述库"),
    ("manifest", "Manifest"),
    ("index", "Index"),
    ("validation", "Validation"),
)

STRUCTURE_MATCH_OBJECTS = (
    ("input", "匹配输入"),
    ("rules", "匹配规则"),
    ("groups", "Structure Groups / 结构组"),
    ("summary", "Summary"),
)



class Dashboard(QWidget):
    """Dense project overview, closer to a CAE workbench than a slide dashboard."""

    def __init__(self, project_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_provider = project_provider

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        self.title = QLabel("工程概览")
        self.title.setObjectName("pageTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        self.state_badge = QLabel("READY")
        self.state_badge.setObjectName("stateBadge")
        header.addWidget(self.state_badge)
        layout.addLayout(header)

        self.project_path = QLabel("")
        self.project_path.setObjectName("breadcrumb")
        self.project_path.setWordWrap(False)
        layout.addWidget(self.project_path)

        info_box = QGroupBox("Project / 工程")
        info_form = QFormLayout(info_box)
        info_form.setContentsMargins(10, 10, 10, 8)
        info_form.setHorizontalSpacing(14)
        self.project_name_value = QLabel("-")
        self.project_root_value = QLabel("-")
        self.project_root_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stage_value = QLabel("12")
        self.artifact_value = QLabel("0")
        info_form.addRow("工程名称", self.project_name_value)
        info_form.addRow("工作目录", self.project_root_value)
        info_form.addRow("标准阶段", self.stage_value)
        info_form.addRow("已有产物", self.artifact_value)
        layout.addWidget(info_box)

        workflow_box = QGroupBox("Workflow Status / 工作流状态")
        workflow_layout = QVBoxLayout(workflow_box)
        workflow_layout.setContentsMargins(6, 8, 6, 6)

        self.table = QTableWidget(12, 5)
        self.table.setHorizontalHeaderLabels(["Stage", "模块", "工作目录", "状态", "产物数"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 58)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(2, 190)

        for row, (sid, name, directory) in enumerate(STAGES[1:]):
            self.table.setItem(row, 0, QTableWidgetItem(sid))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(directory))

        workflow_layout.addWidget(self.table)
        layout.addWidget(workflow_box, 1)

        action_row = QHBoxLayout()
        self.hint = QLabel("双击或展开左侧工程树进入具体命令。")
        self.hint.setObjectName("smallLabel")
        action_row.addWidget(self.hint)
        action_row.addStretch(1)
        refresh = QPushButton("刷新状态")
        refresh.clicked.connect(self.refresh)
        action_row.addWidget(refresh)
        layout.addLayout(action_row)

        self.refresh()

    def refresh(self) -> None:
        root = self.project_provider()
        self.title.setText(f"{root.name} · 工程概览")
        self.project_path.setText(str(root))
        self.project_name_value.setText(root.name)
        self.project_root_value.setText(str(root))

        total_artifacts = 0
        for row, (_sid, _name, directory) in enumerate(STAGES[1:]):
            path = root / directory
            if not path.exists():
                status = "未开始"
                count = 0
            else:
                try:
                    count = sum(1 for _ in path.iterdir())
                except OSError:
                    count = 0
                status = "已建立" if count == 0 else "有产物"
            total_artifacts += count
            self.table.setItem(row, 3, QTableWidgetItem(status))
            self.table.setItem(row, 4, QTableWidgetItem(str(count)))

        self.artifact_value.setText(str(total_artifacts))


class InspectorPanel(QWidget):
    """Selection/property inspector, similar to engineering CAE applications."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        title = QLabel("属性")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        selection_box = QGroupBox("Selection / 当前选择")
        form = QFormLayout(selection_box)
        form.setContentsMargins(8, 10, 8, 8)
        form.setHorizontalSpacing(8)
        self.type_value = QLabel("工程")
        self.name_value = QLabel("-")
        self.name_value.setWordWrap(True)
        self.path_value = QLabel("-")
        self.path_value.setWordWrap(True)
        self.status_value = QLabel("-")
        form.addRow("类型", self.type_value)
        form.addRow("名称", self.name_value)
        form.addRow("路径", self.path_value)
        form.addRow("状态", self.status_value)
        layout.addWidget(selection_box)

        runtime_box = QGroupBox("Connection / 连接设置")
        runtime_form = QFormLayout(runtime_box)
        runtime_form.setContentsMargins(8, 10, 8, 8)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("MP_API_KEY（可选）")
        runtime_form.addRow("MP API Key", self.api_key)
        note = QLabel("仅注入当前任务进程，不写入命令或项目文件。")
        note.setWordWrap(True)
        note.setObjectName("optionHelp")
        runtime_form.addRow("", note)
        layout.addWidget(runtime_box)

        layout.addStretch(1)

    def set_selection(
        self,
        *,
        item_type: str,
        name: str,
        path: str,
        status: str = "",
    ) -> None:
        self.type_value.setText(item_type)
        self.name_value.setText(name)
        self.path_value.setText(path)
        self.status_value.setText(status or "-")


class MainWindow(QMainWindow):
    """SS-Screen desktop engineering workbench with multi-project roots."""

    def __init__(self, project_dir: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1600, 1000)
        self.setMinimumSize(1180, 720)

        self._pages: dict[tuple[str, ...], CommandPage] = {}
        self._command_lookup = self._collect_commands()
        self._current_run: RunRecord | None = None

        self._projects: list[ProjectRecord] = []
        self._active_project: ProjectRecord | None = None

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)

        self._build_ui()

        initial = Path(project_dir).expanduser() if project_dir else Path.cwd()
        self._add_project(initial.resolve(), initialize=False, activate=True)
        self._apply_style()

    def _collect_commands(self) -> dict[tuple[str, ...], click.Command]:
        lookup: dict[tuple[str, ...], click.Command] = {}
        for presentation in COMMANDS:
            command: click.Command = cli
            ok = True
            for part in presentation.command_path:
                if not isinstance(command, click.Group) or part not in command.commands:
                    ok = False
                    break
                command = command.commands[part]
            if ok:
                lookup[presentation.command_path] = command
        return lookup

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # Title strip: compact, neutral, engineering-software style.
        title_bar = QFrame()
        title_bar.setObjectName("titleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 4, 10, 4)
        title_layout.setSpacing(8)

        product = QLabel("SS-SCREEN")
        product.setObjectName("productMark")
        title_layout.addWidget(product)
        subtitle = QLabel("新材料计算筛选工程工作台")
        subtitle.setObjectName("productSubtitle")
        title_layout.addWidget(subtitle)
        title_layout.addStretch(1)
        self.active_project_label = QLabel("当前工程：—")
        self.active_project_label.setObjectName("activeProjectLabel")
        title_layout.addWidget(self.active_project_label)
        root.addWidget(title_bar)

        # Dense command toolbar.
        toolbar = QFrame()
        toolbar.setObjectName("toolBar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(6, 4, 6, 4)
        tools.setSpacing(4)

        def add_tool(text, slot, object_name="toolButton"):
            button = QPushButton(text)
            button.setObjectName(object_name)
            button.clicked.connect(slot)
            tools.addWidget(button)
            return button

        add_tool("＋ 新建工程", self.new_project)
        add_tool("打开工程", self.open_existing_project)
        add_tool("初始化", self.init_project)
        add_tool("打开目录", self.open_project)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setObjectName("toolbarSeparator")
        tools.addWidget(sep)
        add_tool("从工作区移除", self.remove_active_project)
        tools.addStretch(1)
        add_tool("■ 停止", self.stop_process, "stopButton")
        root.addWidget(toolbar)

        workspace = QSplitter(Qt.Horizontal)
        workspace.setHandleWidth(4)

        # Left: Project Explorer
        project_panel = QFrame()
        project_panel.setObjectName("projectPanel")
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.setSpacing(0)

        project_header = QLabel("工程树 / Project Explorer")
        project_header.setObjectName("panelHeader")
        project_layout.addWidget(project_header)

        self.nav = QTreeWidget()
        self.nav.setObjectName("navigation")
        self.nav.setHeaderLabels(["工程 / 对象", "状态"])
        self.nav.setColumnWidth(0, 225)
        self.nav.setIndentation(17)
        self.nav.setRootIsDecorated(True)
        self.nav.setAlternatingRowColors(False)
        self.nav.itemClicked.connect(self._navigation_clicked)
        project_layout.addWidget(self.nav, 1)
        workspace.addWidget(project_panel)

        # Center: document/work area + output tabs.
        center_split = QSplitter(Qt.Vertical)
        center_split.setHandleWidth(4)
        center_split.setChildrenCollapsible(False)

        document_frame = QFrame()
        document_frame.setObjectName("documentFrame")
        document_frame.setMinimumHeight(500)
        document_layout = QVBoxLayout(document_frame)
        document_layout.setContentsMargins(0, 0, 0, 0)
        document_layout.setSpacing(0)

        document_header = QFrame()
        document_header.setObjectName("documentHeader")
        doc_head_layout = QHBoxLayout(document_header)
        doc_head_layout.setContentsMargins(8, 3, 8, 3)
        self.document_label = QLabel("工程概览")
        self.document_label.setObjectName("documentTitle")
        doc_head_layout.addWidget(self.document_label)
        doc_head_layout.addStretch(1)
        document_layout.addWidget(document_header)

        self.stack = QStackedWidget()
        self.dashboard = Dashboard(self.project_root)
        self.stack.addWidget(self.dashboard)

        self.dataset_source_page = DatasetSourcePage(self.project_root)
        self.dataset_source_page.run_requested.connect(self.run_command)
        self.stack.addWidget(self.dataset_source_page)

        self.composition_screen_page = CompositionScreenPage(self.project_root)
        self.composition_screen_page.run_requested.connect(self.run_command)
        self.stack.addWidget(self.composition_screen_page)

        self.structure_archive_page = StructureArchivePage(self.project_root)
        self.structure_archive_page.run_requested.connect(self.run_command)
        self.stack.addWidget(self.structure_archive_page)

        self.structure_match_page = StructureMatchPage(self.project_root)
        self.structure_match_page.run_requested.connect(self.run_command)
        self.stack.addWidget(self.structure_match_page)

        document_layout.addWidget(self.stack, 1)
        center_split.addWidget(document_frame)

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.setObjectName("bottomTabs")
        self.bottom_tabs.setMinimumHeight(110)
        self.bottom_tabs.setDocumentMode(True)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("logConsole")
        self.log.setPlaceholderText("任务输出将在此显示。")
        self.bottom_tabs.addTab(self.log, "任务输出")

        self.file_model = QFileSystemModel(self)
        self.file_model.setReadOnly(True)
        self.files = QTreeView()
        self.files.setModel(self.file_model)
        self.files.doubleClicked.connect(self._open_selected_file)
        self.files.setObjectName("fileTree")
        self.bottom_tabs.addTab(self.files, "工程文件")

        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setObjectName("messageConsole")
        self.messages.setPlainText("SS-Screen 工程工作台已就绪。\n选择左侧工程节点或分析命令开始。")
        self.bottom_tabs.addTab(self.messages, "消息")

        center_split.addWidget(self.bottom_tabs)
        center_split.setStretchFactor(0, 1)
        center_split.setStretchFactor(1, 0)
        center_split.setSizes([760, 145])
        workspace.addWidget(center_split)

        # Right: properties/inspector.
        inspector_frame = QFrame()
        inspector_frame.setObjectName("inspectorFrame")
        inspector_layout = QVBoxLayout(inspector_frame)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)
        inspector_header = QLabel("属性 / Properties")
        inspector_header.setObjectName("panelHeader")
        inspector_layout.addWidget(inspector_header)
        self.inspector = InspectorPanel()
        inspector_layout.addWidget(self.inspector, 1)
        self.api_key = self.inspector.api_key
        workspace.addWidget(inspector_frame)

        workspace.setSizes([300, 1020, 280])
        workspace.setStretchFactor(1, 1)
        root.addWidget(workspace, 1)

        self.statusBar().setObjectName("statusBar")
        self.statusBar().showMessage("就绪")

    # ---------------- Project tree ----------------

    def _project_by_path(self, path: Path) -> ProjectRecord | None:
        resolved = path.expanduser().resolve()
        for project in self._projects:
            if project.path == resolved:
                return project
        return None

    def _add_project(
        self,
        path: Path,
        *,
        name: str | None = None,
        initialize: bool,
        activate: bool,
    ) -> ProjectRecord:
        path = path.expanduser().resolve()
        existing = self._project_by_path(path)
        if existing is not None:
            if activate:
                self._activate_project(existing)
            return existing

        if initialize:
            self._initialize_project_path(path)

        project = ProjectRecord(name=name or path.name or "工程", path=path)
        self._projects.append(project)
        if activate or self._active_project is None:
            self._active_project = project

        self._rebuild_project_tree()
        if activate:
            self._activate_project(project)
        return project

    def _initialize_project_path(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for directory in PROJECT_DIRS:
            (root / directory).mkdir(parents=True, exist_ok=True)

        metadata_path = root / ".ssscreen-project.json"
        if not metadata_path.exists():
            payload = {
                "schema_version": 1,
                "name": root.name,
                "created_by": "SS-Screen GUI",
            }
            try:
                metadata_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

    def _stage_status(self, root: Path, directory: str) -> tuple[str, int]:
        path = root / directory
        if not path.exists():
            return "未开始", 0
        try:
            count = sum(1 for _ in path.iterdir())
        except OSError:
            count = 0
        if count == 0:
            return "已建立", 0
        return "有产物", count

    def _rebuild_project_tree(self) -> None:
        self.nav.clear()
        active_path = self._active_project.path if self._active_project else None
        active_item: QTreeWidgetItem | None = None

        for project in self._projects:
            root_item = QTreeWidgetItem([project.name, ""])
            root_item.setData(0, Qt.UserRole, ("project", str(project.path)))
            root_item.setToolTip(0, str(project.path))
            root_item.setFirstColumnSpanned(False)
            self.nav.addTopLevelItem(root_item)

            overview = QTreeWidgetItem(["工程概览", ""])
            overview.setData(0, Qt.UserRole, ("dashboard", str(project.path)))
            root_item.addChild(overview)

            for group_name, stage_ids in STAGE_GROUPS:
                group_item = QTreeWidgetItem([group_name, ""])
                group_item.setData(0, Qt.UserRole, ("group", str(project.path), group_name))
                root_item.addChild(group_item)

                for sid in stage_ids:
                    stage_info = next(item for item in STAGES if item[0] == sid)
                    _sid, stage_name, directory = stage_info
                    status, count = self._stage_status(project.path, directory)
                    status_text = status if count == 0 else f"{status} ({count})"
                    stage_item = QTreeWidgetItem([f"{sid}  {stage_name}", status_text])
                    stage_item.setData(
                        0,
                        Qt.UserRole,
                        ("stage", str(project.path), sid, directory, stage_name),
                    )
                    group_item.addChild(stage_item)

                    if sid == "01":
                        dataset_root = project.path / "01_dataset"
                        mp_df = dataset_root / "mp.df"
                        mp_provenance = dataset_root / "mp.df.provenance.json"
                        wbm_df = dataset_root / "wbm.df"

                        mp_parent = QTreeWidgetItem(
                            [
                                "Materials Project",
                                "Ready" if mp_df.exists() else "未获取",
                            ]
                        )
                        mp_parent.setData(
                            0,
                            Qt.UserRole,
                            (
                                "dataset_object",
                                str(project.path),
                                "mp",
                                "Materials Project",
                            ),
                        )
                        stage_item.addChild(mp_parent)

                        for key, name, status_value in (
                            (
                                "mp_fetch",
                                "数据获取 / Acquisition",
                                "API / Offline",
                            ),
                            (
                                "mp_local",
                                "Local Dataset / mp.df",
                                (
                                    "已生成"
                                    if mp_df.exists()
                                    else "未生成"
                                ),
                            ),
                            (
                                "mp_provenance",
                                "Provenance / 来源记录",
                                (
                                    "已生成"
                                    if mp_provenance.exists()
                                    else "未生成"
                                ),
                            ),
                        ):
                            child = QTreeWidgetItem([name, status_value])
                            child.setData(
                                0,
                                Qt.UserRole,
                                (
                                    "dataset_object",
                                    str(project.path),
                                    key,
                                    name,
                                ),
                            )
                            mp_parent.addChild(child)

                        wbm_parent = QTreeWidgetItem(
                            [
                                "WBM Dataset",
                                "Ready" if wbm_df.exists() else "未获取",
                            ]
                        )
                        wbm_parent.setData(
                            0,
                            Qt.UserRole,
                            (
                                "dataset_object",
                                str(project.path),
                                "wbm",
                                "WBM Dataset",
                            ),
                        )
                        stage_item.addChild(wbm_parent)

                        for key, name, status_value in (
                            (
                                "wbm_fetch",
                                "数据获取 / Acquisition",
                                "",
                            ),
                            (
                                "wbm_local",
                                "Local Dataset / wbm.df",
                                (
                                    "已生成"
                                    if wbm_df.exists()
                                    else "未生成"
                                ),
                            ),
                        ):
                            child = QTreeWidgetItem([name, status_value])
                            child.setData(
                                0,
                                Qt.UserRole,
                                (
                                    "dataset_object",
                                    str(project.path),
                                    key,
                                    name,
                                ),
                            )
                            wbm_parent.addChild(child)

                    elif sid == "02":
                        composition_root = project.path / "02_composition"
                        valid_ids = composition_root / "valid_ids.json"
                        candidate_file = (
                            composition_root / "composition_candidates.csv"
                        )
                        composition_summary = (
                            composition_root / "composition_summary.json"
                        )

                        candidate_count = 0
                        template_count = None

                        if composition_summary.exists():
                            try:
                                with composition_summary.open(
                                    "r",
                                    encoding="utf-8",
                                ) as handle:
                                    summary_data = json.load(handle)
                                if isinstance(summary_data, dict):
                                    candidate_count = int(
                                        summary_data.get(
                                            "candidate_rows",
                                            0,
                                        )
                                        or 0
                                    )
                                    value = summary_data.get(
                                        "template_count",
                                        None,
                                    )
                                    if value is not None:
                                        template_count = int(value)
                            except Exception:
                                pass

                        if (
                            candidate_count == 0
                            and candidate_file.exists()
                        ):
                            try:
                                with candidate_file.open(
                                    "r",
                                    encoding="utf-8-sig",
                                    newline="",
                                ) as handle:
                                    candidate_count = sum(
                                        1 for _ in csv.DictReader(handle)
                                    )
                            except Exception:
                                candidate_count = 0

                        # Valence filter remains an optional operation.
                        valence_item = QTreeWidgetItem(
                            [
                                "价态过滤（可选）",
                                "已生成" if valid_ids.exists() else "未使用",
                            ]
                        )
                        valence_item.setData(
                            0,
                            Qt.UserRole,
                            (
                                "command",
                                str(project.path),
                                ("valence-filter",),
                            ),
                        )
                        stage_item.addChild(valence_item)

                        object_status = {
                            "input": "MP / WBM / 自定义",
                            "rules": "Template screening",
                            "candidates": (
                                f"{candidate_count} 条"
                                if candidate_count
                                else "未生成"
                            ),
                            "summary": (
                                (
                                    f"{template_count} templates"
                                    if template_count is not None
                                    else "已生成"
                                )
                                if composition_summary.exists()
                                else "未生成"
                            ),
                        }

                        for object_key, object_name in COMPOSITION_SCREEN_OBJECTS:
                            object_item = QTreeWidgetItem(
                                [object_name, object_status[object_key]]
                            )
                            object_item.setData(
                                0,
                                Qt.UserRole,
                                (
                                    "composition_object",
                                    str(project.path),
                                    object_key,
                                    object_name,
                                ),
                            )
                            stage_item.addChild(object_item)

                    elif sid == "03":
                        archive_root = project.path / "03_condensed"
                        description_count = 0
                        for folder_name in ("mp", "user"):
                            folder = archive_root / folder_name
                            if folder.exists():
                                description_count += len(list(folder.glob("*.json")))

                        manifest_ready = (
                            any(archive_root.glob("*manifest*.jsonl"))
                            if archive_root.exists() else False
                        )
                        index_ready = (
                            any(archive_root.glob("*index*.csv"))
                            if archive_root.exists() else False
                        )
                        validation_ready = (
                            any(archive_root.glob("*validation*.csv"))
                            if archive_root.exists() else False
                        )

                        object_status = {
                            "input": "DataFrame / Files",
                            "archive": f"{description_count} 条" if description_count else "未生成",
                            "manifest": "已生成" if manifest_ready else "未生成",
                            "index": "已生成" if index_ready else "未生成",
                            "validation": "已校验" if validation_ready else "待校验",
                        }
                        for object_key, object_name in STRUCTURE_ARCHIVE_OBJECTS:
                            object_item = QTreeWidgetItem(
                                [object_name, object_status[object_key]]
                            )
                            object_item.setData(
                                0,
                                Qt.UserRole,
                                (
                                    "structure_object",
                                    str(project.path),
                                    object_key,
                                    object_name,
                                ),
                            )
                            stage_item.addChild(object_item)

                    elif sid == "04":
                        candidate_file = (
                            project.path
                            / "02_composition"
                            / "composition_candidates.csv"
                        )
                        archive_root = project.path / "03_condensed"
                        archive_count = 0
                        for folder_name in ("mp", "user", "structures"):
                            folder = archive_root / folder_name
                            if folder.exists() and any(folder.glob("*.json")):
                                archive_count += 1

                        groups_file = project.path / "04_groups" / "groups.json"
                        summary_file = (
                            project.path
                            / "04_groups"
                            / "structure_match_summary.json"
                        )

                        group_count = 0
                        if groups_file.exists():
                            try:
                                with groups_file.open("r", encoding="utf-8") as handle:
                                    group_data = json.load(handle)
                                if isinstance(group_data, list):
                                    group_count = len(group_data)
                                elif isinstance(group_data, dict) and "entry_idx" in group_data:
                                    entry_column = group_data.get("entry_idx", {})
                                    if isinstance(entry_column, dict):
                                        group_count = len(entry_column)
                            except Exception:
                                group_count = 0

                        input_ready = candidate_file.exists() and archive_count > 0
                        object_status = {
                            "input": "Ready" if input_ready else "待准备",
                            "rules": "X substitution",
                            "groups": (
                                f"{group_count} groups"
                                if group_count
                                else "未生成"
                            ),
                            "summary": "已生成" if summary_file.exists() else "未生成",
                        }

                        for object_key, object_name in STRUCTURE_MATCH_OBJECTS:
                            object_item = QTreeWidgetItem(
                                [object_name, object_status[object_key]]
                            )
                            object_item.setData(
                                0,
                                Qt.UserRole,
                                (
                                    "structure_match_object",
                                    str(project.path),
                                    object_key,
                                    object_name,
                                ),
                            )
                            stage_item.addChild(object_item)

                    else:
                        for presentation in COMMANDS:
                            if presentation.stage != sid:
                                continue
                            if presentation.command_path not in self._command_lookup:
                                continue
                            command_item = QTreeWidgetItem([presentation.title, ""])
                            command_item.setData(
                                0,
                                Qt.UserRole,
                                ("command", str(project.path), presentation.command_path),
                            )
                            stage_item.addChild(command_item)

                group_item.setExpanded(True)

            files_item = QTreeWidgetItem(["工程文件", ""])
            files_item.setData(0, Qt.UserRole, ("files", str(project.path)))
            root_item.addChild(files_item)

            logs_item = QTreeWidgetItem(["运行记录", ""])
            logs_item.setData(0, Qt.UserRole, ("logs", str(project.path)))
            root_item.addChild(logs_item)

            root_item.setExpanded(True)

            if active_path is not None and project.path == active_path:
                active_item = root_item

        if active_item is not None:
            self.nav.setCurrentItem(active_item)

    def _navigation_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        kind = data[0]
        path = Path(data[1]).resolve()
        project = self._project_by_path(path)
        if project is None:
            return

        self._activate_project(project)

        if kind in {"project", "dashboard"}:
            self.stack.setCurrentWidget(self.dashboard)
            self.document_label.setText(f"{project.name} / 工程概览")
            self.dashboard.refresh()
            self.inspector.set_selection(
                item_type="工程",
                name=project.name,
                path=str(project.path),
                status="活动工程",
            )
            return

        if kind == "group":
            self.stack.setCurrentWidget(self.dashboard)
            self.document_label.setText(f"{project.name} / {data[2]}")
            self.inspector.set_selection(
                item_type="功能组",
                name=data[2],
                path=str(project.path),
                status="",
            )
            return

        if kind == "stage":
            sid, directory, stage_name = data[2], data[3], data[4]
            status, count = self._stage_status(project.path, directory)

            if sid == "01":
                self.dataset_source_page.select_section("mp")
                self.stack.setCurrentWidget(self.dataset_source_page)
                self.document_label.setText(
                    f"{project.name} / 数据源"
                )
                self.inspector.set_selection(
                    item_type="工程阶段",
                    name="Stage 01：外部材料数据源",
                    path=str(project.path / directory),
                    status=status if count == 0 else f"{status} · {count} 项",
                )
            elif sid == "02":
                self.composition_screen_page.select_section("screen")
                self.stack.setCurrentWidget(self.composition_screen_page)
                self.document_label.setText(
                    f"{project.name} / 组成模板筛选"
                )
                self.inspector.set_selection(
                    item_type="工程阶段",
                    name="流程第 1 步：组成模板筛选",
                    path=str(project.path / directory),
                    status=status if count == 0 else f"{status} · {count} 项",
                )
            elif sid == "03":
                self.structure_archive_page.select_section("input")
                self.stack.setCurrentWidget(self.structure_archive_page)
                self.document_label.setText(f"{project.name} / 结构描述归档")
                self.inspector.set_selection(
                    item_type="工程阶段",
                    name="流程第 2 步：结构描述归档",
                    path=str(project.path / directory),
                    status=status if count == 0 else f"{status} · {count} 项",
                )
            elif sid == "04":
                self.structure_match_page.select_section("match")
                self.stack.setCurrentWidget(self.structure_match_page)
                self.document_label.setText(
                    f"{project.name} / 结构匹配与材料分组"
                )
                self.inspector.set_selection(
                    item_type="工程阶段",
                    name="流程第 3 步：结构匹配与材料分组",
                    path=str(project.path / directory),
                    status=status if count == 0 else f"{status} · {count} 项",
                )
            else:
                self.stack.setCurrentWidget(self.dashboard)
                self.document_label.setText(f"{project.name} / {sid} {stage_name}")
                self.inspector.set_selection(
                    item_type="分析阶段",
                    name=f"{sid} {stage_name}",
                    path=str(project.path / directory),
                    status=status if count == 0 else f"{status} · {count} 项",
                )
            return

        if kind == "dataset_object":
            object_key, object_name = data[2], data[3]
            self.dataset_source_page.select_section(object_key)
            self.stack.setCurrentWidget(self.dataset_source_page)
            self.document_label.setText(
                f"{project.name} / 数据源 / {object_name}"
            )

            if object_key.startswith("mp"):
                if object_key in {"mp_local", "mp_provenance"}:
                    item_type = "本地数据对象"
                else:
                    item_type = "外部数据源"
                object_path = project.path / "01_dataset"
            else:
                if object_key == "wbm_local":
                    item_type = "本地数据对象"
                else:
                    item_type = "外部数据源"
                object_path = project.path / "01_dataset"

            self.inspector.set_selection(
                item_type=item_type,
                name=object_name,
                path=str(object_path),
                status="",
            )
            return

        if kind == "composition_object":
            object_key, object_name = data[2], data[3]
            self.composition_screen_page.select_section(object_key)
            self.stack.setCurrentWidget(self.composition_screen_page)
            self.document_label.setText(
                f"{project.name} / 组成模板筛选 / {object_name}"
            )

            if object_key in {"candidates", "summary"}:
                object_type = "组成筛选结果"
                object_path = project.path / "02_composition"
            else:
                object_type = "组成筛选设置"
                object_path = project.path

            self.inspector.set_selection(
                item_type=object_type,
                name=object_name,
                path=str(object_path),
                status="",
            )
            return

        if kind == "structure_object":
            object_key, object_name = data[2], data[3]
            self.structure_archive_page.select_section(object_key)
            self.stack.setCurrentWidget(self.structure_archive_page)
            self.document_label.setText(
                f"{project.name} / 结构描述归档 / {object_name}"
            )
            self.inspector.set_selection(
                item_type="结构归档对象",
                name=object_name,
                path=str(project.path / "03_condensed"),
                status="",
            )
            return

        if kind == "structure_match_object":
            object_key, object_name = data[2], data[3]
            self.structure_match_page.select_section(object_key)
            self.stack.setCurrentWidget(self.structure_match_page)
            self.document_label.setText(
                f"{project.name} / 结构匹配与材料分组 / {object_name}"
            )

            if object_key in {"groups", "summary"}:
                object_path = project.path / "04_groups"
                object_type = "结构匹配结果"
            else:
                object_path = project.path
                object_type = "结构匹配设置"

            self.inspector.set_selection(
                item_type=object_type,
                name=object_name,
                path=str(object_path),
                status="",
            )
            return

        if kind == "command":
            command_path = tuple(data[2])
            self._show_command_page(command_path)
            presentation = next(p for p in COMMANDS if p.command_path == command_path)
            self.document_label.setText(f"{project.name} / {presentation.title}")
            self.inspector.set_selection(
                item_type="命令",
                name=presentation.title,
                path="ss-screen " + " ".join(command_path),
                status="待运行",
            )
            return

        if kind == "files":
            self.bottom_tabs.setCurrentWidget(self.files)
            self.document_label.setText(f"{project.name} / 工程文件")
            self.inspector.set_selection(
                item_type="文件系统",
                name="工程文件",
                path=str(project.path),
                status="",
            )
            return

        if kind == "logs":
            self.bottom_tabs.setCurrentWidget(self.log)
            self.document_label.setText(f"{project.name} / 运行记录")
            self.inspector.set_selection(
                item_type="日志",
                name="运行记录",
                path=str(project.path / "logs"),
                status="",
            )
            return

    def _activate_project(self, project: ProjectRecord) -> None:
        self._active_project = project
        self.active_project_label.setText(f"工程：{project.name}")
        self.active_project_label.setToolTip(str(project.path))
        self._refresh_file_tree()
        self.dashboard.refresh()

    def new_project(self) -> None:
        parent = QFileDialog.getExistingDirectory(
            self,
            "选择新工程保存位置",
            str(self.project_root().parent),
        )
        if not parent:
            return

        name, ok = QInputDialog.getText(
            self,
            "新建工程",
            "工程名称：",
            text=f"Project-{len(self._projects) + 1:02d}",
        )
        if not ok or not name.strip():
            return

        path = Path(parent) / name.strip()
        if path.exists() and any(path.iterdir()):
            answer = QMessageBox.question(
                self,
                "目录非空",
                f"{path} 已存在且非空。\n是否将其作为 SS-Screen 工程打开？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            project = self._add_project(
                path,
                name=name.strip(),
                initialize=True,
                activate=True,
            )
        except OSError as exc:
            QMessageBox.critical(self, "创建工程失败", str(exc))
            return

        self.document_label.setText(f"{project.name} / 工程概览")
        self.statusBar().showMessage(f"已创建工程：{project.name}")

    def open_existing_project(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self,
            "打开现有 SS-Screen 工程",
            str(self.project_root()),
        )
        if not value:
            return
        project = self._add_project(
            Path(value),
            initialize=False,
            activate=True,
        )
        self.document_label.setText(f"{project.name} / 工程概览")
        self.statusBar().showMessage(f"已打开工程：{project.name}")

    def remove_active_project(self) -> None:
        project = self._active_project
        if project is None:
            return
        if len(self._projects) == 1:
            QMessageBox.information(
                self,
                "保留一个工程",
                "工作区至少保留一个工程。请先新建或打开另一个工程。",
            )
            return

        answer = QMessageBox.question(
            self,
            "从工作区移除工程",
            f"仅从当前工作区移除“{project.name}”，不会删除磁盘文件。\n确认继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._projects = [item for item in self._projects if item.path != project.path]
        self._active_project = self._projects[0] if self._projects else None
        self._rebuild_project_tree()
        if self._active_project is not None:
            self._activate_project(self._active_project)

    def project_root(self) -> Path:
        if self._active_project is not None:
            return self._active_project.path
        return Path.cwd().resolve()

    def init_project(self) -> None:
        root = self.project_root()
        try:
            self._initialize_project_path(root)
        except OSError as exc:
            QMessageBox.critical(self, "初始化失败", str(exc))
            return

        self.dashboard.refresh()
        self._refresh_file_tree()
        self._rebuild_project_tree()
        self.statusBar().showMessage(f"已初始化工程目录：{root}")

    def open_project(self) -> None:
        root = self.project_root()
        if root.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    # ---------------- Command pages ----------------

    def _show_command_page(self, path: tuple[str, ...]) -> None:
        if path == ("dataset", "mp"):
            self.dataset_source_page.select_section("mp")
            self.stack.setCurrentWidget(self.dataset_source_page)
            return

        if path == ("dataset", "wbm"):
            self.dataset_source_page.select_section("wbm")
            self.stack.setCurrentWidget(self.dataset_source_page)
            return

        if path == ("composition-screen",):
            self.composition_screen_page.select_section("screen")
            self.stack.setCurrentWidget(self.composition_screen_page)
            return

        if path in {("condense",), ("condense-index",), ("condense-validate",)}:
            self.structure_archive_page.select_section(
                "input" if path == ("condense",) else "archive"
            )
            self.stack.setCurrentWidget(self.structure_archive_page)
            return

        if path == ("structure-match",):
            self.structure_match_page.select_section("match")
            self.stack.setCurrentWidget(self.structure_match_page)
            return

        if path in self._pages:
            self.stack.setCurrentWidget(self._pages[path])
            return

        command = self._command_lookup[path]
        presentation = next(item for item in COMMANDS if item.command_path == path)
        page = CommandPage(presentation, command)
        page.run_requested.connect(self.run_command)
        self._pages[path] = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    # ---------------- Files / process ----------------

    def _refresh_file_tree(self) -> None:
        root = self.project_root()
        if not root.exists():
            self.files.setRootIndex(self.file_model.index(""))
            return

        index = self.file_model.setRootPath(str(root))
        self.files.setRootIndex(index)
        self.files.setColumnWidth(0, 360)

    def _open_selected_file(self, index) -> None:
        path = Path(self.file_model.filePath(index))
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def run_command(self, argv: list[str], title: str) -> None:
        if self.process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "已有任务运行", "请等待当前任务结束，或先停止当前任务。")
            return

        project = self._active_project
        if project is None:
            QMessageBox.warning(self, "未选择工程", "请先新建或打开一个工程。")
            return

        root = project.path
        root.mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(exist_ok=True)

        preview = shlex.join(["ss-screen", *argv])
        self._current_run = RunRecord(
            started=datetime.now().isoformat(timespec="seconds"),
            command=preview,
        )

        self.log.appendPlainText("\n" + "=" * 90)
        self.log.appendPlainText(f"[PROJECT] {project.name}")
        self.log.appendPlainText(f"[TASK] {title}")
        self.log.appendPlainText(f"[CWD] {root}")
        self.log.appendPlainText(f"[CMD] {preview}")
        self.log.appendPlainText("=" * 90)
        self.bottom_tabs.setCurrentWidget(self.log)

        env = QProcessEnvironment.systemEnvironment()
        key = self.api_key.text().strip()
        if key:
            env.insert("MP_API_KEY", key)
        env.insert("PYTHONUNBUFFERED", "1")

        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(root))
        program = sys.executable
        args = ["-m", "ssscreen.cli.app", *argv]
        self.process.start(program, args)
        self.statusBar().showMessage(f"{project.name} · 运行中：{title}")

    def stop_process(self) -> None:
        if self.process.state() == QProcess.NotRunning:
            self.statusBar().showMessage("当前没有运行中的任务")
            return
        self.log.appendPlainText("\n[GUI] 正在停止当前任务……")
        self.process.terminate()
        if not self.process.waitForFinished(2000):
            self.process.kill()
        self.statusBar().showMessage("任务已停止")

    def _read_stdout(self) -> None:
        raw = bytes(self.process.readAllStandardOutput())
        self._append_log(raw.decode("utf-8", errors="replace"))

    def _read_stderr(self) -> None:
        raw = bytes(self.process.readAllStandardError())
        self._append_log(raw.decode("utf-8", errors="replace"))

    def _append_log(self, text: str) -> None:
        if not text:
            return
        text = text.replace("\r", "\n")
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _finished(self, exit_code: int, _exit_status) -> None:
        self.log.appendPlainText(f"\n[GUI] 任务结束，exit code = {exit_code}")
        self.statusBar().showMessage(f"任务结束 · 退出码 {exit_code}")

        finished_command = (
            self._current_run.command
            if self._current_run is not None
            else ""
        )

        if self._current_run is not None:
            self._current_run.exit_code = exit_code
            self._write_run_audit(self._current_run)
            self._current_run = None

        self.dashboard.refresh()
        self.dataset_source_page.refresh_sources()
        self.composition_screen_page.refresh_inputs()
        self.composition_screen_page.refresh_results()
        self.structure_archive_page.refresh_archive()
        self.structure_match_page.refresh_inputs()
        self.structure_match_page.refresh_results()
        self._refresh_file_tree()
        self._rebuild_project_tree()

        if exit_code == 0 and " dataset mp " in f" {finished_command} ":
            if self.dataset_source_page._resolve(
                self.dataset_source_page.mp_output.text()
            ).exists():
                self.dataset_source_page.select_section("local")
                self.stack.setCurrentWidget(self.dataset_source_page)

        if exit_code == 0 and " dataset wbm " in f" {finished_command} ":
            if self.dataset_source_page._resolve(
                self.dataset_source_page.wbm_output.text()
            ).exists():
                self.dataset_source_page.select_section("local")
                self.stack.setCurrentWidget(self.dataset_source_page)

        if exit_code == 0 and " composition-screen " in f" {finished_command} ":
            candidates_path = self.composition_screen_page._resolve(
                self.composition_screen_page.candidates_output.text()
            )
            summary_path = self.composition_screen_page._resolve(
                self.composition_screen_page.summary_output.text()
            )
            if candidates_path.exists() or summary_path.exists():
                self.composition_screen_page.select_section("candidates")
                self.stack.setCurrentWidget(self.composition_screen_page)

    def _write_run_audit(self, record: RunRecord) -> None:
        path = self.project_root() / "logs" / "gui_commands.jsonl"
        payload = {
            "timestamp": record.started,
            "project": self._active_project.name if self._active_project else None,
            "command": record.command,
            "exit_code": record.exit_code,
            "gui_version": __version__,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            self.log.appendPlainText(f"[GUI] 无法写入命令审计日志：{exc}")

    def _process_error(self, error) -> None:
        self.log.appendPlainText(f"\n[GUI] QProcess 错误：{error}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.process.state() == QProcess.NotRunning:
            event.accept()
            return

        answer = QMessageBox.question(
            self,
            "任务仍在运行",
            "关闭 GUI 会停止当前任务。确认关闭吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.stop_process()
            event.accept()
        else:
            event.ignore()

    def _apply_style(self) -> None:
        # Dense neutral palette inspired by CAE/engineering desktop tools.
        QApplication.instance().setFont(QFont("Segoe UI", 9))
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #e9eaec;
                color: #202428;
            }
            #titleBar {
                background: #30353a;
                border-bottom: 1px solid #1f2327;
                min-height: 28px;
                max-height: 28px;
            }
            #productMark {
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            #productSubtitle {
                color: #cbd0d5;
                font-size: 11px;
            }
            #activeProjectLabel {
                color: #e6e9ec;
                font-size: 11px;
            }
            #toolBar {
                background: #d7d9dc;
                border-bottom: 1px solid #aeb2b7;
                min-height: 34px;
                max-height: 34px;
            }
            #toolButton, #stopButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 2px;
                padding: 4px 8px;
                min-height: 20px;
            }
            #toolButton:hover {
                background: #eef0f2;
                border-color: #aeb3b9;
            }
            #stopButton {
                color: #8c2424;
            }
            #stopButton:hover {
                background: #f2dddd;
                border-color: #c89a9a;
            }
            #toolbarSeparator {
                color: #a8acb1;
                margin-left: 3px;
                margin-right: 3px;
            }
            #projectPanel, #inspectorFrame {
                background: #f0f1f2;
                border: 0;
            }
            #projectPanel {
                border-right: 1px solid #9fa4aa;
            }
            #inspectorFrame {
                border-left: 1px solid #9fa4aa;
            }
            #panelHeader {
                background: #d1d4d7;
                border-bottom: 1px solid #9ea3a8;
                color: #2b3035;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 7px;
                min-height: 18px;
                max-height: 18px;
            }
            #navigation {
                background: #f5f6f7;
                border: 0;
                outline: none;
                alternate-background-color: #eef0f2;
                font-size: 11px;
            }
            #navigation::item {
                min-height: 21px;
                padding: 1px 2px;
                border: 0;
            }
            #navigation::item:selected {
                background: #b8c9da;
                color: #17212b;
            }
            #navigation::item:hover {
                background: #dce4eb;
            }
            QHeaderView::section {
                background: #d6d8db;
                color: #30353a;
                border: 0;
                border-right: 1px solid #b3b6ba;
                border-bottom: 1px solid #a7abb0;
                padding: 4px 5px;
                font-size: 10px;
                font-weight: 600;
            }
            #documentFrame {
                background: #f7f7f8;
                border: 0;
            }
            #documentHeader {
                background: #e0e2e4;
                border-bottom: 1px solid #aeb2b7;
                min-height: 25px;
                max-height: 25px;
            }
            #documentTitle {
                color: #30353a;
                font-size: 11px;
                font-weight: 600;
            }
            #pageTitle {
                color: #202428;
                font-size: 16px;
                font-weight: 600;
            }
            #breadcrumb, #commandName {
                color: #56616b;
                font-size: 10px;
                font-family: Consolas, monospace;
            }
            #pageDescription {
                color: #4f5962;
                font-size: 11px;
            }
            #panelTitle {
                color: #202428;
                font-size: 12px;
                font-weight: 600;
                padding: 2px;
            }
            #stateBadge {
                background: #4f6577;
                color: white;
                border-radius: 2px;
                padding: 2px 7px;
                font-size: 9px;
                font-weight: 600;
            }
            #smallLabel, #optionHelp {
                color: #69737c;
                font-size: 9px;
            }
            QGroupBox {
                background: #f5f6f7;
                border: 1px solid #b8bcc1;
                border-radius: 1px;
                margin-top: 10px;
                padding-top: 7px;
                font-size: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 7px;
                padding: 0 3px;
                color: #384047;
            }
            QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QTreeView {
                background: #ffffff;
                border: 1px solid #adb2b7;
                border-radius: 1px;
                padding: 3px;
                selection-background-color: #9fb8cf;
                selection-color: #111820;
                font-size: 10px;
            }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                border-color: #5e7e9b;
            }
            QPushButton {
                background: #e7e8ea;
                border: 1px solid #aeb2b7;
                border-radius: 2px;
                padding: 4px 9px;
                min-height: 20px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #f4f5f6;
                border-color: #8f959b;
            }
            #primaryButton {
                background: #506d86;
                color: white;
                border-color: #3e596f;
                font-weight: 600;
            }
            #primaryButton:hover {
                background: #607f99;
            }
            #commandPreview, #logConsole, #messageConsole {
                background: #1f2428;
                color: #d6d9dc;
                border: 1px solid #15191c;
                font-family: Consolas, monospace;
                font-size: 10px;
            }
            #bottomTabs::pane {
                border-top: 1px solid #9fa4aa;
                background: #f2f3f4;
            }
            QTabBar::tab {
                background: #d6d8db;
                border-right: 1px solid #b0b4b9;
                padding: 4px 12px;
                min-height: 18px;
                font-size: 10px;
            }
            QTabBar::tab:selected {
                background: #f2f3f4;
                font-weight: 600;
            }
            QTabWidget::pane {
                border: 1px solid #aeb2b7;
                background: #f7f7f8;
            }
            QTableWidget {
                gridline-color: #c6c9cc;
            }
            #groupsTable {
                background: #ffffff;
            }
            #statusBar {
                background: #d2d4d6;
                border-top: 1px solid #a8acb1;
                color: #3e454c;
                font-size: 9px;
            }

            QTableWidget::item {
                min-height: 22px;
                padding: 3px 5px;
            }
            QScrollBar:vertical {
                background: #e2e4e6;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #a7adb3;
                min-height: 26px;
                border-radius: 2px;
            }
            QScrollBar:horizontal {
                background: #e2e4e6;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #a7adb3;
                min-width: 26px;
                border-radius: 2px;
            }
            QSplitter::handle {
                background: #aeb2b7;
            }
            """
        )


def run_gui(project_dir: str | None = None) -> int:
    """Run the desktop workbench and return the Qt application exit code."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    app.setApplicationName("SS-Screen")
    window = MainWindow(project_dir=project_dir)
    window.show()
    return app.exec()


def main() -> int:
    project_dir = sys.argv[1] if len(sys.argv) > 1 else None
    return run_gui(project_dir=project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
