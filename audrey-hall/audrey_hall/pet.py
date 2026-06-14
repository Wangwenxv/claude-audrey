import ctypes
from ctypes import wintypes
import os
import time
import win32gui
import win32con
import random
import tkinter as tk
from typing import Any
from screeninfo import get_monitors
from PIL import Image, ImageTk

from .config import load_config, save_config, check_and_fix_startup
from .constants import (
    DEFAULT_SCREEN_INDEX,
    DEFAULT_SCALE_INDEX,
    DEFAULT_TRANSPARENCY_INDEX,
    DEFAULT_WANDER_IDLE_STAY_MODE,
    DEFAULT_VOICE_ENABLED,
    DEFAULT_VOICE_VOLUME,
    EDGE_ESCAPE_CHANCE,
    FOLLOW_DISTANCE,
    FOLLOW_START_DIST,
    FOLLOW_STOP_DIST,
    GIF_DIR,
    GWL_EXSTYLE,
    HWND_BOTTOM,
    HWND_TOPMOST,
    INERTIA_FACTOR,
    INTENT_FACTOR,
    JITTER,
    JITTER_INTERVAL,
    MAX_INTERVAL,
    MIN_INTERVAL,
    MOTION_CURIOUS,
    MOTION_FOLLOW,
    MOTION_REST,
    MOTION_WANDER,
    MOVE_INTERVAL,
    OUTSIDE_TARGET_CHANCE,
    RESPAWN_MARGIN,
    REST_CHANCE,
    REST_DISTANCE,
    REST_DURATION_MAX,
    REST_DURATION_MIN,
    SCALE_OPTIONS,
    SPEED_CURIOUS,
    SPEED_FOLLOW,
    SPEED_WANDER,
    SPEED_X,
    SPEED_Y,
    STAY_PUT_CHANCE,
    STOP_CHANCE,
    STOP_DURATION_MAX,
    STOP_DURATION_MIN,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_SHOWWINDOW,
    TARGET_CHANGE_MAX,
    TARGET_CHANGE_MIN,
    TRANSPARENT_COLOR,
    TRANSPARENCY_OPTIONS,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
)
from .utils import flip_frames, load_gif_frames, resource_path
from .voice import VoicePlayer
from . import window_manager
from .ui import get_theme


def load_static_image_frames(image_path, scale=1.0, frame_count=1, delay=100):
    image = Image.open(image_path).convert('RGBA')
    width, height = image.size
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    if scale < 1.0:
        resample = Image.Resampling.BOX
    else:
        resample = Image.Resampling.LANCZOS
    resized = image.resize((new_width, new_height), resample)
    photo = ImageTk.PhotoImage(resized)
    frames = [photo for _ in range(max(1, frame_count))]
    delays = [delay for _ in range(max(1, frame_count))]
    pil_frames = [resized.copy() for _ in range(max(1, frame_count))]
    return frames, delays, pil_frames


class DesktopGif:
    app: Any = None  # 用于系统托盘

    def __init__(self, root):
        self.root = root
        self._request_quit = False  # 退出标志（主线程统一收尾）
        self.display_priority = 1
        self._hidden_by_fullscreen = False
        self._user_hidden = False  # 用户手动隐藏标志
        self._attached_to_desktop = False  # 是否已挂载到桌面 WorkerW
        self._quick_menu = None  # 快捷菜单实例
        self._bubble_hide_job = None
        self._bubble_theme = get_theme()
        self._bubble_state = 'idle'

        # 立即设置无边框，避免闪烁
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.config(bg=TRANSPARENT_COLOR)
        root.attributes("-transparentcolor", TRANSPARENT_COLOR)

        # 初始化语音播放器
        try:
            self.voice_player = VoicePlayer()
            # 加载语音配置
            voice_config = load_config()
            voice_enabled = voice_config.get("voice_enabled", DEFAULT_VOICE_ENABLED)
            voice_volume = voice_config.get("voice_volume", DEFAULT_VOICE_VOLUME)
            if self.voice_player:
                self.voice_player.set_enabled(voice_enabled)
                self.voice_player.set_volume(voice_volume)
        except Exception:
            self.voice_player = None

        # 加载配置
        config = load_config()
        self.total_screen = config.get("total_screen", True)
        self.screen_index = config.get("screen_index", DEFAULT_SCREEN_INDEX)
        self.scale_index = config.get("scale_index", DEFAULT_SCALE_INDEX)
        self.window_snap = config.get("window_snap", True)
        self.auto_startup = config.get("auto_startup", False)
        self.scale = SCALE_OPTIONS[self.scale_index]
        self.display_priority = config.get("display_priority", 1)
        self.wander_idle_stay_mode = config.get(
            "wander_idle_stay_mode", DEFAULT_WANDER_IDLE_STAY_MODE
        )

        # 捕获窗口的类名，可以用开源工具winspy获取
        self.snap_class_name = ["Notepad", "TXGuiFoundation"]  # 记事本和QQ
        self.snap_class_name_lower = {name.lower() for name in self.snap_class_name}
        # 捕获窗口的窗口名
        # 'AI 对话' 是桌宠自己的 AI 对话窗口标题（见 chat_window.py），
        # 加入后桌宠会像贴靠微信一样自动附着到对话窗口顶部。
        self.snap_window_name = ["微信"]
        self.snap_window_name_lower = {name.lower() for name in self.snap_window_name}
        # 窗口名非精确匹配
        self.snap_window_egg = ["鸣潮"]
        self.snap_window_egg_lower = {name.lower() for name in self.snap_window_egg}

        # 获取屏幕
        monitors = get_monitors()
        if self.screen_index < 0 or self.screen_index + 1 > len(monitors):
            target_monitor = monitors[0]
            print("屏幕设置非法,使用主屏")
            config["screen_index"] = 0
            save_config(config)
        else:
            target_monitor = monitors[self.screen_index]

        # 按屏幕模式获取屏幕高度和宽度
        left = float("inf")
        top = float("inf")
        right = float("-inf")
        bottom = float("-inf")
        if self.total_screen:
            # 多屏模式
            for m in monitors:
                left = min(left, m.x)
                top = min(top, m.y)
                right = max(right, m.x + m.width)
                bottom = max(bottom, m.y + m.height)
        else:
            # 单屏模式
            left = target_monitor.x
            top = target_monitor.y
            right = target_monitor.x + target_monitor.width
            bottom = target_monitor.y + target_monitor.height

        # 可活动区域
        self.screen_x = left
        self.screen_y = top
        self.screen_w = right
        self.screen_h = bottom
        # 检查开机自启路径是否正确（exe移动后自动修复）
        check_and_fix_startup()

        # ---------- 加载所有GIF ----------
        # 加载move.gif (使用 resource_path 支持打包)
        move_path = resource_path(os.path.join(GIF_DIR, "move.gif"))
        self.move_frames, self.move_delays, self.move_pil_frames = load_gif_frames(
            move_path, self.scale
        )
        # 加载翻转的move帧（向左）
        self.move_frames_left = flip_frames(self.move_pil_frames)

        # 只保留 idle2.gif 作为待机动画
        self.idle_gifs = []
        idle_path = resource_path(os.path.join(GIF_DIR, 'idle2.gif'))
        frames, delays, _ = load_gif_frames(idle_path, self.scale)
        self.idle_gifs.append((frames, delays))

        # screen1~7 的特殊效果统一改为 sit.png
        self.screen_gifs = []
        sit_path = resource_path(os.path.join('audrey_hall', 'img', 'sit.png'))
        for _ in range(7):
            frames, delays, _ = load_static_image_frames(sit_path, self.scale, frame_count=1, delay=120)
            self.screen_gifs.append((frames, delays))

        # 加载开场 GIF 序列
        self.open_sequence = []
        for name in ('open1.gif', 'idle2.gif'):
            open_path = resource_path(os.path.join('audrey_hall', 'img', name))
            frames, delays, _ = load_gif_frames(open_path, self.scale)
            if frames:
                duration_ms = sum(delays) if delays else 0
                self.open_sequence.append({
                    'frames': frames,
                    'delays': delays,
                    'duration_ms': duration_ms,
                })

        # 加载paused的GIF
        paused_path = resource_path(os.path.join(GIF_DIR, "idle2.gif"))
        self.paused_frames, self.paused_delays, _ = load_gif_frames(
            paused_path, self.scale
        )

        # 默认 screen 状态也使用 sit.png
        self.screen_frames, self.screen_delays, _ = load_static_image_frames(
            sit_path, self.scale, frame_count=1, delay=120
        )

        self._effect_assets = {
            'working': resource_path(os.path.join('audrey_hall', 'img', 'sit.png')),
            'building': resource_path(os.path.join('audrey_hall', 'img', 'writing.png')),
            'analyzing': resource_path(os.path.join('audrey_hall', 'img', 'thinking.gif')),
            'fetching': resource_path(os.path.join('audrey_hall', 'img', 'search.png')),
            'searching': resource_path(os.path.join('audrey_hall', 'img', 'search.png')),
            'permission': resource_path(os.path.join('audrey_hall', 'img', 'right.png')),
            'chatting': resource_path(os.path.join('audrey_hall', 'img', 'thinking.gif')),
        }
        self._effect_cache = {}

        # 当前状态
        self.current_frames = self.move_frames
        self.current_delays = self.move_delays
        self.is_moving = False
        self.is_paused = True  # 默认以暂停状态启动
        self.is_screen = False  # 窗口捕获状态
        self.is_idle_playing = False
        self.idle_allows_move = False
        self.moving_right = True  # 当前移动方向
        self.frame_index = 0
        self.dragging = False  # 拖动状态
        self.drag_start_x = 0
        self.drag_start_y = 0
        self._pre_drag_frames = None  # 保存拖动前的帧
        self._pre_drag_delays = None
        self._drag_animating = False  # 拖动时是否在播放动画

        # 程序运行使用
        self.old_screen = False  # 窗口捕获状态对比用
        self.screen_anim = None  # 窗口贴靠动画ID
        self.paused_anim = None  # 暂停动画ID
        self._window_check_counter = 0  # 窗口检测帧计数
        self._cached_window_rect = None  # 缓存的窗口矩形
        self._cached_window_info = None  # 缓存的前台窗口信息
        self._last_foreground_signature = None  # 最近一次输出过的前台窗口签名
        self._opening_until = 0
        self._opening_index = 0
        self.window_snap_debug_log = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "audrey_hall_window_debug.log",
        )
        self.paused_x = self.x if hasattr(self, "x") else 0
        self.paused_y = self.y if hasattr(self, "y") else 0

        self.label = tk.Label(root, bg=TRANSPARENT_COLOR, bd=0)
        self.label.pack()

        self.bubble_window = tk.Toplevel(root)
        self.bubble_window.overrideredirect(True)
        self.bubble_window.attributes('-topmost', True)
        self.bubble_window.withdraw()
        self.bubble_window.config(bg=TRANSPARENT_COLOR)
        self.bubble_window.attributes('-transparentcolor', TRANSPARENT_COLOR)

        self._bubble_canvas = tk.Canvas(
            self.bubble_window,
            bg=TRANSPARENT_COLOR,
            bd=0,
            highlightthickness=0,
        )
        self._bubble_canvas.pack()
        self._bubble_bg_photo = None
        self._bubble_image_id = None
        self._bubble_text_id = None
        self._bubble_text_width = 220
        self._init_bubble_surface()

        self.w = self.current_frames[0].width()
        self.h = self.current_frames[0].height()

        # 初始固定在屏幕右下角并上移 100px，避免贴底。
        self.x = self.screen_w - self.w
        self.y = max(self.screen_y, self.screen_h - self.h - 100)
        root.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")

        # 强制刷新，让 winfo_x/y 生效
        root.update_idletasks()

        # 加载鼠标穿透配置并设置
        config = load_config()
        self.click_through = config.get("click_through", True)
        self.follow_mouse = config.get("follow_mouse", False)
        self.set_click_through(self.click_through)

        # 加载透明度配置并设置
        self.transparency_index = config.get(
            "transparency_index", DEFAULT_TRANSPARENCY_INDEX
        )
        self.set_transparency(self.transparency_index)

        self.vx = SPEED_X
        self.vy = SPEED_Y

        # 运动系统：目标点和计时器（立即设置一个随机目标，不要当前位置）
        self.target_x, self.target_y = self.get_random_target()
        self.target_timer = random.randint(TARGET_CHANGE_MIN, TARGET_CHANGE_MAX)

        # 状态机变量
        self.motion_state = MOTION_WANDER  # 当前运动状态
        self.rest_timer = 0  # 休息计时器

        # 绑定拖动事件
        self.label.bind("<ButtonPress-1>", self.start_drag)
        self.label.bind("<B1-Motion>", self.do_drag)
        self.label.bind("<ButtonRelease-1>", self.stop_drag)

        if self.open_sequence:
            total_opening_ms = sum(item['duration_ms'] for item in self.open_sequence)
            self._opening_until = time.time() + total_opening_ms / 1000 if total_opening_ms > 0 else 0
            self._play_opening_sequence(0)
        else:
            self._opening_until = 0
            self.paused()
        self.animate()
        self.move()

        # 获取正确的窗口句柄
        self.root.update_idletasks()
        self.hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

        # 应用显示优先级
        self.set_display_priority(self.display_priority, persist=False)

        # 启动轻量级可见性轮询（替代Shell Hook）
        self.root.after(500, self.ensure_visibility)

        # 启动退出轮询（主线程统一收尾）
        self.root.after(100, self.check_quit)

        # 绑定右键事件
        self.label.bind("<Button-3>", self.handle_right_click)

    def _init_bubble_surface(self):
        bubble_colors = self._bubble_theme['colors']
        bubble_font = self._bubble_theme['fonts']['small']
        bubble_asset = resource_path(os.path.join('audrey_hall', 'img', 'maopao.png'))
        try:
            bubble_image = Image.open(bubble_asset)
            max_width = 360
            if bubble_image.width > max_width:
                scale = max_width / float(bubble_image.width)
                bubble_image = bubble_image.resize(
                    (max_width, max(1, int(bubble_image.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            self._bubble_bg_photo = ImageTk.PhotoImage(bubble_image)
            bubble_width = self._bubble_bg_photo.width()
            bubble_height = self._bubble_bg_photo.height()
            self._bubble_text_width = max(170, int(bubble_width * 0.58))
            self._bubble_canvas.config(width=bubble_width, height=bubble_height)
            self._bubble_image_id = self._bubble_canvas.create_image(
                0,
                0,
                anchor=tk.NW,
                image=self._bubble_bg_photo,
            )
            self._bubble_text_id = self._bubble_canvas.create_text(
                int(bubble_width * 0.43),
                int(bubble_height * 0.42),
                text='',
                font=bubble_font,
                fill=bubble_colors['text'],
                justify=tk.CENTER,
                width=self._bubble_text_width,
                anchor=tk.CENTER,
            )
        except Exception:
            fallback_width = 260
            fallback_height = 92
            self._bubble_text_width = 200
            self._bubble_canvas.config(width=fallback_width, height=fallback_height)
            self._bubble_canvas.create_rectangle(
                1,
                1,
                fallback_width - 1,
                fallback_height - 1,
                fill=bubble_colors['panel'],
                outline=bubble_colors['border'],
                width=1,
            )
            self._bubble_text_id = self._bubble_canvas.create_text(
                fallback_width // 2,
                fallback_height // 2,
                text='',
                font=bubble_font,
                fill=bubble_colors['text'],
                justify=tk.CENTER,
                width=self._bubble_text_width,
                anchor=tk.CENTER,
            )

    def _bubble_text_color(self, status):
        bubble_colors = self._bubble_theme['colors']
        if status == 'permission':
            return bubble_colors.get('accent_dark', bubble_colors['text'])
        if status == 'celebrating':
            return bubble_colors.get('gold_deep', bubble_colors['text'])
        if status in {'building', 'fetching', 'searching', 'analyzing'}:
            return bubble_colors.get('text', '#334B4E')
        if status == 'greeting':
            return bubble_colors.get('accent_dark', bubble_colors['text'])
        return bubble_colors['text']

    def _get_time_greeting_text(self):
        hour = time.localtime().tm_hour
        if 5 <= hour < 11:
            greeting = '早上好'
        elif 11 <= hour < 14:
            greeting = '中午好'
        elif 14 <= hour < 18:
            greeting = '下午好'
        else:
            greeting = '晚上好'
        return f'{greeting}，先生'

    def _get_effect_frames_for_status(self, status):
        asset_path = self._effect_assets.get(status)
        if not asset_path:
            return None

        cache_key = (status, self.scale)
        cached = self._effect_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            if asset_path.lower().endswith('.gif'):
                frames, delays, _ = load_gif_frames(asset_path, self.scale)
            else:
                frames, delays, _ = load_static_image_frames(asset_path, self.scale, frame_count=1, delay=120)
            if frames:
                self._effect_cache[cache_key] = (frames, delays)
                return frames, delays
        except Exception:
            pass
        return None

    def _apply_effect_status(self, status):
        effect = self._get_effect_frames_for_status(status)
        if effect is None:
            return

        frames, delays = effect
        self.current_frames = frames
        self.current_delays = delays
        self.frame_index = 0

    def show_startup_greeting(self):
        try:
            self.root.update_idletasks()
            self._reposition_bubble()
        except Exception:
            pass
        self.set_claude_bubble(
            self._get_time_greeting_text(),
            status='greeting',
            auto_hide_ms=4200,
        )

    def handle_right_click(self, event):
        """
        处理右键点击事件 - 显示快捷菜单

        在小爱旁边显示一个简洁的快捷菜单，包含常用功能。
        """
        from .quick_menu import show_quick_menu
        from .utils import get_version

        # 获取管理器引用
        manager = getattr(self, "manager", None)
        if manager:
            # 如果已有菜单显示中，先关闭
            if self._quick_menu and self._quick_menu.is_visible():
                self._quick_menu._on_close()
            else:
                # 获取托盘图标引用（用于同步更新托盘菜单）
                tray_icon = getattr(self, "app", None)
                # 显示快捷菜单（在鼠标位置附近）
                self._quick_menu = show_quick_menu(
                    self,
                    manager,
                    get_version(),
                    event.x_root,
                    event.y_root,
                    tray_icon=tray_icon,
                )

    def ensure_visibility(self):
        """轻量级可见性轮询（替代Shell Hook）"""
        try:
            # 如果用户手动隐藏，不自动恢复显示
            if self._user_hidden:
                pass
            elif self.display_priority == 1:
                self._apply_topmost()
            elif self.display_priority == 2:
                self._apply_fullscreen_hide()
            else:
                self._apply_desktop_only()
        except Exception:
            pass
        self._reposition_bubble()
        self.root.after(500, self.ensure_visibility)

    def set_claude_bubble(self, text, status='working', auto_hide_ms=None):
        text = (text or '').strip()
        self._bubble_state = status
        if self._bubble_hide_job is not None:
            try:
                self.root.after_cancel(self._bubble_hide_job)
            except Exception:
                pass
            self._bubble_hide_job = None

        if not text:
            self.hide_claude_bubble()
            return

        if status != 'idle':
            self._apply_effect_status(status)

        if self._bubble_text_id is not None:
            self._bubble_canvas.itemconfig(
                self._bubble_text_id,
                text=text,
                fill=self._bubble_text_color(status),
            )
        self._reposition_bubble()
        self.bubble_window.deiconify()
        if auto_hide_ms is not None and int(auto_hide_ms) > 0:
            self._bubble_hide_job = self.root.after(int(auto_hide_ms), self.hide_claude_bubble)

    def hide_claude_bubble(self):
        if self._bubble_hide_job is not None:
            try:
                self.root.after_cancel(self._bubble_hide_job)
            except Exception:
                pass
            self._bubble_hide_job = None
        self._bubble_state = 'idle'
        if self.is_paused:
            self.paused()
        try:
            self.bubble_window.withdraw()
        except Exception:
            pass

    def _reposition_bubble(self):
        try:
            if not self.bubble_window.winfo_exists():
                return
            if self.bubble_window.state() == 'withdrawn':
                return
            self.bubble_window.update_idletasks()
            bubble_w = self.bubble_window.winfo_reqwidth()
            bubble_h = self.bubble_window.winfo_reqheight()
            x = int(self.x + self.w + 10)
            y = int(self.y - bubble_h + 10)
            x = max(int(self.screen_x), min(int(self.screen_w - bubble_w), x))
            y = max(int(self.screen_y), min(int(self.screen_h - bubble_h), y))
            self.bubble_window.geometry(f'+{x}+{y}')
        except Exception:
            pass

    def _apply_topmost(self):
        if self._hidden_by_fullscreen:
            self.root.deiconify()
            self._hidden_by_fullscreen = False
        self.root.attributes("-topmost", True)
        ctypes.windll.user32.SetWindowPos(
            self.hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

    def _apply_fullscreen_hide(self):
        if self._is_fullscreen_window_active():
            if not self._hidden_by_fullscreen:
                self.root.withdraw()
                self._hidden_by_fullscreen = True
            return
        if self._hidden_by_fullscreen:
            self.root.deiconify()
            self._hidden_by_fullscreen = False
        self._apply_topmost()

    def _apply_desktop_only(self):
        """使用 WorkerW 挂载实现"仅桌面显示" - 支持多显示器"""
        if self._hidden_by_fullscreen:
            self.root.deiconify()
            self._hidden_by_fullscreen = False

        # 检查是否已经挂载到桌面（使用实例变量，避免重复挂载）
        if not self._attached_to_desktop:
            # 挂载到桌面 WorkerW
            window_manager.attach_to_desktop(self.hwnd)
            # 设置为工具窗口，隐藏任务栏
            window_manager.make_tool_window(self.hwnd)
            # 保持点击穿透设置
            if self.click_through:
                window_manager.enable_click_through(self.hwnd)
            # 标记为已挂载
            self._attached_to_desktop = True

        # 确保不是 topmost，否则 WorkerW 挂载无效
        self.root.attributes("-topmost", False)

    def _is_desktop_foreground(self):
        if self._hidden_by_fullscreen:
            self.root.deiconify()
            self._hidden_by_fullscreen = False
        if self._is_desktop_foreground():
            self._apply_topmost()
            return
        self.root.attributes("-topmost", False)
        ctypes.windll.user32.SetWindowPos(
            self.hwnd,
            HWND_BOTTOM,
            0,
            0,
            0,
            0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

    def _is_desktop_foreground(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return False
            class_name = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, class_name, 256)
            return class_name.value in {"Progman", "WorkerW"}
        except Exception:
            return False

    def _is_fullscreen_window_active(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd or hwnd == self.hwnd:
                return False
            class_name = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, class_name, 256)
            if class_name.value in {"Progman", "WorkerW"}:
                return False
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            screen_w = self.screen_w
            screen_h = self.screen_h
            return width >= screen_w and height >= screen_h
        except Exception:
            return False

    def check_quit(self):
        """主线程轮询退出标志（确保托盘在主线程正确销毁）"""
        if self._request_quit:
            try:
                if hasattr(self, "app") and self.app:
                    self.app.stop()  # 在主线程 stop 托盘
            except Exception:
                pass
            try:
                self.bubble_window.destroy()
            except Exception:
                pass
            self.root.destroy()
            return
        self.root.after(100, self.check_quit)

    def set_click_through(self, enable):
        """设置鼠标穿透"""
        try:
            # 动态获取窗口句柄
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enable:
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                )
            else:
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT
                )
        except Exception as e:
            print(f"设置鼠标穿透失败: {e}")

    def set_transparency(self, index):
        """设置透明度"""
        self.transparency_index = index
        alpha = TRANSPARENCY_OPTIONS[index]
        self.root.attributes("-alpha", alpha)
        # 保存配置
        config = load_config()
        config["transparency_index"] = index
        save_config(config)

    def set_display_priority(self, mode, persist=True):
        """设置显示优先级"""
        # 记录旧模式
        old_mode = getattr(self, "display_priority", mode)
        self.display_priority = mode
        if persist:
            config = load_config()
            config["display_priority"] = mode
            save_config(config)
        try:
            # 如果用户手动隐藏，不改变窗口可见性
            if self._user_hidden:
                return

            # 如果从桌面模式切换到其他模式，需要先从 WorkerW 分离
            if old_mode == 3 and mode != 3:
                window_manager.detach_from_desktop(self.hwnd)
                self._attached_to_desktop = False

            if self.display_priority == 1:
                self._apply_topmost()
            elif self.display_priority == 2:
                self._apply_fullscreen_hide()
            else:
                self._apply_desktop_only()
        except Exception:
            pass

    def set_wander_idle_stay_mode(self, mode):
        """设置显示优先级"""
        self.display_priority = mode
        if persist:
            config = load_config()
            config["display_priority"] = mode
            save_config(config)
        try:
            # 如果用户手动隐藏，不改变窗口可见性
            if self._user_hidden:
                return
            if self.display_priority == 1:
                self._apply_topmost()
            elif self.display_priority == 2:
                self._apply_fullscreen_hide()
            else:
                self._apply_desktop_only()
        except Exception:
            pass

    def set_wander_idle_stay_mode(self, mode):
        """设置游荡停驻模式"""
        self.wander_idle_stay_mode = mode
        config = load_config()
        config["wander_idle_stay_mode"] = mode
        save_config(config)

    def stop_drag(self, event):
        """停止拖动"""
        self.dragging = False
        # 恢复拖动前的帧
        if self._pre_drag_frames is not None:
            self.current_frames = self._pre_drag_frames
            self.current_delays = self._pre_drag_delays
            self.frame_index = 0

    def _finish_opening(self):
        self._opening_until = 0
        self._opening_index = 0
        if self.dragging:
            return
        self.paused()

    def _play_opening_sequence(self, index: int):
        if index >= len(self.open_sequence):
            self._finish_opening()
            return

        self._opening_index = index
        segment = self.open_sequence[index]
        self.current_frames = segment['frames']
        self.current_delays = segment['delays']
        self.frame_index = 0

        duration_ms = segment['duration_ms'] or 100
        self.root.after(duration_ms, lambda: self._play_opening_sequence(index + 1))

    def set_scale(self, index):
        """设置缩放"""
        self.scale_index = index
        self.scale = SCALE_OPTIONS[index]
        config = load_config()
        config["scale_index"] = index
        save_config(config)

        # 重新加载GIF (使用 resource_path 支持打包)
        move_path = resource_path(os.path.join(GIF_DIR, "move.gif"))
        result = load_gif_frames(move_path, self.scale)
        if result[0]:  # 确保有帧
            self.move_frames, self.move_delays, self.move_pil_frames = result
            self.move_frames_left = flip_frames(self.move_pil_frames)
        else:
            print("加载move.gif失败")
            return

        self.idle_gifs = []
        idle_path = resource_path(os.path.join(GIF_DIR, 'idle2.gif'))
        result = load_gif_frames(idle_path, self.scale)
        if result[0]:
            self.idle_gifs.append((result[0], result[1]))
        # 确保有idle帧可用
        if not self.idle_gifs:
            self.idle_gifs.append((self.move_frames, self.move_delays))

        self.screen_gifs = []
        sit_path = resource_path(os.path.join('audrey_hall', 'img', 'sit.png'))
        for _ in range(7):
            result = load_static_image_frames(sit_path, self.scale, frame_count=1, delay=120)
            if result[0]:
                self.screen_gifs.append((result[0], result[1]))
        # 确保有帧可用
        if not self.screen_gifs:
            self.screen_gifs.append((self.move_frames, self.move_delays))

        # 重新加载paused的GIF
        paused_path = resource_path(os.path.join(GIF_DIR, "idle2.gif"))
        paused_result = load_gif_frames(paused_path, self.scale)
        if paused_result[0]:
            self.paused_frames, self.paused_delays, _ = paused_result

        # 重新加载 screen 特效
        self.screen_frames, self.screen_delays, _ = load_static_image_frames(
            sit_path, self.scale, frame_count=1, delay=120
        )

        self._effect_cache = {}

        # 更新窗口大小
        if self.move_frames:
            self.w = self.move_frames[0].width()
            self.h = self.move_frames[0].height()
            self.root.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

        # 重置帧索引，切换到move帧
        self.frame_index = 0
        self.current_frames = (
            self.move_frames if self.moving_right else self.move_frames_left
        )
        self.current_delays = self.move_delays

    def toggle_pause(self):
        """切换暂停/继续"""
        self.is_paused = not self.is_paused
        if self.is_paused:
            # 暂停：停止移动，切换到暂停模式
            self.paused()
        else:
            # 继续：恢复移动
            self.is_moving = True
            self.current_frames = (
                self.move_frames if self.moving_right else self.move_frames_left
            )
            self.current_delays = self.move_delays
            self.frame_index = 0

    def start_drag(self, event):
        """开始拖动（鼠标穿透关闭时才可用）"""
        if self.click_through:
            return
        self.dragging = True
        # 记录鼠标相对于窗口左上角的偏移量
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        # 保存当前帧状态
        self._pre_drag_frames = self.current_frames
        self._pre_drag_delays = self.current_delays

    def do_drag(self, event):
        """拖动中"""
        if self.dragging:
            # 窗口左上角 = 鼠标当前位置 - 偏移量
            self.x = event.x_root - self.drag_start_x
            self.y = event.y_root - self.drag_start_y
            self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
            self._reposition_bubble()

    def paused(self):
        if self._opening_until and time.time() < self._opening_until:
            return
        self.frame_index = 0
        interval = random.randint(MIN_INTERVAL, MAX_INTERVAL)
        if self.window_snap:
            if self.is_screen:
                self.current_frames = self.screen_frames
                self.current_delays = self.screen_delays
                self.screen_anim = self.root.after(interval, self.paused_to_screen)
                # 取消paused动画
                if self.paused_anim is not None:
                    self.root.after_cancel(self.paused_anim)
                    self.paused_anim = None
            else:
                self.current_frames = self.paused_frames
                self.current_delays = self.paused_delays
                self.paused_anim = self.root.after(interval, self.paused_to_idle)
                # 取消screen动画
                if self.screen_anim is not None:
                    self.root.after_cancel(self.screen_anim)
                    self.screen_anim = None
        else:
            self.current_frames = self.paused_frames
            self.current_delays = self.paused_delays
            self.paused_anim = self.root.after(interval, self.paused_to_idle)
            # 取消screen动画
            if self.screen_anim is not None:
                self.root.after_cancel(self.screen_anim)
                self.screen_anim = None

    def paused_to_idle(self):
        """切换到随机idle状态（暂停状态）"""
        # 播放 idle 动画
        frames, delays = random.choice(self.idle_gifs)
        self.current_frames = frames
        self.current_delays = delays
        self.frame_index = 0
        # 随机停止一段时间后恢复暂停模式
        stop_duration = random.randint(STOP_DURATION_MIN, STOP_DURATION_MAX)
        self.root.after(stop_duration, self.paused)

    def paused_to_screen(self):
        """切换到随机screen状态（暂停状态）"""
        # 播放 screen 动画
        frames, delays = random.choice(self.screen_gifs)
        self.current_frames = frames
        self.current_delays = delays
        self.frame_index = 0
        # 随机停止一段时间后恢复暂停模式
        stop_duration = random.randint(STOP_DURATION_MIN, STOP_DURATION_MAX)
        self.root.after(stop_duration, self.paused)

    def switch_to_idle(self):
        """切换到随机idle状态（随机停下功能）"""
        # 如果是暂停状态跳转paused
        if self.is_paused:
            stop_duration = random.randint(STOP_DURATION_MIN, STOP_DURATION_MAX)
            self.root.after(stop_duration, self.paused)

        self.is_idle_playing = False
        self.idle_allows_move = False

        if self.wander_idle_stay_mode == 0:
            # 始终移动：播放 idle 动画，但继续移动
            self.is_idle_playing = True
            self.idle_allows_move = True
            self.is_moving = True
        elif self.wander_idle_stay_mode == 2:
            # 停驻：始终播放 idle 动画并停留
            self.is_idle_playing = True
            self.idle_allows_move = False
            self.is_moving = False
        else:
            # 概率停驻：0.3 概率播放动画；若播放，0.5 概率停驻/移动
            if random.random() < STAY_PUT_CHANCE:
                self.is_idle_playing = True
                self.idle_allows_move = random.random() >= 0.5
                self.is_moving = self.idle_allows_move
            else:
                # 不播放动画，停在原地
                self.is_idle_playing = False
                self.idle_allows_move = False
                self.is_moving = False

        if self.is_idle_playing:
            frames, delays = random.choice(self.idle_gifs)
            self.current_frames = frames
            self.current_delays = delays
            self.frame_index = 0
        else:
            # 不播放 idle 动画时，显示随机 idle 静帧
            frames, delays = random.choice(self.idle_gifs)
            self.current_frames = frames
            self.current_delays = delays
            self.frame_index = random.randint(0, max(0, len(frames) - 1))

        stop_duration = random.randint(STOP_DURATION_MIN, STOP_DURATION_MAX)
        self.root.after(stop_duration, self.switch_to_move)

    def switch_to_move(self):
        """切换到移动状态"""
        # 如果是暂停状态，不处理
        if self.is_paused:
            return
        self.is_idle_playing = False
        self.idle_allows_move = False
        self.is_moving = True
        self.current_frames = (
            self.move_frames if self.moving_right else self.move_frames_left
        )
        self.current_delays = self.move_delays
        self.frame_index = 0

    def _log_window_snap_debug(self, message):
        """输出 window snap 调试信息，同时写入 APPDATA 日志文件。"""
        line = f"[window_snap {time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        try:
            with open(self.window_snap_debug_log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _describe_show_cmd(self, show_cmd):
        if show_cmd == win32con.SW_SHOWMINIMIZED:
            return "minimized"
        if show_cmd == win32con.SW_SHOWMAXIMIZED:
            return "maximized"
        return f"normal({show_cmd})"

    def _poll_foreground_window(self):
        """轮询当前前台窗口；窗口切换时输出调试信息，并缓存可贴靠窗口。"""
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            signature = (None, None, None)
            if signature != self._last_foreground_signature:
                self._last_foreground_signature = signature
                self._log_window_snap_debug("foreground=<none>")
            self._cached_window_info = None
            self._cached_window_rect = None
            return None

        if not (win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)):
            signature = (hwnd, "<invalid>", "<invalid>")
            if signature != self._last_foreground_signature:
                self._last_foreground_signature = signature
                self._log_window_snap_debug(f"foreground hwnd={hwnd} not visible/valid")
            self._cached_window_info = None
            self._cached_window_rect = None
            return None

        class_name = win32gui.GetClassName(hwnd)
        window_name = win32gui.GetWindowText(hwnd).strip()
        class_name_lower = class_name.lower()
        window_name_lower = window_name.lower()

        class_match = class_name_lower in self.snap_class_name_lower
        title_match = any(name in window_name_lower for name in self.snap_window_name_lower)
        egg_match = any(name in window_name_lower for name in self.snap_window_egg_lower)
        matched = class_match or title_match or egg_match

        rect = None
        show_cmd = None
        is_minimized = False
        is_maximized = False
        if matched:
            try:
                placement = win32gui.GetWindowPlacement(hwnd)
                show_cmd = placement[1]
                is_minimized = show_cmd == win32con.SW_SHOWMINIMIZED
                is_maximized = show_cmd == win32con.SW_SHOWMAXIMIZED
                if not is_minimized:
                    rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                rect = None

        info = {
            "hwnd": hwnd,
            "class_name": class_name,
            "window_name": window_name,
            "matched": matched,
            "class_match": class_match,
            "title_match": title_match,
            "egg_match": egg_match,
            "show_cmd": show_cmd,
            "is_minimized": is_minimized,
            "is_maximized": is_maximized,
            "rect": rect,
        }

        signature = (
            hwnd,
            class_name,
            window_name,
            matched,
            self._describe_show_cmd(show_cmd) if show_cmd is not None else "unknown",
        )
        if signature != self._last_foreground_signature:
            self._last_foreground_signature = signature
            reasons = []
            if class_match:
                reasons.append("class")
            if title_match:
                reasons.append("title")
            if egg_match:
                reasons.append("egg")
            reason_text = ",".join(reasons) if reasons else "none"
            show_text = self._describe_show_cmd(show_cmd) if show_cmd is not None else "unknown"
            self._log_window_snap_debug(
                f"foreground title='{window_name or '<empty>'}' class='{class_name}' "
                f"match={matched} reason={reason_text} show={show_text} rect={rect}"
            )

        self._cached_window_info = info
        self._cached_window_rect = rect if matched and not is_minimized else None
        return info

    def _get_snap_position(self, rect):
        """根据目标窗口矩形计算桌宠贴靠坐标，并限制在屏幕范围内。"""
        left, top, right, bottom = rect
        raw_x = right - self.w
        raw_y = top - self.h + 5
        pet_x = max(self.screen_x, min(self.screen_w - self.w, raw_x))
        pet_y = max(self.screen_y, min(self.screen_h - self.h, raw_y))
        return pet_x, pet_y, raw_x, raw_y

    # 获取目前激活窗口数据
    def get_window_rect_by_title(self):
        info = self._poll_foreground_window()
        if not info:
            return None
        if info["matched"] and info["is_minimized"]:
            self._log_window_snap_debug(
                f"matched window minimized, skip snap: title='{info['window_name']}'"
            )
        return info["rect"] if info["matched"] and not info["is_minimized"] else None

    # ============ 运动系统方法 ============

    def get_random_target(self):
        """获取随机目标点（偶尔在屏幕外，触发边缘效果）"""
        # 使用配置的概率，让宠物尝试冲边界
        if random.random() < OUTSIDE_TARGET_CHANCE:
            side = random.choice(["left", "right", "top", "bottom"])
            margin = RESPAWN_MARGIN + 50  # 比重生距离再远一点
            if side == "left":
                return (-margin, random.randint(self.screen_y, self.screen_h - self.h))
            elif side == "right":
                return (
                    self.screen_w + margin,
                    random.randint(self.screen_y, self.screen_h - self.h),
                )
            elif side == "top":
                return (random.randint(self.screen_x, self.screen_w - self.w), -margin)
            else:  # bottom
                return (
                    random.randint(self.screen_x, self.screen_w - self.w),
                    self.screen_h + margin,
                )
        else:
            return (
                random.randint(self.screen_x, self.screen_w - self.w),
                random.randint(self.screen_y, self.screen_h - self.h),
            )

    def get_follow_target(self):
        """获取跟随鼠标的目标点"""
        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        # 保持一定距离，不要贴脸
        offset = FOLLOW_DISTANCE
        tx = mx + random.randint(-offset, offset)
        ty = my + random.randint(-offset, offset)
        # 限制在屏幕内
        tx = max(self.screen_x, min(self.screen_w - self.w, tx))
        ty = max(self.screen_y, min(self.screen_h - self.h, ty))
        return tx, ty

    def respawn_from_edge(self):
        """从屏幕边缘外侧重生"""
        side = random.choice(["left", "right", "top", "bottom"])
        if side == "left":
            self.x = -RESPAWN_MARGIN
            self.y = random.randint(self.screen_y, self.screen_h - self.h)
        elif side == "right":
            self.x = self.screen_w + RESPAWN_MARGIN
            self.y = random.randint(self.screen_y, self.screen_h - self.h)
        elif side == "top":
            self.y = -RESPAWN_MARGIN
            self.x = random.randint(self.screen_x, self.screen_w - self.w)
        else:  # bottom
            self.y = self.screen_h + RESPAWN_MARGIN
            self.x = random.randint(self.screen_x, self.screen_w - self.w)

        # 给一点入场速度
        self.vx = random.choice([-3, 3])
        self.vy = random.randint(-2, 2)

    def handle_edge(self):
        """处理边缘：反弹或出屏重生"""
        escaped = False

        # 检测是否出屏
        if self.x < self.screen_x or self.x > self.screen_w - self.w:
            escaped = True
        if self.y < self.screen_y or self.y > self.screen_h - self.h:
            escaped = True

        if escaped:
            if random.random() < EDGE_ESCAPE_CHANCE:
                self.respawn_from_edge()
                return True
            else:
                # 反弹
                self.vx = -self.vx
                self.vy = -self.vy
                # 拉回屏幕内
                self.x = max(self.screen_x, min(self.screen_w - self.w, self.x))
                self.y = max(self.screen_y, min(self.screen_h - self.h, self.y))
        return False

    # ============ 动画方法 ============

    def animate(self):
        if not self.current_frames:
            self.root.after(100, self.animate)
            return
        self.label.config(image=self.current_frames[self.frame_index])
        delay = self.current_delays[self.frame_index] if self.current_delays else 100

        self.frame_index = (self.frame_index + 1) % len(self.current_frames)
        self.root.after(delay, self.animate)

    def move(self):
        """运动状态机主循环（性能优化版）"""
        if self._opening_until and time.time() < self._opening_until:
            self.root.after(MOVE_INTERVAL, self.move)
            return
        if self.window_snap:
            # 带间隔检测优化，每5帧约150ms~250ms检测一次前台窗口
            self._window_check_counter += 1
            if self._window_check_counter >= 5:
                self._window_check_counter = 0
                self._poll_foreground_window()

        # 拖动时停止自动运动
        if self.dragging:
            self.root.after(50, self.move)
            return

        # 暂停时停止所有运动并切换对应功能
        if self.is_paused:
            self.root.after(100, self.move)
            if self.window_snap:
                rect = self._cached_window_rect
                if rect:
                    # 记录窗口贴靠前位置
                    if not self.is_screen:
                        self.paused_x = self.x
                        self.paused_y = self.y
                    pet_x, pet_y, raw_x, raw_y = self._get_snap_position(rect)
                    self.root.geometry(f"{self.w}x{self.h}+{int(pet_x)}+{int(pet_y)}")
                    self.is_screen = True
                    cached_title = ""
                    if self._cached_window_info:
                        cached_title = self._cached_window_info.get("window_name", "")
                    if not self.old_screen:
                        self._log_window_snap_debug(
                            f"snap to title='{cached_title}' raw=({raw_x},{raw_y}) clamped=({pet_x},{pet_y})"
                        )
                else:
                    self.is_screen = False
                if self.old_screen != self.is_screen:
                    # 回到窗口贴靠前位置
                    if not self.is_screen:
                        self.root.geometry(
                            f"+{int(self.paused_x)}+{int(self.paused_y)}"
                        )
                        self._log_window_snap_debug(
                            f"leave snap, restore paused position=({int(self.paused_x)},{int(self.paused_y)})"
                        )
                    self.old_screen = self.is_screen
                    self.paused()
            return

        # ============ 随机停下休息（游荡模式专属） ============
        if self.motion_state == MOTION_WANDER and self.is_moving:
            if not self.is_idle_playing and random.random() < STOP_CHANCE:
                self.switch_to_idle()
                self.root.after(MOVE_INTERVAL, self.move)
                return

        # ============ 休息状态 ============
        if self.motion_state == MOTION_REST:
            self.rest_timer -= MOVE_INTERVAL
            if self.rest_timer <= 0:
                # 休息结束，恢复游荡
                self.motion_state = MOTION_WANDER
                self.target_x, self.target_y = self.get_random_target()
                self.target_timer = random.randint(TARGET_CHANGE_MIN, TARGET_CHANGE_MAX)
                self.switch_to_move()
            self.root.after(MOVE_INTERVAL, self.move)
            return

        # idle 播放中保持原地不动
        if not self.is_moving:
            self.root.after(MOVE_INTERVAL, self.move)
            return

        # ============ 鼠标位置缓存 ============
        # 仅在跟随模式启用时查询鼠标位置，避免高频轮询干扰其他应用（如MATLAB）
        mx = my = mouse_moved = None
        if self.follow_mouse:
            mx = self.root.winfo_pointerx()
            my = self.root.winfo_pointery()
            mouse_moved = (mx, my) != getattr(self, "_last_mouse", (mx, my))
            self._last_mouse = (mx, my)

        # ============ 计算到目标的距离 ============
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = (dx * dx + dy * dy) ** 0.5

        # ============ 状态判断与切换 ============

        # 如果关闭了跟随模式，强制重置为游荡模式
        if not self.follow_mouse and self.motion_state in (
            MOTION_FOLLOW,
            MOTION_CURIOUS,
        ):
            self.motion_state = MOTION_WANDER

        # 跟随模式：根据距离切换follow/curious
        if self.follow_mouse:
            dist_mouse = ((mx - self.x) ** 2 + (my - self.y) ** 2) ** 0.5

            if dist_mouse > FOLLOW_START_DIST:
                self.motion_state = MOTION_FOLLOW
            elif dist_mouse < FOLLOW_STOP_DIST:
                self.motion_state = MOTION_CURIOUS

        # 游荡模式：到达目标后决定是否休息
        elif self.motion_state == MOTION_WANDER and dist < REST_DISTANCE:
            if random.random() < REST_CHANCE:
                # 休息一下
                if self.wander_idle_stay_mode == 0:
                    self.target_x, self.target_y = self.get_random_target()
                    self.target_timer = random.randint(
                        TARGET_CHANGE_MIN, TARGET_CHANGE_MAX
                    )
                else:
                    if not self.is_idle_playing:
                        self.motion_state = MOTION_REST
                        self.rest_timer = random.randint(
                            REST_DURATION_MIN, REST_DURATION_MAX
                        )
                        self.switch_to_idle()
                        self.root.after(MOVE_INTERVAL, self.move)
                        return
            else:
                # 继续游荡，换个目标
                self.target_x, self.target_y = self.get_random_target()
                self.target_timer = random.randint(TARGET_CHANGE_MIN, TARGET_CHANGE_MAX)

        # ============ 定时更换目标（仅游荡模式） ============
        if self.motion_state == MOTION_WANDER:
            self.target_timer -= 1
            if self.target_timer <= 0:
                self.target_x, self.target_y = self.get_random_target()
                self.target_timer = random.randint(TARGET_CHANGE_MIN, TARGET_CHANGE_MAX)

        # ============ 计算速度倍率 ============
        if self.motion_state == MOTION_WANDER:
            speed_mul = SPEED_WANDER
        elif self.motion_state == MOTION_FOLLOW:
            speed_mul = SPEED_FOLLOW
        elif self.motion_state == MOTION_CURIOUS:
            speed_mul = SPEED_CURIOUS
        else:
            speed_mul = 1.0

        # ============ 跟随/好奇模式：只在鼠标移动时更新目标 ============
        if self.motion_state in (MOTION_FOLLOW, MOTION_CURIOUS):
            if mouse_moved:  # 只有鼠标移动时才更新目标
                if self.motion_state == MOTION_FOLLOW:
                    offset = FOLLOW_DISTANCE
                else:  # curious
                    offset = FOLLOW_STOP_DIST
                self.target_x = mx + random.randint(-offset, offset)
                self.target_y = my + random.randint(-offset, offset)

                # 重新计算距离
                dx = self.target_x - self.x
                dy = self.target_y - self.y
                dist = max(1, (dx * dx + dy * dy) ** 0.5)

        # ============ 朝目标移动（惯性 + 意图） ============
        desired_vx = dx / dist * SPEED_X * speed_mul
        desired_vy = dy / dist * SPEED_Y * speed_mul

        # 惯性融合
        self.vx = self.vx * INERTIA_FACTOR + desired_vx * INTENT_FACTOR
        self.vy = self.vy * INERTIA_FACTOR + desired_vy * INTENT_FACTOR

        # ============ 抖动降频：每N帧更新一次 ============
        if not hasattr(self, "_move_tick"):
            self._move_tick = 0
        self._move_tick += 1

        if self._move_tick % JITTER_INTERVAL == 0:
            self._jitter_x = random.uniform(-JITTER, JITTER)
            self._jitter_y = random.uniform(-JITTER, JITTER)
        self.vx += getattr(self, "_jitter_x", 0)
        self.vy += getattr(self, "_jitter_y", 0)

        # 应用移动
        self.x += self.vx
        self.y += self.vy

        # ============ 边缘处理 ============
        if not self.handle_edge():
            # 没出屏时才检查边界碰撞
            hit_edge = False
            if self.x <= self.screen_x:
                self.x = self.screen_x
                self.vx = abs(self.vx)  # 向右反弹
                hit_edge = True
            elif self.x + self.w >= self.screen_w:
                self.x = self.screen_w - self.w
                self.vx = -abs(self.vx)  # 向左反弹
                hit_edge = True

            if self.y <= self.screen_y:
                self.y = self.screen_y
                self.vy = abs(self.vy)  # 向下
                hit_edge = True
            elif self.y + self.h >= self.screen_h:
                self.y = self.screen_h - self.h
                self.vy = -abs(self.vy)  # 向上
                hit_edge = True

            # 撞边时更新方向状态
            new_moving_right = self.vx > 0.5
            new_moving_left = self.vx < -0.5

            if self.is_idle_playing:
                hit_edge = False
            if new_moving_right and not self.moving_right and not self.is_idle_playing:
                self.moving_right = True
                self.current_frames = self.move_frames
                self.current_delays = self.move_delays
                self.frame_index = 0
            elif new_moving_left and self.moving_right and not self.is_idle_playing:
                self.moving_right = False
                self.current_frames = self.move_frames_left
                self.current_delays = self.move_delays
                self.frame_index = 0

        # 只在位置明显变化时更新geometry
        ix, iy = int(self.x), int(self.y)
        last_pos = getattr(self, "_last_pos", None)
        if (ix, iy) != last_pos:
            self.root.geometry(f"+{ix}+{iy}")
            self._last_pos = (ix, iy)

        self.root.after(MOVE_INTERVAL, self.move)
