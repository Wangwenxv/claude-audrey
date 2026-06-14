"""
Audrey Hall 快捷菜单模块

本模块提供右键点击奥黛丽时显示的快捷菜单，包括：
- 演出开始/结束（音乐播放控制）
- 暂停/继续
- 鼠标穿透
- 更多设置（打开完整设置窗口）

通过菜单项列表配置，可扩展
"""

import math
import os
import tkinter as tk
import tkinter.font as tkfont
import ctypes
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

from PIL import Image, ImageTk

from .config import load_config, save_config
from .utils import resource_path
from .ui import animate_toplevel_slide_in, create_card, get_theme


class QuickMenuItem:
    """
    快捷菜单项基类
    
    用于定义菜单项的结构和行为，支持扩展自定义菜单项。
    """
    
    def __init__(
        self,
        label: Any = "",
        callback: Optional[Callable] = None,
        check_callback: Optional[Callable[[], bool]] = None,
        enabled_callback: Optional[Callable[[], bool]] = None,
        is_separator: bool = False,
    ):
        self.label = label
        self.callback = callback
        self.check_callback = check_callback
        self.enabled_callback = enabled_callback
        self.is_separator = is_separator
    
    def get_label(self) -> str:
        """获取显示文本"""
        if callable(self.label):
            return self.label()
        return self.label
    
    def is_checked(self) -> bool:
        """检查是否应该显示勾选状态"""
        if self.check_callback:
            return self.check_callback()
        return False
    
    def is_enabled(self) -> bool:
        """检查菜单项是否可用"""
        if self.enabled_callback:
            return self.enabled_callback()
        return True

    def matches_label(self, text: str) -> bool:
        return self.get_label() == text


class QuickContextMenu:
    """
    快捷菜单类
    
    在奥黛丽旁边显示一个简洁的快捷操作菜单。
    """
    
    def __init__(self, pet, manager, version: str, tray_icon=None):
        """
        初始化快捷菜单
        
        Args:
            pet: DesktopGif 实例
            manager: PetManager 实例
            version: 版本号字符串
            tray_icon: 托盘图标实例（用于同步更新托盘菜单）
        """
        self.pet = pet
        self.manager = manager
        self.version = version
        self.tray_icon = tray_icon  # 托盘图标引用
        
        # 记录菜单打开前的暂停状态
        self._was_paused_before = False
        # 标记是否是菜单自动触发的临时暂停
        self._was_temporarily_paused = False
        
        # 窗口引用
        self.window: Optional[tk.Toplevel] = None
        self._menu_canvas: Optional[tk.Canvas] = None
        self._bg_image_id: Optional[int] = None
        self._menu_bg_image = None
        self._menu_bg_offset_x = 0
        self._menu_bg_offset_y = 0
        self._surface_backgrounds: List[Dict[str, Any]] = []
        
        # 加载样式配置
        self._load_styles()
        self._load_header_bg()
        
        # 构建菜单项列表
        self._build_menu_items()
    
    def _load_styles(self):
        """加载样式配置（与完整设置页保持一致）"""
        self.theme = get_theme()
        self.colors = self.theme['colors']
        self.fonts = {
            'title': self.theme['fonts']['menu_title'],
            'base': self.theme['fonts']['menu_item'],
            'base_strong': (*self.theme['fonts']['menu_item'][:2], 'bold'),
            'small': self.theme['fonts']['caption'],
        }
        self.menu_theme = self.theme['menu']
        self.window_theme = self.theme['windows']['menu']
    
    def _load_header_bg(self):
        """加载菜单栏背景图"""
        bg_path = os.path.join(os.path.dirname(__file__), 'img', 'menu.png')
        if os.path.isfile(bg_path):
            self._header_bg_source = Image.open(bg_path)
            self._header_bg = None
        else:
            self._header_bg_source = None
            self._header_bg = None

    def _update_menu_bg(self, event=None):
        """按菜单容器尺寸缩放背景图"""
        if not self._header_bg_source or self._menu_canvas is None:
            return

        if event is not None:
            width = event.width
            height = event.height
        else:
            width = self._menu_canvas.winfo_width()
            height = self._menu_canvas.winfo_height()

        if width <= 1 or height <= 1:
            return

        source_width, source_height = self._header_bg_source.size
        scale = min(width / source_width, height / source_height)
        resized_width = max(1, int(source_width * scale))
        resized_height = max(1, int(source_height * scale))
        resized = self._header_bg_source.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
        self._menu_bg_image = resized
        self._menu_bg_offset_x = (width - resized_width) // 2
        self._menu_bg_offset_y = (height - resized_height) // 2
        self._header_bg = ImageTk.PhotoImage(resized)
        if self._bg_image_id is None:
            self._bg_image_id = self._menu_canvas.create_image(self._menu_bg_offset_x, self._menu_bg_offset_y, anchor='nw', image=self._header_bg)
        else:
            self._menu_canvas.itemconfigure(self._bg_image_id, image=self._header_bg)
            self._menu_canvas.coords(self._bg_image_id, self._menu_bg_offset_x, self._menu_bg_offset_y)
        self._menu_canvas.tag_lower(self._bg_image_id)

        for surface in self._surface_backgrounds:
            self._refresh_surface_background(surface)

    def _register_surface_background(self, canvas: tk.Canvas, x: int, y: int, width: int, height: int):
        image_id = canvas.create_image(0, 0, anchor='nw')
        surface = {
            'canvas': canvas,
            'x': x,
            'y': y,
            'width': width,
            'height': height,
            'image_id': image_id,
            'photo': None,
        }
        self._surface_backgrounds.append(surface)
        self._refresh_surface_background(surface)
        return surface

    def _refresh_surface_background(self, surface):
        if self._menu_bg_image is None:
            return

        x = surface['x'] - self._menu_bg_offset_x
        y = surface['y'] - self._menu_bg_offset_y
        width = surface['width']
        height = surface['height']
        background = Image.new('RGBA', (width, height), (0, 0, 0, 0))

        src_left = max(0, x)
        src_top = max(0, y)
        src_right = min(self._menu_bg_image.width, x + width)
        src_bottom = min(self._menu_bg_image.height, y + height)

        if src_right > src_left and src_bottom > src_top:
            crop = self._menu_bg_image.crop((src_left, src_top, src_right, src_bottom))
            paste_x = max(0, -x)
            paste_y = max(0, -y)
            background.paste(crop, (paste_x, paste_y))

        photo = ImageTk.PhotoImage(background)
        surface['photo'] = photo
        surface['canvas'].itemconfigure(surface['image_id'], image=photo)
        surface['canvas'].tag_lower(surface['image_id'])

    def _shift_surface_backgrounds(self, dx: int, dy: int):
        for surface in self._surface_backgrounds:
            surface['x'] += dx
            surface['y'] += dy

    def _build_menu_items(self):
        """构建菜单项列表"""
        self.menu_items: List[QuickMenuItem] = []
        
        # 音乐控制
        self.menu_items.append(QuickMenuItem(
            label=self._get_music_label,
            callback=self._toggle_music,
            enabled_callback=self._is_music_enabled,
        ))
        
        self.menu_items.append(QuickMenuItem(is_separator=True))
        
        # 行为控制
        self.menu_items.append(QuickMenuItem(
            label="鼠标穿透",
            callback=self._toggle_click_through,
            check_callback=lambda: self.manager.click_through,
        ))
        
        self.menu_items.append(QuickMenuItem(is_separator=True))
        
        # 显示控制
        self.menu_items.append(QuickMenuItem(
            label=self._get_visible_label,
            callback=self._toggle_visible,
        ))
        
        self.menu_items.append(QuickMenuItem(is_separator=True))
        
        # 其他
        self.menu_items.append(QuickMenuItem(
            label=self._get_chat_label,
            callback=self._open_chat,
        ))

        self.menu_items.append(QuickMenuItem(is_separator=True))

        self.menu_items.append(QuickMenuItem(
            label="更多设置...",
            callback=self._open_settings,
        ))
        
        self.menu_items.append(QuickMenuItem(
            label="退出",
            callback=self._quit,
        ))
    
    # ========================================================================
    # 菜单项回调方法
    # ========================================================================
    
    def _get_music_label(self) -> str:
        """获取音乐控制按钮的显示文本"""
        config = load_config()
        music_enabled = config.get("music_enabled", False)
        
        if not music_enabled:
            return "🎵 音乐（未启用）"
        
        from .music_player import MusicPlayer
        if MusicPlayer._shared_is_playing and not MusicPlayer._shared_is_paused:
            title = self._truncate_menu_text(MusicPlayer._shared_song_name or "有声小说", 200)
            return f"⏹ {title}"
        else:
            return "▶ 有声小说"

    def _get_music_meta_text(self) -> str:
        from .music_player import MusicPlayer
        if MusicPlayer._shared_is_playing and not MusicPlayer._shared_is_paused:
            return '正在执行'
        if MusicPlayer._shared_is_paused:
            return '已暂停'
        return '点击执行'

    def _truncate_menu_text(self, text: str, max_px: int) -> str:
        value = (text or '').strip()
        if not value:
            return ''
        try:
            font = self.fonts['base_strong']
            probe = tkfont.Font(font=font)
            if probe.measure(value) <= max_px:
                return value
            ellipsis = '...'
            while value and probe.measure(value + ellipsis) > max_px:
                value = value[:-1]
            return (value + ellipsis) if value else ellipsis
        except Exception:
            return value[:18] + ('...' if len(value) > 18 else '')
    
    def _is_music_enabled(self) -> bool:
        """检查音乐播放器是否启用"""
        config = load_config()
        return config.get("music_enabled", False)
    
    def _toggle_music(self):
        """切换音乐播放状态"""
        config = load_config()
        music_enabled = config.get("music_enabled", False)
        
        if not music_enabled:
            return
        
        from .music_player import MusicPlayer

        if getattr(MusicPlayer, '_shared_backend', '') == 'mci':
            alias = 'ameath_story_player'
            if MusicPlayer._shared_is_playing and not MusicPlayer._shared_is_paused:
                self._mci_command(f'pause {alias}')
                MusicPlayer._shared_is_playing = False
                MusicPlayer._shared_is_paused = True
            elif MusicPlayer._shared_current_file:
                self._mci_command(f'resume {alias}')
                MusicPlayer._shared_is_playing = True
                MusicPlayer._shared_is_paused = False
            self._update_tray_menu()
            return

        music_dir = resource_path('sound/music')
        files = []
        if os.path.exists(music_dir):
            files = [
                os.path.join(music_dir, name)
                for name in sorted(os.listdir(music_dir))
                if name.lower().endswith(('.wma', '.mp3', '.wav'))
            ]
        if files:
            current_file = MusicPlayer._shared_current_file if getattr(MusicPlayer, '_shared_current_file', '') in files else files[0]
            alias = 'ameath_story_player'
            if self._mci_command(f'open "{current_file.replace(chr(34), chr(34) * 2)}" alias {alias}') == 0:
                self._mci_command(f'set {alias} time format milliseconds')
                self._mci_command(f'setaudio {alias} volume to {MusicPlayer._shared_music_volume * 10}')
                if self._mci_command(f'play {alias}') == 0:
                    MusicPlayer._shared_backend = 'mci'
                    MusicPlayer._shared_current_file = current_file
                    MusicPlayer._shared_music_files = files
                    MusicPlayer._shared_current_index = files.index(current_file)
                    MusicPlayer._shared_song_name = Path(current_file).stem
                    MusicPlayer._shared_is_playing = True
                    MusicPlayer._shared_is_paused = False
                    self._update_tray_menu()
                    return
                self._mci_command(f'close {alias}')
        
        # 获取或创建 MusicPlayer 单例实例
        player = MusicPlayer._instance
        
        if player is None:
            # 创建隐藏的 Frame 作为 parent，初始化后台播放器
            hidden_frame = tk.Frame(self.pet.root)
            player = MusicPlayer(parent=hidden_frame, position_unlock_callback=None)
        
        # 确保有音乐文件列表
        if not player.music_files:
            player.load_music_files_internal()
        
        if not player.music_files:
            return
        
        # 调用实际的播放控制方法
        if player.is_playing and not player.is_paused:
            # 正在播放 -> 暂停
            player.pause_event.set()
            player.is_playing = False
            player.is_paused = True
            player._sync_to_shared()
        else:
            # 未播放或已暂停 -> 开始播放
            if player.current_index < 0 or player.current_index >= len(player.music_files):
                player.current_index = 0
            
            if player.is_paused and player.audio_data is not None:
                # 恢复播放
                player.pause_event.clear()
                player.is_playing = True
                player.is_paused = False
                player._sync_to_shared()
            else:
                # 开始新播放
                player.play_current_track()
        
        # 更新托盘菜单状态
        self._update_tray_menu()

    def _mci_command(self, command: str) -> int:
        try:
            return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
        except Exception:
            return -1
    
    def _get_pause_label(self) -> str:
        """获取暂停按钮的显示文本"""
        # 如果是临时暂停状态，显示"暂停"（用户可以点击来真正暂停）
        # 如果是用户暂停状态，显示"继续"
        if self._was_temporarily_paused:
            return "⏸ 暂停"
        if self.pet.is_paused:
            return "▶ 继续"
        return "⏸ 暂停"
    
    def _toggle_pause(self):
        """切换暂停状态"""
        if self._was_temporarily_paused:
            # 当前是菜单临时暂停状态，用户点击"暂停"意味着要真正暂停
            # 取消临时暂停标记，让关闭菜单时不恢复运动
            self._was_temporarily_paused = False
            self._was_paused_before = True  # 标记为用户意图暂停
            # pet.is_paused 已经是 True，切换到正面idle帧
            self.pet.paused()  # 调用 paused() 切换到正面idle帧
            self.manager._sync_state_from_primary()
        elif self._was_paused_before:
            # 打开菜单前已经是暂停状态，用户点击"继续"
            # 调用 manager.toggle_pause 恢复运动
            self.manager.toggle_pause()
            self._was_paused_before = False
        else:
            # 正常情况（不应该到这里，但保留作为保险）
            self.manager.toggle_pause()
        self._update_tray_menu()
    
    def _toggle_click_through(self):
        """切换鼠标穿透"""
        self.manager.set_click_through(not self.manager.click_through)
        config = load_config()
        config["click_through"] = self.manager.click_through
        save_config(config)
        self._update_tray_menu()
    
    def _get_visible_label(self) -> str:
        """获取显示/隐藏按钮的显示文本"""
        if self.manager.is_visible():
            return "👁 隐藏"
        return "👁 显示"

    def _get_chat_label(self) -> str:
        """获取 AI 对话菜单文本"""
        return '与奥黛丽聊聊'
    
    def _toggle_visible(self):
        """切换显示/隐藏"""
        if self.manager.is_visible():
            self.manager.hide_all()
        else:
            self.manager.show_all()
        self._update_tray_menu()
    
    def _open_settings(self):
        """打开完整设置窗口"""
        from .settings import show_settings_dialog
        show_settings_dialog(self.pet.root, self.manager, self.version)

    def _open_chat(self):
        """打开 AI 对话窗口"""
        from .chat_window import show_chat_dialog

        show_chat_dialog(self.pet.root, self.manager, self.version)
    
    def _quit(self):
        """退出程序"""
        self.manager.request_quit()
    
    def _update_tray_menu(self):
        """更新托盘菜单（同步状态）"""
        if self.tray_icon is not None:
            try:
                # 重新创建菜单以反映新状态
                new_menu = self._create_tray_menu()
                self.tray_icon.menu = new_menu
                # 刷新托盘图标以显示更新后的菜单
                self.tray_icon.update_menu()
            except Exception:
                pass
    
    def _create_tray_menu(self):
        """创建托盘菜单（内部方法）"""
        import pystray
        
        def on_toggle_visible(icon, item):
            if self.manager.is_visible():
                self.manager.hide_all()
            else:
                self.manager.show_all()
            icon.menu = self._create_tray_menu()
        
        def on_toggle_pause(icon, item):
            self.manager.toggle_pause()
            icon.menu = self._create_tray_menu()
        
        def on_toggle_click_through(icon, item):
            self.manager.set_click_through(not self.manager.click_through)
            config = load_config()
            config["click_through"] = self.manager.click_through
            save_config(config)
            icon.menu = self._create_tray_menu()
        
        def on_settings(icon, item):
            from .settings import show_settings_dialog
            show_settings_dialog(self.pet.root, self.manager, self.version)

        def on_chat(icon, item):
            from .chat_window import show_chat_dialog

            show_chat_dialog(self.pet.root, self.manager, self.version)
        
        def on_quit(icon):
            self.manager.request_quit()
        
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: "隐藏" if self.manager.is_visible() else "显示",
                on_toggle_visible,
            ),
            pystray.MenuItem(
                lambda item: "暂停" if not self.manager.is_paused else "继续",
                on_toggle_pause,
            ),
            pystray.MenuItem(
                "鼠标穿透",
                on_toggle_click_through,
                checked=lambda it: self.manager.click_through,
            ),
            pystray.MenuItem("与奥黛丽聊聊", on_chat),
            pystray.MenuItem("设置", on_settings),
            pystray.MenuItem("退出", on_quit),
        )
    
    # ========================================================================
    # 菜单显示方法
    # ========================================================================
    
    def show(self, x: int, y: int):
        """
        在指定位置显示快捷菜单
        
        Args:
            x: 屏幕 X 坐标
            y: 屏幕 Y 坐标
        """
        # 如果菜单已存在，先关闭它（恢复临时暂停状态）
        if self.window is not None and self.window.winfo_exists():
            self._on_close()  # 正确关闭并恢复状态
        
        # 记录菜单打开前的暂停状态
        self._was_paused_before = self.pet.is_paused
        self._was_temporarily_paused = False
        
        # 如果奥黛丽未暂停，先临时暂停它（保持当前姿态）
        if not self._was_paused_before:
            self._was_temporarily_paused = True
            # 直接设置暂停状态，保持当前帧不变
            self.pet.is_paused = True
            self.pet.is_moving = False
            # 取消任何待执行的动画切换
            if self.pet.paused_anim is not None:
                self.pet.root.after_cancel(self.pet.paused_anim)
                self.pet.paused_anim = None
            if self.pet.screen_anim is not None:
                self.pet.root.after_cancel(self.pet.screen_anim)
                self.pet.screen_anim = None
        
        # 创建顶层窗口
        self.window = tk.Toplevel(self.pet.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=self.colors['gold_deep'])
        
        # 绑定关闭时恢复状态
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # 创建内容容器
        content_frame = tk.Canvas(
            self.window,
            bg=self.colors['gold_deep'],
            highlightthickness=0,
            bd=0,
        )
        content_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._menu_canvas = content_frame

        if self._header_bg_source:
            content_frame.bind('<Configure>', self._update_menu_bg, add='+')

        outer_pad_x = 50
        outer_pad_y = 130

        header_metrics = self._create_header(content_frame, outer_pad_x, outer_pad_y)
        content_width = max(380, header_metrics['width'] + self.menu_theme['header_pad_x'] * 2)

        current_y = outer_pad_y + self.menu_theme['header_pad_y']
        current_y += header_metrics['height'] + 8

        current_y = self._create_menu_items(content_frame, outer_pad_x, current_y, content_width)

        content_bounds_width = content_width + outer_pad_x * 2
        content_bounds_height = current_y + outer_pad_y

        if self._header_bg_source:
            image_width, image_height = self._header_bg_source.size
            image_ratio = image_width / image_height
            canvas_width = max(content_bounds_width, math.ceil(content_bounds_height * image_ratio))
            canvas_height = max(content_bounds_height, math.ceil(canvas_width / image_ratio))

            if canvas_width / canvas_height > image_ratio:
                canvas_height = max(content_bounds_height, math.ceil(canvas_width / image_ratio))
            else:
                canvas_width = max(content_bounds_width, math.ceil(canvas_height * image_ratio))
        else:
            canvas_width = content_bounds_width
            canvas_height = content_bounds_height

        shift_x = max(0, (canvas_width - content_bounds_width) // 2)
        shift_y = max(0, (canvas_height - content_bounds_height) // 2)

        if shift_x or shift_y:
            content_frame.move('all', shift_x, shift_y)
            self._shift_surface_backgrounds(shift_x, shift_y)

        content_frame.configure(width=canvas_width, height=canvas_height)
        if self._header_bg_source:
            content_frame.after(0, self._update_menu_bg)
        
        # 计算窗口位置
        self.window.update_idletasks()
        window_width = self.window.winfo_width()
        window_height = self.window.winfo_height()
        
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        
        # 确保窗口在屏幕内
        if x + window_width > screen_width:
            x = screen_width - window_width - self.window_theme['screen_margin']
        if y + window_height > screen_height:
            y = screen_height - window_height - self.window_theme['screen_margin']
        
        animate_toplevel_slide_in(
            self.window,
            x,
            y,
            window_width,
            window_height,
            offset_y=self.window_theme['slide_offset_y'],
            steps=self.window_theme['slide_steps'],
            interval_ms=self.window_theme['slide_interval_ms'],
        )
        
        # 绑定 Escape 键关闭
        self.window.bind("<Escape>", lambda e: self._on_close())
        
        # 点击窗口本身不关闭
        self.window.bind("<Button-1>", lambda e: None)
        
        # 绑定失去焦点时关闭
        self.window.bind("<FocusOut>", self._on_focus_out)
        
        # 聚焦窗口（不使用 grab_set，以便能检测点击外部）
        self.window.focus_force()
        
        # 延迟绑定全局点击检测（避免立即触发）
        self.window.after(100, self._bind_global_click)
    
    def _on_focus_out(self, event):
        """失去焦点时关闭菜单"""
        # 延迟检查，避免窗口刚打开时误触发
        self.window.after(50, self._check_focus)
    
    def _check_focus(self):
        """检查焦点状态"""
        if self.window is None or not self.window.winfo_exists():
            return
        # 如果焦点不在菜单窗口内，关闭菜单
        try:
            focus_widget = self.window.focus_get()
            if focus_widget is None or focus_widget.master != self.window:
                self._on_close()
        except Exception:
            pass
    
    def _on_close(self):
        """菜单关闭时的处理"""
        # 如果是菜单自动触发的临时暂停，恢复运动
        if self._was_temporarily_paused and self.pet.is_paused:
            self.pet.is_paused = False
            self.pet.is_moving = True
            # 恢复移动帧
            self.pet.current_frames = (
                self.pet.move_frames if self.pet.moving_right else self.pet.move_frames_left
            )
            self.pet.current_delays = self.pet.move_delays
            self.pet.frame_index = 0
            # 同步 manager 状态
            self.manager._sync_state_from_primary()
        
        self.hide()

    def _create_header(self, parent, outer_pad_x: int, outer_pad_y: int):
        title_font = tkfont.Font(font=self.fonts['title'])
        base_font = tkfont.Font(font=self.fonts['base'])
        small_font = tkfont.Font(font=self.fonts['small'])

        eyebrow_text = 'AURORA CONTROL'
        title_text = self.menu_theme['title_text']
        subtitle_text = self.menu_theme['subtitle_text']
        version_text = f'v{self.version}'

        inner_pad_x = self.menu_theme['title_pad_x']
        inner_pad_y = self.menu_theme['title_pad_y']
        header_width = max(
            360,
            inner_pad_x * 2 + title_font.measure(title_text) + base_font.measure(subtitle_text) + small_font.measure(version_text) + 96,
        )
        header_height = inner_pad_y * 2 + small_font.metrics('linespace') + title_font.metrics('linespace') + base_font.metrics('linespace') + 18

        header_canvas = tk.Canvas(
            parent,
            width=header_width,
            height=header_height,
            highlightthickness=0,
            bd=0,
            bg=self.colors['gold_deep'],
        )
        self._register_surface_background(
            header_canvas,
            outer_pad_x + self.menu_theme['header_pad_x'],
            outer_pad_y + self.menu_theme['header_pad_y'],
            header_width,
            header_height,
        )

        y = inner_pad_y
        header_canvas.create_text(
            inner_pad_x,
            y,
            text=eyebrow_text,
            font=self.fonts['small'],
            fill=self.colors['gold_soft'],
            anchor='nw',
        )
        y += small_font.metrics('linespace') + 6

        badge_width = small_font.measure(version_text) + 20
        badge_height = small_font.metrics('linespace') + 8
        badge_x = header_width - inner_pad_x - badge_width
        header_canvas.create_text(
            inner_pad_x,
            y,
            text=title_text,
            font=self.fonts['title'],
            fill=self.colors['white'],
            anchor='nw',
        )
        header_canvas.create_text(
            inner_pad_x + title_font.measure(title_text) + 10,
            y + 3,
            text=subtitle_text,
            font=self.fonts['base'],
            fill=self.colors['accent_soft'],
            anchor='nw',
        )
        header_canvas.create_rectangle(
            badge_x,
            y,
            badge_x + badge_width,
            y + badge_height,
            fill=self.colors['gold_soft'],
            outline='',
        )
        header_canvas.create_text(
            badge_x + badge_width / 2,
            y + badge_height / 2,
            text=version_text,
            font=self.fonts['small'],
            fill=self.colors['gold_deep'],
        )

        parent.create_window(
            outer_pad_x + self.menu_theme['header_pad_x'],
            outer_pad_y + self.menu_theme['header_pad_y'],
            anchor='nw',
            window=header_canvas,
            width=header_width,
            height=header_height,
        )
        return {'width': header_width, 'height': header_height}
    
    def _create_menu_items(self, parent, start_x: int, start_y: int, width: int) -> int:
        """创建菜单项组件"""
        current_y = start_y
        for item in self.menu_items:
            if item.is_separator:
                separator = tk.Frame(parent, bg=self.colors["gold_soft"], height=1)
                parent.create_window(
                    start_x + self.menu_theme['separator_pad_x'],
                    current_y + self.menu_theme['separator_pad_y'],
                    anchor='nw',
                    window=separator,
                    width=width - self.menu_theme['separator_pad_x'] * 2,
                )
                current_y += self.menu_theme['separator_pad_y'] * 2 + 1
            else:
                button_height = self._create_menu_button(parent, item, start_x, current_y, width)
                current_y += button_height
        return current_y
    
    def _create_menu_button(self, parent, item: QuickMenuItem, start_x: int, start_y: int, width: int) -> int:
        """创建单个菜单按钮"""
        label = item.get_label()
        is_checked = item.is_checked()
        is_enabled = item.is_enabled()
        is_chat_item = item.matches_label('与奥黛丽聊聊')
        chat_active = bool(getattr(self.manager, 'chat_window', None))

        button_width = width - self.menu_theme['item_frame_pad_x'] * 2
        btn_canvas = tk.Canvas(
            parent,
            width=button_width,
            height=88,
            highlightthickness=0,
            bd=0,
            bg=self.colors['gold_deep'],
            cursor='hand2' if is_enabled else 'arrow',
        )

        normal_bg = self.colors['card_alt'] if is_enabled else self.colors['panel']
        hover_bg = self.colors['hover'] if is_enabled else normal_bg
        normal_border = self.colors['gold_soft'] if is_checked else self.colors['border']
        hover_border = self.colors['gold'] if is_enabled else normal_border
        indicator_normal = self.colors['gold'] if is_checked else self.colors['accent_soft']
        indicator_hover = self.colors['gold_bright'] if is_enabled else indicator_normal

        row_height = 88
        self._register_surface_background(
            btn_canvas,
            start_x + self.menu_theme['item_frame_pad_x'],
            start_y + self.menu_theme['item_frame_pad_y'],
            button_width,
            row_height,
        )

        if item.label == self._get_music_label and callable(getattr(self, '_get_music_meta_text', None)):
            meta_text = self._get_music_meta_text()
        elif not is_enabled:
            meta_text = '当前不可用'
        elif is_chat_item and chat_active:
            meta_text = '正在进行'
        elif is_checked:
            meta_text = '已启用'
        else:
            meta_text = '点击执行'

        text_color = self.colors['text_strong'] if is_enabled else self.colors['subtext']
        active_state = is_checked or (is_chat_item and chat_active)
        meta_color = self.colors['gold_deep'] if active_state else self.colors['text_strong']
        trailing_color = self.colors['gold_deep'] if active_state else self.colors['accent_dark']

        border_id = btn_canvas.create_rectangle(0, 0, button_width, row_height, outline='', fill='')
        indicator_id = btn_canvas.create_rectangle(0, 0, self.menu_theme['item_indicator_width'], row_height, outline='', fill='')
        title_id = btn_canvas.create_text(
            self.menu_theme['item_indicator_width'] + self.menu_theme['item_pad_x'],
            self.menu_theme['item_pad_y'],
            text=label,
            font=self.fonts['base_strong'],
            fill=text_color,
            anchor='nw',
        )
        meta_id = btn_canvas.create_text(
            self.menu_theme['item_indicator_width'] + self.menu_theme['item_pad_x'],
            self.menu_theme['item_pad_y'] + 32,
            text=meta_text,
            font=self.fonts['small'],
            fill=meta_color,
            anchor='nw',
        )
        trailing_id = btn_canvas.create_text(
            button_width - 14,
            row_height / 2,
            text='ON' if active_state else ('›' if is_enabled else '·'),
            font=self.fonts['small'],
            fill=trailing_color,
            anchor='e',
        )

        if is_enabled and item.callback:
            def apply_state(hovered: bool):
                btn_canvas.itemconfigure(border_id, fill=hover_bg if hovered else '', outline=hover_border if hovered else '', width=self.menu_theme['item_border_width'] if hovered else 0)
                btn_canvas.itemconfigure(indicator_id, fill=indicator_hover if hovered else '')
                btn_canvas.itemconfigure(meta_id, fill=self.colors['gold_deep'] if (hovered or active_state) else self.colors['text_strong'])
                btn_canvas.itemconfigure(trailing_id, fill=self.colors['gold_deep'] if (hovered or active_state) else self.colors['accent_dark'])

            def on_enter(_event):
                apply_state(True)

            def on_leave(_event):
                apply_state(False)

            def on_click(_event, i=item):
                i.callback()
                self._on_close()

            btn_canvas.bind('<Enter>', on_enter, add='+')
            btn_canvas.bind('<Leave>', on_leave, add='+')
            btn_canvas.bind('<Button-1>', on_click, add='+')

        parent.create_window(
            start_x + self.menu_theme['item_frame_pad_x'],
            start_y + self.menu_theme['item_frame_pad_y'],
            anchor='nw',
            window=btn_canvas,
            width=button_width,
            height=row_height,
        )
        return row_height + self.menu_theme['item_frame_pad_y'] * 2
    
    def _bind_global_click(self):
        """绑定全局点击检测"""
        if self.window is None or not self.window.winfo_exists():
            return
        self.window.bind_all("<Button-1>", self._check_click_outside, add="+")
    
    def _check_click_outside(self, event):
        """检查点击是否在菜单外部"""
        if self.window is None or not self.window.winfo_exists():
            return
        
        x = self.window.winfo_x()
        y = self.window.winfo_y()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        
        # 点击在菜单外部，关闭菜单
        if not (x <= event.x_root <= x + w and y <= event.y_root <= y + h):
            self._on_close()
    
    def hide(self):
        """隐藏菜单"""
        if self.window is not None:
            try:
                self.window.unbind_all("<Button-1>")
                self.window.grab_release()
                self.window.destroy()
            except Exception:
                pass
            self.window = None
    
    def is_visible(self) -> bool:
        """检查菜单是否可见"""
        return self.window is not None and self.window.winfo_exists()


def show_quick_menu(pet, manager, version: str, x: int, y: int, tray_icon=None) -> QuickContextMenu:
    """
    显示快捷菜单的便捷函数
    
    Args:
        pet: DesktopGif 实例
        manager: PetManager 实例
        version: 版本号
        x: 屏幕 X 坐标
        y: 屏幕 Y 坐标
        tray_icon: 托盘图标实例（可选）
    
    Returns:
        QuickContextMenu: 菜单实例
    """
    menu = QuickContextMenu(pet, manager, version, tray_icon)
    menu.show(x, y)
    return menu
