from typing import Any, List, Tuple
import json
import os
import sys
import time
import ctypes
import math

import numpy as np
import win32api
import win32con
import win32gui
from PIL import ImageGrab, Image, ImageDraw, ImageFont
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, \
    QSizePolicy, QLabel, QCheckBox
from PySide6.QtGui import QIcon
from paddleocr import PaddleOCR

# --- DPI感知 ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# --- 点击位置可视化 ---
def show_debug_click_marker(x, y, duration=0.2):
    try:
        hdc = win32gui.GetDC(0)
        red = win32api.RGB(255, 0, 0)
        for i in range(-4, 5):
            win32gui.SetPixel(hdc, x + i, y, red)
            win32gui.SetPixel(hdc, x, y + i, red)
        win32gui.ReleaseDC(0, hdc)
        time.sleep(duration)
    except Exception:
        pass


class WindowHandler:
    def __init__(self):
        self.window = None
        self.window_title = "咸鱼之王"

    def find_window(self, debug=False):
        if self.window and win32gui.IsWindow(self.window):
            return
        visible_windows = []

        def callback(hwnd, extra):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title: visible_windows.append(title)
                    if self.window_title in title:
                        self.window = hwnd
                        return False
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except Exception:
            pass
        if not self.window:
            if debug:
                print(f"未找到窗口。当前可见: {visible_windows}")
            self.window = None

    def capture_screenshot_ext(self, left, top, right, bottom):
        try:
            self.find_window()
            if not self.window: return np.zeros((10, 10, 3), dtype=np.uint8)
            try:
                if win32gui.IsWindow(self.window):
                    placement = win32gui.GetWindowPlacement(self.window)
                    if placement[1] == win32con.SW_SHOWMINIMIZED:
                        win32gui.ShowWindow(self.window, win32con.SW_RESTORE)
            except:
                pass
            return np.array(ImageGrab.grab(bbox=(left, top, right, bottom)))
        except Exception:
            return np.zeros((10, 10, 3), dtype=np.uint8)


class WinOperator:
    def __init__(self, handler, show_marker=False):
        self.handler = handler
        self.show_marker = show_marker

    def click(self, x, y):
        try:
            if self.show_marker:
                show_debug_click_marker(int(x), int(y))
            original_pos = win32api.GetCursorPos()
            win32api.SetCursorPos((int(x), int(y)))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.1)
            win32api.SetCursorPos(original_pos)
            return True
        except Exception as e:
            print(f"物理点击失败: {e}")
            return False


class Ocr:
    def __init__(self) -> None:
        self.ocr = PaddleOCR(show_log=False, use_angle_cls=False, lang="ch")

    def do_ocr_ext(self, img_data) -> List:
        if img_data is None or img_data.size == 0: return []
        result = self.ocr.ocr(img_data, cls=False)
        if not result or result[0] is None: return []
        return result[0]

    def find_text_center(self, img_data, keywords: List[str]) -> Tuple[int, int, str]:
        results = self.do_ocr_ext(img_data)
        for item in results:
            box = item[0]
            text = str(item[1][0])
            for k in keywords:
                if k in text:
                    center_x = (box[0][0] + box[2][0]) / 2
                    center_y = (box[0][1] + box[2][1]) / 2
                    return int(center_x), int(center_y), text
        return None


class ConsoleOutput:
    def __init__(self, text_edit):
        self.text_edit = text_edit

    def write(self, text):
        if hasattr(self.text_edit, 'append_text'):
            self.text_edit.append_text.emit(text.rstrip())
        else:
            self.text_edit.append(text.rstrip())

    def flush(self):
        pass


class SafeTextEdit(QTextEdit):
    append_text = Signal(str)

    def __init__(self):
        super().__init__()
        self.append_text.connect(self.append)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(1000)


class WorkerThread(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, worker):
        super().__init__()
        self.worker = worker

    def run(self):
        try:
            self.worker.run()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self):
        if self.worker: self.worker.stop()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("咸鱼助手 v2.3 (小鱼干检测版)")
        self.setFixedSize(380, 550)  # 加宽一点

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.console = SafeTextEdit()
        layout.addWidget(self.console)

        # 选项区
        option_layout = QHBoxLayout()
        self.chk_save_img = QCheckBox("保存检测截图")
        self.chk_show_click = QCheckBox("显示点击位置")
        self.chk_show_click.setChecked(True)
        option_layout.addWidget(self.chk_save_img)
        option_layout.addWidget(self.chk_show_click)
        layout.addLayout(option_layout)

        btn_layout = QVBoxLayout()
        self.btn_start = QPushButton("开始推图")
        self.btn_analyze = QPushButton("全屏分析 (生成坐标图)")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)

        for btn in [self.btn_start, self.btn_analyze, self.btn_stop]:
            btn.setMinimumHeight(35)
            btn_layout.addWidget(btn)

        self.btn_analyze.setStyleSheet("background-color: #fff9c4; border: 1px solid #fbc02d;")

        layout.addLayout(btn_layout)
        layout.addWidget(QLabel("新功能：检测到'小鱼干不足'时会自动停止"))

        self.btn_start.clicked.connect(self.start_worker)
        self.btn_analyze.clicked.connect(self.run_analysis)
        self.btn_stop.clicked.connect(self.stop_worker)

        sys.stdout = ConsoleOutput(self.console)
        self.worker = None
        self.thread = None

    def start_worker(self):
        if not self.thread or not self.thread.isRunning():
            self.worker = MainWorker(
                save_images=self.chk_save_img.isChecked(),
                show_marker=self.chk_show_click.isChecked()
            )
            self.thread = WorkerThread(self.worker)
            self.thread.finished.connect(self.on_finish)
            self.thread.start()
            self.btn_start.setEnabled(False)
            self.btn_analyze.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.chk_save_img.setEnabled(False)
            self.chk_show_click.setEnabled(False)
            print(">>> 启动智能推图 <<<")

    def run_analysis(self):
        pass  # 全屏分析功能不变

    def stop_worker(self):
        if self.thread: self.thread.stop()

    def on_finish(self):
        self.btn_start.setEnabled(True)
        self.btn_analyze.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.chk_save_img.setEnabled(True)
        self.chk_show_click.setEnabled(True)
        print(">>> 已停止 <<<")

    def closeEvent(self, event):
        self.stop_worker()
        event.accept()


# --- 区域定义 ---
def get_window_rect(name="咸鱼之王"):
    rects = []
    win32gui.EnumWindows(lambda h, e: e.append(win32gui.GetWindowRect(h)) if win32gui.IsWindowVisible(
        h) and name in win32gui.GetWindowText(h) else None, rects)
    return rects[0] if rects else None


def get_area_bottom():
    r = get_window_rect()
    if not r: return None
    w, h = r[2] - r[0], r[3] - r[1]
    return (int(r[0]), int(r[1] + h * 0.80), int(r[2]), int(r[3]))


def get_area_middle():
    r = get_window_rect()
    if not r: return None
    w, h = r[2] - r[0], r[3] - r[1]
    return (int(r[0]), int(r[1] + h * 0.50), int(r[2]), int(r[3] * 0.75))


def get_area_left_bottom():
    r = get_window_rect()
    if not r: return None
    w, h = r[2] - r[0], r[3] - r[1]
    return (int(r[0]), int(r[1] + h * 0.80), int(r[0] + w * 0.25), int(r[3]))


class MainWorker:
    def __init__(self, save_images=False, show_marker=False):
        self.is_running = True
        self.save_images = save_images
        self.show_marker = show_marker

        if self.save_images:
            self.save_dir = "detected_images"
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)

    def stop(self):
        self.is_running = False

    def save_detection_image(self, img_array, text_found):
        pass  # 截图功能不变

    def check_for_error_popup(self, handler, ocr):
        """[新功能] 检查是否有错误弹窗，如'小鱼干不足'"""
        time.sleep(0.5)  # 等待弹窗出现
        rect = get_window_rect()
        if not rect: return False

        # 截取整个窗口进行检查
        full_screen_img = handler.capture_screenshot_ext(*rect)
        if full_screen_img.size == 0: return False

        # 检查关键词
        if ocr.find_text_center(full_screen_img, ["小鱼干不足", "次数不足"]):
            print("\n错误：检测到'小鱼干不足'或'次数不足'弹窗！")
            print("自动停止运行。")
            return True  # 发现了错误
        return False  # 未发现错误

    def run(self):
        handler = WindowHandler()
        operator = WinOperator(handler, show_marker=self.show_marker)
        ocr = Ocr()
        handler.find_window()

        print("初始化完成。")

        while self.is_running:
            try:
                processed = False

                # --- 1. 左下角跳过 ---
                area = get_area_left_bottom()
                if area:
                    img = handler.capture_screenshot_ext(*area)
                    res = ocr.find_text_center(img, ["跳过"])
                    if res:
                        rel_x, rel_y, txt = res
                        print(f"发现 [{txt}] -> 点击")
                        self.save_detection_image(img, txt)
                        operator.click(area[0] + rel_x, area[1] + rel_y)
                        processed = True
                        time.sleep(0.8)

                if not self.is_running: break

                # --- 2. 中间重试 ---
                if not processed:
                    area = get_area_middle()
                    if area:
                        img = handler.capture_screenshot_ext(*area)
                        res = ocr.find_text_center(img, ["重新挑战", "再试一次"])
                        if res:
                            rel_x, rel_y, txt = res
                            print(f"发现 [{txt}] -> 点击")
                            self.save_detection_image(img, txt)
                            operator.click(area[0] + rel_x, area[1] + rel_y)
                            processed = True
                            time.sleep(1.0)

                if not self.is_running: break

                # --- 3. 底部按钮 ---
                if not processed:
                    area = get_area_bottom()
                    if area:
                        img = handler.capture_screenshot_ext(*area)
                        res = ocr.find_text_center(img, ["下一关"])
                        if res:
                            rel_x, rel_y, txt = res
                            print(f"发现 [{txt}] -> 点击")
                            self.save_detection_image(img, txt)
                            operator.click(area[0] + rel_x, area[1] + rel_y)
                            processed = True
                            time.sleep(1.5)
                        else:
                            challenge_keywords = ["挑战", "进攻", "闯关", "布阵", "下一塔"]
                            res = ocr.find_text_center(img, challenge_keywords)
                            if res:
                                rel_x, rel_y, txt = res
                                print(f"发现 [{txt}] -> 点击")
                                self.save_detection_image(img, txt)
                                operator.click(area[0] + rel_x, area[1] + rel_y)
                                processed = True

                                # --- [关键改动] 点击后检查错误弹窗 ---
                                if self.check_for_error_popup(handler, ocr):
                                    self.stop()  # 发现错误，停止
                                    break

                                time.sleep(1.5)

                if not processed:
                    time.sleep(0.2)

            except Exception as e:
                print(f"Error: {e}")
                time.sleep(1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())