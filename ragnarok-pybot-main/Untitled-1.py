import sys
import os
import time
import math
import ctypes
import struct
from ctypes import windll, wintypes
import tkinter as tk
from tkinter import messagebox

# 強迫 Windows 啟用 DPI 意識
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    ctypes.windll.user32.SetProcessDPIAware()

current_dir = os.path.dirname(os.path.abspath(__file__))
helpers_path = os.path.join(current_dir, "helpers")
sys.path.insert(0, helpers_path)

# 引入基礎模組
try:
    from process import Process
    from addresses import *
except ImportError as e:
    print(f"錯誤：無法載入基礎 helpers 模組，原因: {e}")
    sys.exit(1)

# 自建獨立坐標類別
class LocalCoordinate:
    def __init__(self, x, y):
        self.x = int(x)
        self.y = int(y)

    def distance_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt((dx * dx) + (dy * dy))

# =======================================================
# ✨ 本地自動化 GAT 二進位解析器與 DLL 尋路銜接器
# =======================================================
class LocalGatNavigator:
    def __init__(self):
        self.lib = self.load_library()
        self.map_width = 0
        self.map_height = 0
        self.map_data_list = []
        self.current_map = ""

    def load_library(self):
        lib_path = os.path.abspath("./helpers/shortest_path.dll")
        if not os.path.exists(lib_path):
            return None
        return ctypes.windll.LoadLibrary(lib_path)

    def load_gat_file(self, map_name):
        if not map_name:
            return False
        if map_name == self.current_map and len(self.map_data_list) > 0:
            return True
            
        file_path = os.path.join(current_dir, "maps", f"{map_name}.gat")
        if not os.path.exists(file_path):
            print(f"警告：找不到地圖數據 {file_path}")
            self.map_data_list = []
            return False
            
        try:
            with open(file_path, 'rb') as f:
                f.seek(6)
                self.map_width, self.map_height = struct.unpack('<II', f.read(8))
                
                total_cells = self.map_width * self.map_height
                self.map_data_list = [0] * total_cells
                
                for i in range(total_cells):
                    block_data = f.read(20)
                    if not block_data:
                        break
                    block_type = block_data[16]
                    if block_type not in (0, 3):
                        self.map_data_list[i] = 1
                        
            self.current_map = map_name
            print(f"成功自動加載地圖: {map_name}.gat (大小: {self.map_width}x{self.map_height})")
            return True
        except Exception as e:
            print(f"解析 GAT 失敗: {e}")
            self.map_data_list = []
            return False

class PathMetadata(ctypes.Structure):
    _fields_ = [("path", ctypes.POINTER(ctypes.c_int32)), ("size", ctypes.c_size_t)]


class RagnarokUltimateGUINavigator:
    def __init__(self):
        self.proc = Process()
        self.memory = self.proc.memory
        self.base = self.proc.base
        self.handle = None
        self.is_walking = False
        
        self.navigator = LocalGatNavigator()
        self.MAP_NAME = ""
        
        self.current_path = []
        self.script_queue = []  
        self.current_script_index = 0  
        self.last_click_time = 0
        
        # 1440x900 的中心點
        self.auto_cx = 720  
        self.auto_cy = 450  
        
        # DPI 縮放比例
        hdc = windll.user32.GetDC(0)
        LOGPIXELSX = 88
        self.dpi_scale = windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX) / 96.0
        windll.user32.ReleaseDC(0, hdc)

        # 介面繪製
        self.root = tk.Tk()
        self.root.title("Ragnarok A* 尋路 (自動腳本排程終極狂飆版)")
        self.root.geometry("750x480")
        self.root.configure(bg="#f5f5f5")

        ui_font = ("Microsoft JhengHei", 12)
        title_font = ("Microsoft JhengHei", 16, "bold")
        small_font = ("Microsoft JhengHei", 10)

        # 頂部狀態顯示
        top_frame = tk.Frame(self.root, bg="#f5f5f5")
        top_frame.pack(side="top", fill="x", pady=10)
        
        self.coord_label = tk.Label(top_frame, text="目前位置: X=0 Y=0", font=title_font, bg="#f5f5f5", fg="#333333")
        self.coord_label.pack()

        self.window_info = tk.Label(top_frame, text="地圖偵測中... 請進入遊戲", font=ui_font, bg="#f5f5f5", fg="#1B5E20")
        self.window_info.pack(pady=2)

        # 左側：加入腳本框區域
        left_container = tk.LabelFrame(self.root, text=" 📜 加入腳本框 (執行排程列表) ", font=ui_font, bg="#f5f5f5", fg="#333333")
        left_container.pack(side="left", fill="both", expand=True, padx=15, pady=10)

        self.script_box = tk.Listbox(left_container, font=("Consolas", 12), bg="white", fg="#222222", selectbackground="#2196F3")
        self.script_box.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(left_container, orient="vertical", command=self.script_box.yview)
        self.script_box.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        # 右側：控制面板區域
        right_container = tk.LabelFrame(self.root, text=" ⚙️ 移動 X . Y 控制面板 ", font=ui_font, bg="#f5f5f5", fg="#333333")
        right_container.pack(side="right", fill="both", padx=15, pady=10)

        input_frame = tk.Frame(right_container, bg="#f5f5f5")
        input_frame.pack(pady=10, padx=10)

        tk.Label(input_frame, text="目標 X 座標:", font=ui_font, bg="#f5f5f5").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.target_x = tk.Entry(input_frame, width=10, font=ui_font)
        self.target_x.grid(row=0, column=1, padx=5, pady=5)
        self.target_x.insert(0, "61")

        tk.Label(input_frame, text="目標 Y 座標:", font=ui_font, bg="#f5f5f5").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.target_y = tk.Entry(input_frame, width=10, font=ui_font)
        self.target_y.grid(row=1, column=1, padx=5, pady=5)
        self.target_y.insert(0, "205")

        ctrl_btn_frame = tk.Frame(right_container, bg="#f5f5f5")
        ctrl_btn_frame.pack(pady=5)

        tk.Button(ctrl_btn_frame, text="➕ 填入並加入腳本", command=self.add_to_script, 
                  height=1, width=16, font=small_font, bg="#4CAF50", fg="white", relief="flat").grid(row=0, column=0, padx=3, pady=3)
        
        tk.Button(ctrl_btn_frame, text="❌ 刪除所選座標", command=self.delete_selected_script, 
                  height=1, width=16, font=small_font, bg="#FF5722", fg="white", relief="flat").grid(row=0, column=1, padx=3, pady=3)

        tk.Button(ctrl_btn_frame, text="🎯 複製當前位置", command=self.catch_current_coords, 
                  height=1, width=16, font=small_font, bg="#9C27B0", fg="white", relief="flat").grid(row=1, column=0, padx=3, pady=3)

        tk.Button(ctrl_btn_frame, text="🗑️ 清空整份腳本", command=self.clear_all_script, 
                  height=1, width=16, font=small_font, bg="#795548", fg="white", relief="flat").grid(row=1, column=1, padx=3, pady=3)

        self.walk_btn = tk.Button(right_container, text="🚀 啟動自動腳本導航 (F5)", command=self.toggle_walk, 
                 height=2, width=26, font=("Microsoft JhengHei", 12, "bold"), bg="#2196F3", fg="white", relief="flat")
        self.walk_btn.pack(pady=15, padx=10)

        self.status = tk.Label(right_container, text="狀態: 準備就緒", fg="#1976D2", bg="#f5f5f5", font=ui_font)
        self.status.pack(pady=5)

        self.check_f5_key()
        self.update_gui_loop()

    def add_to_script(self):
        try:
            tx = int(self.target_x.get())
            ty = int(self.target_y.get())
            self.script_queue.append((tx, ty))
            step_num = len(self.script_queue)
            self.script_box.insert(tk.END, f"站點 {step_num:02d} ➔ X: {tx:<4} Y: {ty}")
            self.status.config(text=f"已成功加入站點 {step_num}：({tx}, {ty})")
        except:
            messagebox.showerror("錯誤", "請確認輸入的座標是正確的數字！")

    def delete_selected_script(self):
        try:
            index = self.script_box.curselection()[0]
            self.script_box.delete(index)
            del self.script_queue[index]
            self.status.config(text="已刪除指定站點")
            self.rebuild_listbox_ui()
        except:
            pass

    def clear_all_script(self):
        self.script_queue = []
        self.script_box.delete(0, tk.END)
        self.current_script_index = 0
        self.status.config(text="腳本清單已完全清空")

    def rebuild_listbox_ui(self):
        self.script_box.delete(0, tk.END)
        for i, (tx, ty) in enumerate(self.script_queue):
            self.script_box.insert(tk.END, f"站點 {(i+1):02d} ➔ X: {tx:<4} Y: {ty}")

    def check_f5_key(self):
        VK_F5 = 0x74
        if windll.user32.GetAsyncKeyState(VK_F5) & 0x8000:
            self.toggle_walk()
            time.sleep(0.3) 
        self.root.after(100, self.check_f5_key)

    def get_window_handle(self):
        if not self.handle:
            titles = ["PartyRO", "Ragnarok", "RO", "神之谷", "Rag_Classic"]
            for t in titles:
                main_hwnd = windll.user32.FindWindowW(None, t)
                if main_hwnd:
                    self.handle = main_hwnd
                    break
        return self.handle

    def check_window_exists(self):
        return self.get_window_handle() is not None

    def get_coords(self):
        try:
            x = self.memory.read_u_int(self.base + PLAYER_COORDINATE_X_OFFSET)
            y = self.memory.read_u_int(self.base + PLAYER_COORDINATE_Y_OFFSET)
            return int(x), int(y)
        except:
            return 0, 0

    def get_memory_map_name(self):
        try:
            map_bytes = self.memory.read_bytes(self.base + MAP_NAME_OFFSET, 16)
            map_name = map_bytes.split(b'\x00')[0].decode('utf-8', errors='ignore')
            if map_name.endswith('.gat'):
                map_name = map_name[:-4]
            return map_name
        except:
            return ""

    def update_coords(self):
        x, y = self.get_coords()
        self.coord_label.config(text=f"目前位置: X={x} Y={y}")
        m_name = self.get_memory_map_name()
        if m_name and m_name != self.MAP_NAME:
            self.MAP_NAME = m_name
            self.navigator.load_gat_file(self.MAP_NAME)
            self.window_info.config(text=f"自動偵測地圖：{self.MAP_NAME}.gat (尋路網格已對齊)")
        return x, y

    def catch_current_coords(self):
        x, y = self.get_coords()
        if x != 0 or y != 0:
            self.target_x.delete(0, tk.END)
            self.target_x.insert(0, str(x))
            self.target_y.delete(0, tk.END)
            self.target_y.insert(0, str(y))
            self.status.config(text=f"已複製當前位置 ({x}, {y})")
        else:
            self.status.config(text="❌ 無法獲取當前座標")

    def calculate_dll_route(self, tx, ty):
        if not self.navigator.lib or len(self.navigator.map_data_list) == 0:
            self.current_path = []
            return
        cx, cy = self.get_coords()
        dx = tx - cx
        dy = ty - cy
        full_dist = math.sqrt((dx * dx) + (dy * dy))
        if full_dist > 20.0:
            scale = 20.0 / full_dist
            tx = int(cx + dx * scale)
            ty = int(cy + dy * scale)
        map_array = (ctypes.c_int32 * len(self.navigator.map_data_list))(*self.navigator.map_data_list)
        self.navigator.lib.My_ShortestPath.restype = PathMetadata
        result = self.navigator.lib.My_ShortestPath(
            map_array, self.navigator.map_width, self.navigator.map_height,
            cx, cy, tx, ty
        )
        self.current_path = [result.path[i:i+2] for i in range(0, result.size, 2)]

    def toggle_walk(self):
        if self.is_walking:
            self.is_walking = False
            self.walk_btn.config(text="🚀 啟動自動腳本導航 (F5)", bg="#2196F3")
            self.status.config(text="狀態: 腳本導航已手動停止 (F5)")
            self.current_path = []
        else:
            if not self.check_window_exists():
                messagebox.showerror("錯誤", "找不到遊戲視窗，請確認遊戲已開啟！")
                return
            if len(self.script_queue) == 0:
                messagebox.showwarning("提示", "左側腳本框內目前沒有任何座標！請先在右邊輸入並加入腳本！")
                return
            self.is_walking = True
            self.walk_btn.config(text="🛑 停止腳本導航 (F5)", bg="#F44336")
            self.current_script_index = 0
            self.update_coords()
            tx, ty = self.script_queue[self.current_script_index]
            self.calculate_dll_route(tx, ty)
            self.auto_walk_loop()

    def auto_walk_loop(self):
        if not self.is_walking: return
        current_x, current_y = self.get_coords()
        if current_x == 0 and current_y == 0:
            self.status.config(text="❌ 記憶體座標中斷，停止導航")
            self.toggle_walk()
            return

        if self.current_script_index >= len(self.script_queue):
            self.status.config(text="🎉 恭喜！整份自動化腳本排程已全部執行完畢！")
            self.toggle_walk()
            return

        tx, ty = self.script_queue[self.current_script_index]

        if abs(tx - current_x) <= 1 and abs(ty - current_y) <= 1:
            self.current_script_index += 1
            self.current_path = []
            if self.current_script_index >= len(self.script_queue):
                self.status.config(text="🎉 恭喜！整份自動化腳本排程已全部執行完畢！")
                self.toggle_walk()
                return
            tx, ty = self.script_queue[self.current_script_index]
            self.calculate_dll_route(tx, ty)

        if len(self.current_path) == 0:
            self.calculate_dll_route(tx, ty)

        if self.current_path and len(self.current_path) > 0:
            next_x = self.current_path[0][0]
            next_y = self.current_path[0][1]
            player_coord = LocalCoordinate(current_x, current_y)
            current_dest = LocalCoordinate(next_x, next_y)

            if player_coord.distance_to(current_dest) <= 1.5 and len(self.current_path) > 1:
                del self.current_path[:1]
                next_x = self.current_path[0][0]
                next_y = self.current_path[0][1]
            else:
                lead_index = min(12, len(self.current_path) - 1)
                next_x = self.current_path[lead_index][0]
                next_y = self.current_path[lead_index][1]

            step_dx = next_x - current_x
            step_dy = next_y - current_y
            mode_text = f"【⚡腳本第 {self.current_script_index+1} 站狂飆中】"
        else:
            dx = tx - current_x
            dy = ty - current_y
            dist = math.sqrt((dx * dx) + (dy * dy))
            if dist > 0:
                step_dx = (dx / dist) * 12.0
                step_dy = (dy / dist) * 12.0
            else:
                step_dx, step_dy = 0, 0
            mode_text = "【⚡腳本幾何盲走補償】"

        gw = 32.0
        gh = 32.0
        screen_dx = step_dx * gw
        screen_dy = -step_dy * gh

        MAX_PIXEL_RADIUS = 240.0
        click_dist = math.sqrt((screen_dx * screen_dx) + (screen_dy * screen_dy))

        if click_dist > MAX_PIXEL_RADIUS:
            scale_factor = MAX_PIXEL_RADIUS / click_dist
            screen_dx *= scale_factor
            screen_dy *= scale_factor

        click_x = self.auto_cx + screen_dx
        click_y = self.auto_cy + screen_dy

        hwnd = self.get_window_handle()
        rect = wintypes.RECT()
        windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

        screen_absolute_x = rect.left + int(click_x)
        screen_absolute_y = rect.top + int(click_y)

        final_x = int(screen_absolute_x / self.dpi_scale)
        final_y = int(screen_absolute_y / self.dpi_scale)

        now = time.time()
        if now - self.last_click_time > 0.30:
            windll.user32.SetForegroundWindow(hwnd)
            windll.user32.SetCursorPos(final_x, final_y)
            MOUSEEVENTF_LEFTDOWN = 0x0002
            MOUSEEVENTF_LEFTUP = 0x0004
            windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.01)
            windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            self.last_click_time = now

        self.script_box.see(self.current_script_index)
        self.script_box.selection_clear(0, tk.END)
        try:
            self.script_box.selection_set(self.current_script_index)
        except:
            pass

        rem_dx = tx - current_x
        rem_dy = ty - current_y
        remain_dist = int(math.sqrt((rem_dx * rem_dx) + (rem_dy * rem_dy)))
        self.status.config(text=f"{mode_text} 離本站剩餘: {remain_dist} 格\n目標站點: ({tx},{ty})")

        self.root.after(100, self.auto_walk_loop)

    def update_gui_loop(self):
        self.update_coords()
        self.root.after(600, self.update_gui_loop)

    def run(self):
        if not ctypes.windll.shell32.IsUserAnAdmin():
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                f'"{os.path.abspath(file)}"', None, 1)
            sys.exit(0)
        self.root.mainloop()


if __name__ == "__main__":
    gui = RagnarokUltimateGUINavigator()
    gui.run()
