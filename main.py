import os
import shutil
import sqlite3
import sys
from datetime import datetime

import pandas as pd
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

DB_FILE = "trade_review.db"

DEFAULT_OPTIONS = {
    "strategy_type": ["隔夜超短", "正T", "反T", "波段持有", "趋势跟踪", "打板", "低吸反弹", "其他"],
    "buy_signal": ["日线BOLL缩口", "60分金叉", "RSI底背离", "放量突破前高"],
    "sell_signal": ["15分死叉", "冲高回落长上影", "达到目标止盈", "跌破止损线"],
    "profit_reason": ["顺势持有", "信号精准", "严格执行止盈", "运气好"],
    "error_reason": ["追高", "没止损", "信号误判", "过早止盈", "大盘拖累", "情绪化交易", "违反策略"],
}


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.figure = Figure(figsize=(8, 4), dpi=100)
        super().__init__(self.figure)
        self.setParent(parent)


class MultiSelectDialog(QDialog):
    def __init__(self, title, options, current_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 520)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(self.list_widget.MultiSelection)
        for opt in options:
            self.list_widget.addItem(QListWidgetItem(opt))
        layout.addWidget(QLabel("请选择预设项（可多选）："))
        layout.addWidget(self.list_widget)
        self.manual_edit = QTextEdit()
        self.manual_edit.setPlaceholderText("可补充手动输入，多个用逗号分隔")
        self.manual_edit.setText(current_text)
        layout.addWidget(QLabel("当前值（可直接编辑）："))
        layout.addWidget(self.manual_edit)
        btns = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def get_value(self):
        selected = [item.text() for item in self.list_widget.selectedItems()]
        manual = self.manual_edit.toPlainText().strip()
        current_parts = [x.strip() for x in manual.replace("，", ",").split(",") if x.strip()]
        merged = []
        for value in selected + current_parts:
            if value not in merged:
                merged.append(value)
        return "，".join(merged)


class OptionManagerDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("自定义选项管理")
        self.resize(760, 520)
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        self.category_combo = QComboBox()
        self.category_combo.addItems(["strategy_type", "buy_signal", "sell_signal", "profit_reason", "error_reason"])
        self.list_widget = QListWidget()
        left.addWidget(QLabel("选项分类："))
        left.addWidget(self.category_combo)
        left.addWidget(self.list_widget)
        root.addLayout(left, 3)

        right = QVBoxLayout()
        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText("输入新选项")
        add_btn = QPushButton("新增")
        rename_btn = QPushButton("重命名")
        delete_btn = QPushButton("删除")
        close_btn = QPushButton("关闭")
        right.addWidget(QLabel("编辑："))
        right.addWidget(self.new_edit)
        right.addWidget(add_btn)
        right.addWidget(rename_btn)
        right.addWidget(delete_btn)
        right.addStretch()
        right.addWidget(close_btn)
        root.addLayout(right, 2)

        self.category_combo.currentIndexChanged.connect(self.load_items)
        add_btn.clicked.connect(self.add_item)
        rename_btn.clicked.connect(self.rename_item)
        delete_btn.clicked.connect(self.delete_item)
        close_btn.clicked.connect(self.accept)
        self.load_items()

    def load_items(self):
        self.list_widget.clear()
        category = self.category_combo.currentText()
        rows = self.conn.execute(
            "SELECT value FROM option_items WHERE category=? ORDER BY id ASC",
            (category,),
        ).fetchall()
        for row in rows:
            self.list_widget.addItem(row["value"])

    def add_item(self):
        category = self.category_combo.currentText()
        value = self.new_edit.text().strip()
        if not value:
            return
        exists = self.conn.execute(
            "SELECT 1 FROM option_items WHERE category=? AND value=?",
            (category, value),
        ).fetchone()
        if exists:
            QMessageBox.warning(self, "提示", "该选项已存在。")
            return
        self.conn.execute("INSERT INTO option_items(category, value) VALUES (?, ?)", (category, value))
        self.conn.commit()
        self.new_edit.clear()
        self.load_items()

    def rename_item(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        category = self.category_combo.currentText()
        old_value = item.text()
        new_value, ok = QInputDialog.getText(self, "重命名", "新值：", text=old_value)
        if not ok:
            return
        new_value = new_value.strip()
        if not new_value:
            return
        self.conn.execute(
            "UPDATE option_items SET value=? WHERE category=? AND value=?",
            (new_value, category, old_value),
        )
        self.conn.commit()
        self.load_items()

    def delete_item(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        category = self.category_combo.currentText()
        value = item.text()
        self.conn.execute("DELETE FROM option_items WHERE category=? AND value=?", (category, value))
        self.conn.commit()
        self.load_items()


class TradeReviewApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("股票交易复盘统计桌面应用（纯本地）")
        self.resize(1600, 900)
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.row_factory = sqlite3.Row
        self.current_trade_id = None
        self.last_warning_key = None

        self.init_database()
        self.init_menu()
        self.init_ui()
        self.reload_option_controls()
        self.load_note_for_selected_date()
        self.load_trades()

    def init_database(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                strategy_type TEXT NOT NULL,
                buy_date TEXT NOT NULL,
                buy_price REAL NOT NULL,
                buy_shares INTEGER NOT NULL,
                sell_date TEXT NOT NULL,
                sell_price REAL NOT NULL,
                hold_days INTEGER NOT NULL,
                pnl_amount REAL NOT NULL,
                pnl_ratio REAL NOT NULL,
                buy_signals TEXT,
                sell_signals TEXT,
                profit_reasons TEXT,
                error_reasons TEXT,
                review_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_date TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS option_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                value TEXT NOT NULL
            )
            """
        )
        for category, values in DEFAULT_OPTIONS.items():
            for value in values:
                exists = cursor.execute(
                    "SELECT 1 FROM option_items WHERE category=? AND value=?",
                    (category, value),
                ).fetchone()
                if not exists:
                    cursor.execute("INSERT INTO option_items(category, value) VALUES (?, ?)", (category, value))
        self.conn.commit()

    def init_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")
        settings_menu = menu_bar.addMenu("设置")
        help_menu = menu_bar.addMenu("帮助")

        import_action = QAction("导入交割单CSV", self)
        export_action = QAction("导出当前筛选CSV", self)
        backup_action = QAction("备份数据库", self)
        restore_action = QAction("恢复数据库", self)
        exit_action = QAction("退出", self)
        option_action = QAction("自定义下拉选项", self)
        about_action = QAction("关于", self)

        file_menu.addAction(import_action)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        file_menu.addAction(backup_action)
        file_menu.addAction(restore_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        settings_menu.addAction(option_action)
        help_menu.addAction(about_action)

        import_action.triggered.connect(self.import_delivery_csv)
        export_action.triggered.connect(self.export_csv)
        backup_action.triggered.connect(self.backup_database)
        restore_action.triggered.connect(self.restore_database)
        exit_action.triggered.connect(self.close)
        option_action.triggered.connect(self.open_option_manager)
        about_action.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "关于",
                "股票交易复盘统计桌面应用\n纯本地运行 / SQLite存储 / PyQt5界面",
            )
        )

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        splitter.addWidget(left)

        form_group = QGroupBox("交易录入 / 编辑")
        form = QFormLayout(form_group)
        self.stock_code_edit = QLineEdit()
        self.stock_name_edit = QLineEdit()
        self.strategy_combo = QComboBox()
        self.strategy_combo.setEditable(True)
        self.buy_date_edit = QDateEdit()
        self.buy_date_edit.setCalendarPopup(True)
        self.buy_date_edit.setDate(QDate.currentDate())
        self.buy_price_edit = QLineEdit()
        self.buy_shares_spin = QSpinBox()
        self.buy_shares_spin.setRange(1, 100000000)
        self.buy_shares_spin.setValue(100)
        self.sell_date_edit = QDateEdit()
        self.sell_date_edit.setCalendarPopup(True)
        self.sell_date_edit.setDate(QDate.currentDate())
        self.sell_price_edit = QLineEdit()
        self.hold_days_label = QLabel("0")
        self.pnl_amount_edit = QLineEdit()
        self.pnl_ratio_label = QLabel("0.00%")
        self.buy_signals_edit = QLineEdit()
        self.sell_signals_edit = QLineEdit()
        self.profit_reasons_edit = QLineEdit()
        self.error_reasons_edit = QLineEdit()
        self.review_note_edit = QTextEdit()
        self.review_note_edit.setMaximumHeight(80)

        buy_signal_btn = QPushButton("选择")
        sell_signal_btn = QPushButton("选择")
        profit_reason_btn = QPushButton("选择")
        error_reason_btn = QPushButton("选择")

        buy_signal_layout = QHBoxLayout()
        buy_signal_layout.addWidget(self.buy_signals_edit)
        buy_signal_layout.addWidget(buy_signal_btn)
        sell_signal_layout = QHBoxLayout()
        sell_signal_layout.addWidget(self.sell_signals_edit)
        sell_signal_layout.addWidget(sell_signal_btn)
        profit_reason_layout = QHBoxLayout()
        profit_reason_layout.addWidget(self.profit_reasons_edit)
        profit_reason_layout.addWidget(profit_reason_btn)
        error_reason_layout = QHBoxLayout()
        error_reason_layout.addWidget(self.error_reasons_edit)
        error_reason_layout.addWidget(error_reason_btn)

        form.addRow("股票代码*：", self.stock_code_edit)
        form.addRow("股票名称：", self.stock_name_edit)
        form.addRow("策略类型*：", self.strategy_combo)
        form.addRow("买入日期*：", self.buy_date_edit)
        form.addRow("买入价格*：", self.buy_price_edit)
        form.addRow("买入股数*：", self.buy_shares_spin)
        form.addRow("卖出日期*：", self.sell_date_edit)
        form.addRow("卖出价格*：", self.sell_price_edit)
        form.addRow("持仓天数（自动）：", self.hold_days_label)
        form.addRow("盈亏金额*：", self.pnl_amount_edit)
        form.addRow("收益率*（自动）：", self.pnl_ratio_label)
        form.addRow("买入触发信号：", buy_signal_layout)
        form.addRow("卖出触发信号：", sell_signal_layout)
        form.addRow("盈利原因：", profit_reason_layout)
        form.addRow("错误/亏损原因：", error_reason_layout)
        form.addRow("复盘备注：", self.review_note_edit)
        left_layout.addWidget(form_group)

        btn_layout = QGridLayout()
        self.add_btn = QPushButton("添加记录")
        self.save_btn = QPushButton("保存修改")
        self.delete_btn = QPushButton("删除记录")
        self.copy_btn = QPushButton("复制记录")
        self.clear_btn = QPushButton("清空")
        btn_layout.addWidget(self.add_btn, 0, 0)
        btn_layout.addWidget(self.save_btn, 0, 1)
        btn_layout.addWidget(self.delete_btn, 1, 0)
        btn_layout.addWidget(self.copy_btn, 1, 1)
        btn_layout.addWidget(self.clear_btn, 2, 0, 1, 2)
        left_layout.addLayout(btn_layout)

        filter_group = QGroupBox("筛选")
        filter_layout = QGridLayout(filter_group)
        self.filter_strategy_combo = QComboBox()
        self.filter_strategy_combo.addItem("全部")
        self.filter_code_edit = QLineEdit()
        self.filter_start_date = QDateEdit()
        self.filter_start_date.setCalendarPopup(True)
        self.filter_start_date.setDate(QDate.currentDate().addMonths(-3))
        self.filter_end_date = QDateEdit()
        self.filter_end_date.setCalendarPopup(True)
        self.filter_end_date.setDate(QDate.currentDate())
        self.filter_btn = QPushButton("筛选")
        self.filter_reset_btn = QPushButton("重置")
        filter_layout.addWidget(QLabel("策略类型："), 0, 0)
        filter_layout.addWidget(self.filter_strategy_combo, 0, 1)
        filter_layout.addWidget(QLabel("股票代码："), 1, 0)
        filter_layout.addWidget(self.filter_code_edit, 1, 1)
        filter_layout.addWidget(QLabel("开始日期："), 2, 0)
        filter_layout.addWidget(self.filter_start_date, 2, 1)
        filter_layout.addWidget(QLabel("结束日期："), 3, 0)
        filter_layout.addWidget(self.filter_end_date, 3, 1)
        filter_layout.addWidget(self.filter_btn, 4, 0)
        filter_layout.addWidget(self.filter_reset_btn, 4, 1)
        left_layout.addWidget(filter_group)

        self.trade_table = QTableWidget()
        self.trade_table.setColumnCount(18)
        self.trade_table.setHorizontalHeaderLabels(
            [
                "ID",
                "股票代码",
                "股票名称",
                "策略类型",
                "买入日期",
                "买入价",
                "买入股数",
                "卖出日期",
                "卖出价",
                "持仓天数",
                "盈亏金额",
                "收益率(%)",
                "买入信号",
                "卖出信号",
                "盈利原因",
                "错误原因",
                "复盘备注",
                "更新时间",
            ]
        )
        self.trade_table.setSelectionBehavior(self.trade_table.SelectRows)
        self.trade_table.setEditTriggers(self.trade_table.NoEditTriggers)
        self.trade_table.setColumnHidden(0, True)
        left_layout.addWidget(self.trade_table, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)

        cards_group = QGroupBox("统计卡片")
        cards_layout = QGridLayout(cards_group)
        self.total_pnl_card = QLabel("0.00")
        self.total_count_card = QLabel("0")
        self.win_rate_card = QLabel("0.00%")
        self.avg_pl_ratio_card = QLabel("0.00")
        self.max_profit_card = QLabel("0.00")
        self.max_drawdown_card = QLabel("0.00")
        cards_layout.addWidget(QLabel("总盈亏："), 0, 0)
        cards_layout.addWidget(self.total_pnl_card, 0, 1)
        cards_layout.addWidget(QLabel("总交易笔数："), 0, 2)
        cards_layout.addWidget(self.total_count_card, 0, 3)
        cards_layout.addWidget(QLabel("胜率："), 1, 0)
        cards_layout.addWidget(self.win_rate_card, 1, 1)
        cards_layout.addWidget(QLabel("平均盈亏比："), 1, 2)
        cards_layout.addWidget(self.avg_pl_ratio_card, 1, 3)
        cards_layout.addWidget(QLabel("最大单笔盈利："), 2, 0)
        cards_layout.addWidget(self.max_profit_card, 2, 1)
        cards_layout.addWidget(QLabel("最大单笔回撤："), 2, 2)
        cards_layout.addWidget(self.max_drawdown_card, 2, 3)
        right_layout.addWidget(cards_group)

        top_stats_split = QSplitter(Qt.Horizontal)
        self.strategy_stats_table = QTableWidget()
        self.strategy_stats_table.setColumnCount(7)
        self.strategy_stats_table.setHorizontalHeaderLabels(
            ["策略", "交易次数", "胜率(%)", "总盈亏", "平均收益率(%)", "盈亏比", "评级(稳定性)"]
        )
        self.strategy_stats_table.setSelectionBehavior(self.strategy_stats_table.SelectRows)
        self.strategy_stats_table.setEditTriggers(self.strategy_stats_table.NoEditTriggers)
        top_stats_split.addWidget(self.strategy_stats_table)
        self.reason_stats_table = QTableWidget()
        self.reason_stats_table.setColumnCount(3)
        self.reason_stats_table.setHorizontalHeaderLabels(["盈利原因", "出现次数", "平均收益率(%)"])
        self.reason_stats_table.setSelectionBehavior(self.reason_stats_table.SelectRows)
        self.reason_stats_table.setEditTriggers(self.reason_stats_table.NoEditTriggers)
        top_stats_split.addWidget(self.reason_stats_table)
        top_stats_split.setSizes([520, 360])
        right_layout.addWidget(top_stats_split, 1)

        self.chart_tabs = QTabWidget()
        self.equity_canvas = MplCanvas(self)
        self.monthly_canvas = MplCanvas(self)
        self.strategy_win_canvas = MplCanvas(self)
        self.error_pie_canvas = MplCanvas(self)
        self.profit_pie_canvas = MplCanvas(self)
        self.chart_tabs.addTab(self.wrap_canvas(self.equity_canvas), "累计资金曲线")
        self.chart_tabs.addTab(self.wrap_canvas(self.monthly_canvas), "月度盈亏柱状图")
        self.chart_tabs.addTab(self.wrap_canvas(self.strategy_win_canvas), "策略胜率对比")
        self.chart_tabs.addTab(self.wrap_canvas(self.error_pie_canvas), "错误原因占比")
        self.chart_tabs.addTab(self.wrap_canvas(self.profit_pie_canvas), "盈利原因占比")
        right_layout.addWidget(self.chart_tabs, 2)

        note_group = QGroupBox("每日复盘笔记")
        note_layout = QVBoxLayout(note_group)
        note_top = QHBoxLayout()
        self.note_date_edit = QDateEdit()
        self.note_date_edit.setCalendarPopup(True)
        self.note_date_edit.setDate(QDate.currentDate())
        self.load_note_btn = QPushButton("加载")
        self.save_note_btn = QPushButton("保存")
        note_top.addWidget(QLabel("日期："))
        note_top.addWidget(self.note_date_edit)
        note_top.addWidget(self.load_note_btn)
        note_top.addWidget(self.save_note_btn)
        self.daily_note_text = QTextEdit()
        self.daily_note_text.setMaximumHeight(110)
        note_layout.addLayout(note_top)
        note_layout.addWidget(self.daily_note_text)
        right_layout.addWidget(note_group)

        splitter.setSizes([560, 1040])

        self.add_btn.clicked.connect(self.add_trade)
        self.save_btn.clicked.connect(self.update_trade)
        self.delete_btn.clicked.connect(self.delete_trade)
        self.copy_btn.clicked.connect(self.copy_trade)
        self.clear_btn.clicked.connect(self.clear_form)
        self.filter_btn.clicked.connect(self.load_trades)
        self.filter_reset_btn.clicked.connect(self.reset_filters)
        self.trade_table.itemSelectionChanged.connect(self.on_trade_selected)
        self.strategy_stats_table.itemSelectionChanged.connect(self.on_strategy_stats_selected)
        self.buy_price_edit.textChanged.connect(self.recalculate_form_values)
        self.sell_price_edit.textChanged.connect(self.recalculate_form_values)
        self.buy_shares_spin.valueChanged.connect(self.recalculate_form_values)
        self.buy_date_edit.dateChanged.connect(self.recalculate_form_values)
        self.sell_date_edit.dateChanged.connect(self.recalculate_form_values)
        buy_signal_btn.clicked.connect(lambda: self.open_multi_selector("buy_signal", self.buy_signals_edit, "买入触发信号"))
        sell_signal_btn.clicked.connect(lambda: self.open_multi_selector("sell_signal", self.sell_signals_edit, "卖出触发信号"))
        profit_reason_btn.clicked.connect(lambda: self.open_multi_selector("profit_reason", self.profit_reasons_edit, "盈利原因"))
        error_reason_btn.clicked.connect(lambda: self.open_multi_selector("error_reason", self.error_reasons_edit, "错误/亏损原因"))
        self.load_note_btn.clicked.connect(self.load_note_for_selected_date)
        self.save_note_btn.clicked.connect(self.save_note_for_selected_date)
        self.note_date_edit.dateChanged.connect(self.load_note_for_selected_date)

    @staticmethod
    def wrap_canvas(canvas):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(canvas)
        return w

    def get_options(self, category):
        rows = self.conn.execute(
            "SELECT value FROM option_items WHERE category=? ORDER BY id ASC",
            (category,),
        ).fetchall()
        return [row["value"] for row in rows]

    def reload_option_controls(self):
        strategies = self.get_options("strategy_type")
        self.strategy_combo.clear()
        self.strategy_combo.addItems(strategies)
        self.filter_strategy_combo.clear()
        self.filter_strategy_combo.addItem("全部")
        self.filter_strategy_combo.addItems(strategies)

    def open_option_manager(self):
        dialog = OptionManagerDialog(self.conn, self)
        dialog.exec_()
        self.reload_option_controls()

    def open_multi_selector(self, category, target_edit, title):
        dialog = MultiSelectDialog(title, self.get_options(category), target_edit.text(), self)
        if dialog.exec_():
            target_edit.setText(dialog.get_value())

    @staticmethod
    def parse_float(text):
        try:
            return float(str(text).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    def recalculate_form_values(self):
        buy = self.parse_float(self.buy_price_edit.text())
        sell = self.parse_float(self.sell_price_edit.text())
        shares = self.buy_shares_spin.value()
        buy_date = self.buy_date_edit.date().toString("yyyy-MM-dd")
        sell_date = self.sell_date_edit.date().toString("yyyy-MM-dd")
        hold_days = (datetime.strptime(sell_date, "%Y-%m-%d") - datetime.strptime(buy_date, "%Y-%m-%d")).days
        hold_days = max(hold_days, 0)
        self.hold_days_label.setText(str(hold_days))
        if buy is None or sell is None:
            self.pnl_ratio_label.setText("0.00%")
            return
        pnl_amount = (sell - buy) * shares
        cost = buy * shares
        pnl_ratio = (pnl_amount / cost * 100) if cost > 0 else 0.0
        if not self.pnl_amount_edit.text().strip():
            self.pnl_amount_edit.setText(f"{pnl_amount:.2f}")
        self.pnl_ratio_label.setText(f"{pnl_ratio:.2f}%")

    def validate_form(self):
        stock_code = self.stock_code_edit.text().strip()
        strategy_type = self.strategy_combo.currentText().strip()
        buy_date = self.buy_date_edit.date().toString("yyyy-MM-dd")
        sell_date = self.sell_date_edit.date().toString("yyyy-MM-dd")
        buy_price = self.parse_float(self.buy_price_edit.text())
        sell_price = self.parse_float(self.sell_price_edit.text())
        buy_shares = self.buy_shares_spin.value()
        manual_pnl = self.parse_float(self.pnl_amount_edit.text())
        if not stock_code:
            QMessageBox.warning(self, "输入错误", "股票代码为必填项。")
            return None
        if not strategy_type:
            QMessageBox.warning(self, "输入错误", "策略类型为必填项。")
            return None
        if buy_price is None or buy_price <= 0 or sell_price is None or sell_price <= 0:
            QMessageBox.warning(self, "输入错误", "买入价格和卖出价格必须为大于0的数字。")
            return None
        if datetime.strptime(sell_date, "%Y-%m-%d") < datetime.strptime(buy_date, "%Y-%m-%d"):
            QMessageBox.warning(self, "输入错误", "卖出日期不能早于买入日期。")
            return None
        auto_pnl = (sell_price - buy_price) * buy_shares
        pnl_amount = manual_pnl if manual_pnl is not None else auto_pnl
        cost = buy_price * buy_shares
        pnl_ratio = (pnl_amount / cost * 100) if cost > 0 else 0.0
        hold_days = (datetime.strptime(sell_date, "%Y-%m-%d") - datetime.strptime(buy_date, "%Y-%m-%d")).days
        hold_days = max(hold_days, 0)
        return {
            "stock_code": stock_code,
            "stock_name": self.stock_name_edit.text().strip(),
            "strategy_type": strategy_type,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "buy_shares": buy_shares,
            "sell_date": sell_date,
            "sell_price": sell_price,
            "hold_days": hold_days,
            "pnl_amount": pnl_amount,
            "pnl_ratio": pnl_ratio,
            "buy_signals": self.buy_signals_edit.text().strip(),
            "sell_signals": self.sell_signals_edit.text().strip(),
            "profit_reasons": self.profit_reasons_edit.text().strip(),
            "error_reasons": self.error_reasons_edit.text().strip(),
            "review_note": self.review_note_edit.toPlainText().strip(),
        }

    def add_trade(self):
        data = self.validate_form()
        if not data:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            """
            INSERT INTO trades (
                stock_code, stock_name, strategy_type, buy_date, buy_price, buy_shares,
                sell_date, sell_price, hold_days, pnl_amount, pnl_ratio, buy_signals,
                sell_signals, profit_reasons, error_reasons, review_note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["stock_code"],
                data["stock_name"],
                data["strategy_type"],
                data["buy_date"],
                data["buy_price"],
                data["buy_shares"],
                data["sell_date"],
                data["sell_price"],
                data["hold_days"],
                data["pnl_amount"],
                data["pnl_ratio"],
                data["buy_signals"],
                data["sell_signals"],
                data["profit_reasons"],
                data["error_reasons"],
                data["review_note"],
                now,
                now,
            ),
        )
        self.conn.commit()
        self.load_trades()
        self.check_error_warning()
        QMessageBox.information(self, "成功", "记录已添加。")

    def update_trade(self):
        if not self.current_trade_id:
            QMessageBox.warning(self, "提示", "请先选择一条记录。")
            return
        data = self.validate_form()
        if not data:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            """
            UPDATE trades SET
                stock_code=?, stock_name=?, strategy_type=?, buy_date=?, buy_price=?, buy_shares=?,
                sell_date=?, sell_price=?, hold_days=?, pnl_amount=?, pnl_ratio=?, buy_signals=?,
                sell_signals=?, profit_reasons=?, error_reasons=?, review_note=?, updated_at=?
            WHERE id=?
            """,
            (
                data["stock_code"],
                data["stock_name"],
                data["strategy_type"],
                data["buy_date"],
                data["buy_price"],
                data["buy_shares"],
                data["sell_date"],
                data["sell_price"],
                data["hold_days"],
                data["pnl_amount"],
                data["pnl_ratio"],
                data["buy_signals"],
                data["sell_signals"],
                data["profit_reasons"],
                data["error_reasons"],
                data["review_note"],
                now,
                self.current_trade_id,
            ),
        )
        self.conn.commit()
        self.load_trades()
        self.check_error_warning()
        QMessageBox.information(self, "成功", "记录已更新。")

    def delete_trade(self):
        if not self.current_trade_id:
            QMessageBox.warning(self, "提示", "请先选择一条记录。")
            return
        if QMessageBox.question(self, "确认", "确定删除选中记录？", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.conn.execute("DELETE FROM trades WHERE id=?", (self.current_trade_id,))
        self.conn.commit()
        self.load_trades()
        self.clear_form()

    def copy_trade(self):
        if not self.current_trade_id:
            QMessageBox.warning(self, "提示", "请先选择一条记录再复制。")
            return
        self.current_trade_id = None
        QMessageBox.information(self, "提示", "已复制到表单，点击“添加记录”可保存为新记录。")

    def clear_form(self):
        self.current_trade_id = None
        self.stock_code_edit.clear()
        self.stock_name_edit.clear()
        if self.strategy_combo.count() > 0:
            self.strategy_combo.setCurrentIndex(0)
        self.buy_date_edit.setDate(QDate.currentDate())
        self.buy_price_edit.clear()
        self.buy_shares_spin.setValue(100)
        self.sell_date_edit.setDate(QDate.currentDate())
        self.sell_price_edit.clear()
        self.hold_days_label.setText("0")
        self.pnl_amount_edit.clear()
        self.pnl_ratio_label.setText("0.00%")
        self.buy_signals_edit.clear()
        self.sell_signals_edit.clear()
        self.profit_reasons_edit.clear()
        self.error_reasons_edit.clear()
        self.review_note_edit.clear()
        self.trade_table.clearSelection()

    def reset_filters(self):
        self.filter_strategy_combo.setCurrentIndex(0)
        self.filter_code_edit.clear()
        self.filter_start_date.setDate(QDate.currentDate().addMonths(-3))
        self.filter_end_date.setDate(QDate.currentDate())
        self.load_trades()

    def fetch_filtered_df(self):
        strategy = self.filter_strategy_combo.currentText().strip()
        stock_code = self.filter_code_edit.text().strip()
        start_date = self.filter_start_date.date().toString("yyyy-MM-dd")
        end_date = self.filter_end_date.date().toString("yyyy-MM-dd")
        query = "SELECT * FROM trades WHERE buy_date BETWEEN ? AND ?"
        params = [start_date, end_date]
        if strategy and strategy != "全部":
            query += " AND strategy_type=?"
            params.append(strategy)
        if stock_code:
            query += " AND stock_code LIKE ?"
            params.append(f"%{stock_code}%")
        query += " ORDER BY sell_date ASC, id ASC"
        return pd.read_sql_query(query, self.conn, params=params)

    def load_trades(self):
        df = self.fetch_filtered_df()
        self.trade_table.setRowCount(len(df))
        for i, row in df.iterrows():
            values = [
                row["id"],
                row["stock_code"],
                row["stock_name"] or "",
                row["strategy_type"],
                row["buy_date"],
                f"{float(row['buy_price']):.3f}",
                int(row["buy_shares"]),
                row["sell_date"],
                f"{float(row['sell_price']):.3f}",
                int(row["hold_days"]),
                f"{float(row['pnl_amount']):.2f}",
                f"{float(row['pnl_ratio']):.2f}",
                row["buy_signals"] or "",
                row["sell_signals"] or "",
                row["profit_reasons"] or "",
                row["error_reasons"] or "",
                row["review_note"] or "",
                row["updated_at"],
            ]
            for col, value in enumerate(values):
                self.trade_table.setItem(i, col, QTableWidgetItem(str(value)))
        self.trade_table.resizeColumnsToContents()
        self.current_trade_id = None
        self.refresh_dashboard(df)

    def on_trade_selected(self):
        items = self.trade_table.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.current_trade_id = int(self.trade_table.item(r, 0).text())
        self.stock_code_edit.setText(self.trade_table.item(r, 1).text())
        self.stock_name_edit.setText(self.trade_table.item(r, 2).text())
        self.strategy_combo.setCurrentText(self.trade_table.item(r, 3).text())
        self.buy_date_edit.setDate(QDate.fromString(self.trade_table.item(r, 4).text(), "yyyy-MM-dd"))
        self.buy_price_edit.setText(self.trade_table.item(r, 5).text())
        self.buy_shares_spin.setValue(int(self.trade_table.item(r, 6).text()))
        self.sell_date_edit.setDate(QDate.fromString(self.trade_table.item(r, 7).text(), "yyyy-MM-dd"))
        self.sell_price_edit.setText(self.trade_table.item(r, 8).text())
        self.hold_days_label.setText(self.trade_table.item(r, 9).text())
        self.pnl_amount_edit.setText(self.trade_table.item(r, 10).text())
        self.pnl_ratio_label.setText(f"{self.trade_table.item(r, 11).text()}%")
        self.buy_signals_edit.setText(self.trade_table.item(r, 12).text())
        self.sell_signals_edit.setText(self.trade_table.item(r, 13).text())
        self.profit_reasons_edit.setText(self.trade_table.item(r, 14).text())
        self.error_reasons_edit.setText(self.trade_table.item(r, 15).text())
        self.review_note_edit.setPlainText(self.trade_table.item(r, 16).text())

    def refresh_dashboard(self, df):
        self.update_cards(df)
        self.update_strategy_stats(df)
        self.update_profit_reason_stats(df)
        self.draw_all_charts(df)

    def update_cards(self, df):
        if df.empty:
            self.total_pnl_card.setText("0.00")
            self.total_count_card.setText("0")
            self.win_rate_card.setText("0.00%")
            self.avg_pl_ratio_card.setText("0.00")
            self.max_profit_card.setText("0.00")
            self.max_drawdown_card.setText("0.00")
            return
        total_pnl = float(df["pnl_amount"].sum())
        total_count = len(df)
        win_rate = (df["pnl_amount"] > 0).sum() / total_count * 100
        avg_profit = df.loc[df["pnl_amount"] > 0, "pnl_amount"].mean()
        avg_loss = abs(df.loc[df["pnl_amount"] < 0, "pnl_amount"].mean())
        avg_profit = 0.0 if pd.isna(avg_profit) else float(avg_profit)
        avg_loss = 0.0 if pd.isna(avg_loss) else float(avg_loss)
        avg_pl_ratio = avg_profit / avg_loss if avg_loss > 0 else 0.0
        self.total_pnl_card.setText(f"{total_pnl:.2f}")
        self.total_count_card.setText(str(total_count))
        self.win_rate_card.setText(f"{win_rate:.2f}%")
        self.avg_pl_ratio_card.setText(f"{avg_pl_ratio:.2f}")
        self.max_profit_card.setText(f"{float(df['pnl_amount'].max()):.2f}")
        self.max_drawdown_card.setText(f"{float(df['pnl_amount'].min()):.2f}")
        self.total_pnl_card.setStyleSheet("color:red;" if total_pnl >= 0 else "color:green;")

    @staticmethod
    def compute_stability_score(group):
        rets = group["pnl_ratio"].astype(float)
        if len(rets) < 2:
            return 0.0
        mean_ret = rets.mean()
        std_ret = rets.std(ddof=1)
        if std_ret <= 0:
            return 0.0
        return float((mean_ret / std_ret) * (len(rets) ** 0.5))

    def update_strategy_stats(self, df):
        if df.empty:
            self.strategy_stats_table.setRowCount(0)
            return
        rows = []
        for strategy, g in df.groupby("strategy_type"):
            count = len(g)
            win_rate = (g["pnl_amount"] > 0).sum() / count * 100
            total_pnl = float(g["pnl_amount"].sum())
            avg_ret = float(g["pnl_ratio"].mean())
            avg_profit = g.loc[g["pnl_amount"] > 0, "pnl_amount"].mean()
            avg_loss = abs(g.loc[g["pnl_amount"] < 0, "pnl_amount"].mean())
            avg_profit = 0.0 if pd.isna(avg_profit) else float(avg_profit)
            avg_loss = 0.0 if pd.isna(avg_loss) else float(avg_loss)
            pl_ratio = avg_profit / avg_loss if avg_loss > 0 else 0.0
            score = self.compute_stability_score(g)
            rows.append((strategy, count, win_rate, total_pnl, avg_ret, pl_ratio, score))
        rows.sort(key=lambda x: x[2], reverse=True)
        self.strategy_stats_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for c, val in enumerate(row):
                text = f"{val:.2f}" if isinstance(val, float) else str(val)
                self.strategy_stats_table.setItem(i, c, QTableWidgetItem(text))
        self.strategy_stats_table.resizeColumnsToContents()

    def update_profit_reason_stats(self, df):
        self.reason_stats_table.setRowCount(0)
        if df.empty:
            return
        exploded = []
        for _, row in df.iterrows():
            reasons = [x.strip() for x in str(row.get("profit_reasons") or "").replace("，", ",").split(",") if x.strip()]
            for reason in reasons:
                exploded.append({"reason": reason, "pnl_ratio": float(row["pnl_ratio"])})
        if not exploded:
            return
        rdf = pd.DataFrame(exploded)
        summary = rdf.groupby("reason").agg(count=("reason", "count"), avg_ret=("pnl_ratio", "mean")).reset_index()
        summary = summary.sort_values("count", ascending=False)
        self.reason_stats_table.setRowCount(len(summary))
        for i, r in summary.iterrows():
            self.reason_stats_table.setItem(i, 0, QTableWidgetItem(str(r["reason"])))
            self.reason_stats_table.setItem(i, 1, QTableWidgetItem(str(int(r["count"]))))
            self.reason_stats_table.setItem(i, 2, QTableWidgetItem(f"{float(r['avg_ret']):.2f}"))
        self.reason_stats_table.resizeColumnsToContents()

    def draw_all_charts(self, df):
        self.draw_equity_curve(df)
        self.draw_monthly_bar(df)
        self.draw_strategy_win_rate_bar(df)
        self.draw_error_reason_pie(df)
        self.draw_profit_reason_pie(df)

    @staticmethod
    def split_multi_text(value):
        return [x.strip() for x in str(value or "").replace("，", ",").split(",") if x.strip()]

    def draw_equity_curve(self, df):
        fig = self.equity_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        if df.empty:
            ax.text(0.5, 0.5, "暂无数据", ha="center", va="center")
            ax.axis("off")
            self.equity_canvas.draw()
            return
        temp = df.copy()
        temp["sell_date"] = pd.to_datetime(temp["sell_date"], errors="coerce")
        temp = temp.dropna(subset=["sell_date"]).sort_values(["sell_date", "id"])
        temp["cum_pnl"] = temp["pnl_amount"].cumsum()
        ax.plot(temp["sell_date"], temp["cum_pnl"], marker="o", linewidth=1.4)
        ax.set_title("累计资金曲线（按日期累计盈亏）")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(True, linestyle="--", alpha=0.4)
        fig.tight_layout()
        self.equity_canvas.draw()

    def draw_monthly_bar(self, df):
        fig = self.monthly_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        if df.empty:
            ax.text(0.5, 0.5, "暂无数据", ha="center", va="center")
            ax.axis("off")
            self.monthly_canvas.draw()
            return
        temp = df.copy()
        temp["sell_date"] = pd.to_datetime(temp["sell_date"], errors="coerce")
        temp = temp.dropna(subset=["sell_date"])
        temp["month"] = temp["sell_date"].dt.to_period("M").astype(str)
        monthly = temp.groupby("month")["pnl_amount"].sum()
        colors = ["#d9534f" if v < 0 else "#5cb85c" for v in monthly.values]
        ax.bar(monthly.index, monthly.values, color=colors)
        ax.set_title("月度盈亏柱状图")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        fig.tight_layout()
        self.monthly_canvas.draw()

    def draw_strategy_win_rate_bar(self, df):
        fig = self.strategy_win_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        if df.empty:
            ax.text(0.5, 0.5, "暂无数据", ha="center", va="center")
            ax.axis("off")
            self.strategy_win_canvas.draw()
            return
        win_rates = df.groupby("strategy_type")["pnl_amount"].apply(lambda s: (s > 0).sum() / len(s) * 100)
        ax.bar(win_rates.index, win_rates.values, color="#4f81bd")
        ax.set_title("策略胜率对比")
        ax.set_ylim(0, 100)
        ax.tick_params(axis="x", rotation=25)
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        fig.tight_layout()
        self.strategy_win_canvas.draw()

    def draw_error_reason_pie(self, df):
        fig = self.error_pie_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        if df.empty:
            ax.text(0.5, 0.5, "暂无数据", ha="center", va="center")
            ax.axis("off")
            self.error_pie_canvas.draw()
            return
        failed = df[df["pnl_amount"] < 0]
        reason_counts = {}
        for v in failed["error_reasons"]:
            for r in self.split_multi_text(v):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        if not reason_counts:
            ax.text(0.5, 0.5, "暂无错误原因数据", ha="center", va="center")
            ax.axis("off")
            self.error_pie_canvas.draw()
            return
        ax.pie(list(reason_counts.values()), labels=list(reason_counts.keys()), autopct="%1.1f%%", startangle=90)
        ax.set_title("错误原因占比（亏损交易）")
        ax.axis("equal")
        fig.tight_layout()
        self.error_pie_canvas.draw()

    def draw_profit_reason_pie(self, df):
        fig = self.profit_pie_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        if df.empty:
            ax.text(0.5, 0.5, "暂无数据", ha="center", va="center")
            ax.axis("off")
            self.profit_pie_canvas.draw()
            return
        win_df = df[df["pnl_amount"] > 0]
        reason_counts = {}
        for v in win_df["profit_reasons"]:
            for r in self.split_multi_text(v):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        if not reason_counts:
            ax.text(0.5, 0.5, "暂无盈利原因数据", ha="center", va="center")
            ax.axis("off")
            self.profit_pie_canvas.draw()
            return
        ax.pie(list(reason_counts.values()), labels=list(reason_counts.keys()), autopct="%1.1f%%", startangle=90)
        ax.set_title("盈利原因占比（盈利交易）")
        ax.axis("equal")
        fig.tight_layout()
        self.profit_pie_canvas.draw()

    def on_strategy_stats_selected(self):
        items = self.strategy_stats_table.selectedItems()
        if not items:
            return
        strategy = self.strategy_stats_table.item(items[0].row(), 0).text()
        df = self.fetch_filtered_df()
        sub = df[df["strategy_type"] == strategy]
        if sub.empty:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"策略明细：{strategy}")
        dialog.resize(1100, 520)
        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(["股票代码", "股票名称", "买入日期", "卖出日期", "股数", "盈亏金额", "收益率(%)", "错误原因"])
        table.setRowCount(len(sub))
        for i, row in sub.reset_index(drop=True).iterrows():
            table.setItem(i, 0, QTableWidgetItem(str(row["stock_code"])))
            table.setItem(i, 1, QTableWidgetItem(str(row["stock_name"] or "")))
            table.setItem(i, 2, QTableWidgetItem(str(row["buy_date"])))
            table.setItem(i, 3, QTableWidgetItem(str(row["sell_date"])))
            table.setItem(i, 4, QTableWidgetItem(str(int(row["buy_shares"]))))
            table.setItem(i, 5, QTableWidgetItem(f"{float(row['pnl_amount']):.2f}"))
            table.setItem(i, 6, QTableWidgetItem(f"{float(row['pnl_ratio']):.2f}"))
            table.setItem(i, 7, QTableWidgetItem(str(row["error_reasons"] or "")))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        dialog.exec_()

    def save_note_for_selected_date(self):
        note_date = self.note_date_edit.date().toString("yyyy-MM-dd")
        content = self.daily_note_text.toPlainText().strip()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not content:
            QMessageBox.warning(self, "提示", "笔记内容为空，未保存。")
            return
        self.conn.execute(
            """
            INSERT INTO daily_notes(note_date, content, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(note_date) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at
            """,
            (note_date, content, now),
        )
        self.conn.commit()
        QMessageBox.information(self, "成功", "复盘笔记已保存。")

    def load_note_for_selected_date(self):
        note_date = self.note_date_edit.date().toString("yyyy-MM-dd")
        row = self.conn.execute("SELECT content FROM daily_notes WHERE note_date=?", (note_date,)).fetchone()
        self.daily_note_text.setPlainText(row["content"] if row else "")

    def check_error_warning(self):
        df = pd.read_sql_query("SELECT sell_date, id, error_reasons FROM trades ORDER BY sell_date ASC, id ASC", self.conn)
        if df.empty:
            return
        streak_reason = None
        streak_count = 0
        for _, row in df.iterrows():
            reasons = self.split_multi_text(row["error_reasons"])
            reason = reasons[0] if reasons else ""
            if not reason:
                streak_reason = None
                streak_count = 0
                continue
            if reason == streak_reason:
                streak_count += 1
            else:
                streak_reason = reason
                streak_count = 1
            if streak_count >= 3:
                key = f"{reason}-{streak_count}-{len(df)}"
                if key != self.last_warning_key:
                    self.last_warning_key = key
                    QMessageBox.warning(self, "错误预警", f"错误“{reason}”已连续出现 {streak_count} 次，请及时反思。")
                return

    def export_csv(self):
        df = self.fetch_filtered_df()
        if df.empty:
            QMessageBox.warning(self, "提示", "当前筛选无数据。")
            return
        default_name = f"trade_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(self, "导出CSV", default_name, "CSV Files (*.csv)")
        if not file_path:
            return
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        QMessageBox.information(self, "成功", f"已导出：\n{file_path}")

    def import_delivery_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "导入交割单CSV", "", "CSV Files (*.csv)")
        if not file_path:
            return
        try:
            try:
                raw = pd.read_csv(file_path, encoding="utf-8-sig")
            except Exception:
                raw = pd.read_csv(file_path, encoding="gbk")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"读取CSV失败：{e}")
            return

        mapping = {
            "证券代码": "stock_code",
            "代码": "stock_code",
            "证券名称": "stock_name",
            "名称": "stock_name",
            "成交日期": "trade_date",
            "日期": "trade_date",
            "买卖标志": "side",
            "买卖": "side",
            "操作": "side",
            "成交价格": "price",
            "价格": "price",
            "成交数量": "shares",
            "数量": "shares",
        }
        raw = raw.rename(columns={c: mapping.get(str(c).strip(), str(c).strip()) for c in raw.columns})
        required = ["stock_code", "stock_name", "trade_date", "side", "price", "shares"]
        missing = [c for c in required if c not in raw.columns]
        if missing:
            QMessageBox.warning(self, "导入失败", f"缺少字段：{', '.join(missing)}")
            return
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        raw["price"] = pd.to_numeric(raw["price"], errors="coerce")
        raw["shares"] = pd.to_numeric(raw["shares"], errors="coerce")
        raw = raw.dropna(subset=["trade_date", "price", "shares"])
        if raw.empty:
            QMessageBox.warning(self, "导入失败", "没有可解析记录。")
            return

        def parse_side(v):
            s = str(v).upper()
            if "买" in s or s == "B" or "BUY" in s:
                return "buy"
            if "卖" in s or s == "S" or "SELL" in s:
                return "sell"
            return ""

        raw["side_parsed"] = raw["side"].map(parse_side)
        raw = raw[raw["side_parsed"] != ""].sort_values("trade_date")
        buys = {}
        inserted = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for _, r in raw.iterrows():
            code = str(r["stock_code"]).strip()
            name = str(r["stock_name"]).strip()
            date = str(r["trade_date"])
            price = float(r["price"])
            shares = int(r["shares"])
            side = r["side_parsed"]
            if shares <= 0 or price <= 0:
                continue
            if side == "buy":
                buys.setdefault(code, []).append({"name": name, "date": date, "price": price, "shares": shares})
                continue
            if code not in buys:
                continue
            while shares > 0 and buys[code]:
                buy_info = buys[code][0]
                matched = min(shares, buy_info["shares"])
                pnl_amount = (price - buy_info["price"]) * matched
                pnl_ratio = (pnl_amount / (buy_info["price"] * matched) * 100) if matched > 0 else 0.0
                hold_days = (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(buy_info["date"], "%Y-%m-%d")).days
                hold_days = max(hold_days, 0)
                self.conn.execute(
                    """
                    INSERT INTO trades (
                        stock_code, stock_name, strategy_type, buy_date, buy_price, buy_shares,
                        sell_date, sell_price, hold_days, pnl_amount, pnl_ratio, buy_signals,
                        sell_signals, profit_reasons, error_reasons, review_note, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        buy_info["name"],
                        "其他",
                        buy_info["date"],
                        buy_info["price"],
                        matched,
                        date,
                        price,
                        hold_days,
                        pnl_amount,
                        pnl_ratio,
                        "CSV导入",
                        "CSV导入",
                        "",
                        "",
                        "交割单自动导入",
                        now,
                        now,
                    ),
                )
                inserted += 1
                shares -= matched
                buy_info["shares"] -= matched
                if buy_info["shares"] <= 0:
                    buys[code].pop(0)
        self.conn.commit()
        self.load_trades()
        QMessageBox.information(self, "导入完成", f"成功导入 {inserted} 条配对交易。")

    def backup_database(self):
        target_path, _ = QFileDialog.getSaveFileName(
            self, "备份数据库", f"trade_review_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db", "DB Files (*.db)"
        )
        if not target_path:
            return
        self.conn.commit()
        self.conn.close()
        try:
            shutil.copyfile(DB_FILE, target_path)
            QMessageBox.information(self, "成功", f"备份完成：\n{target_path}")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"备份失败：{e}")
        finally:
            self.conn = sqlite3.connect(DB_FILE)
            self.conn.row_factory = sqlite3.Row

    def restore_database(self):
        source_path, _ = QFileDialog.getOpenFileName(self, "恢复数据库", "", "DB Files (*.db)")
        if not source_path:
            return
        if QMessageBox.question(self, "确认恢复", "恢复将覆盖当前数据库，是否继续？", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.conn.close()
        try:
            shutil.copyfile(source_path, DB_FILE)
            QMessageBox.information(self, "成功", "数据库恢复完成。")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"恢复失败：{e}")
        finally:
            self.conn = sqlite3.connect(DB_FILE)
            self.conn.row_factory = sqlite3.Row
            self.reload_option_controls()
            self.load_trades()

    def closeEvent(self, event):
        self.conn.close()
        event.accept()


def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    app = QApplication(sys.argv)
    win = TradeReviewApp()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
