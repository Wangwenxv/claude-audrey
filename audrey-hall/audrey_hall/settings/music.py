"""音乐播放器标签页"""

import ctypes
import os
import random
import tkinter as tk
from pathlib import Path

from ..config import load_config, save_config
from ..utils import resource_path


AUDIOBOOK_EXTENSIONS = ('.wav', '.mp3', '.wma')


def create_music_tab(settings_window, parent):
    """创建音乐播放器标签页 - 歌姬偶像风格

    Args:
        settings_window: SettingsWindow 实例
        parent: 父容器

    Returns:
        创建的标签页 frame
    """
    frame = tk.Frame(parent, bg=settings_window.colors["bg"])

    # 创建内嵌音乐播放器（使用统一风格）
    settings_window.music_player_embedded = MusicPlayerEmbedded(
        frame, settings_window.colors, settings_window.fonts, settings_window
    )

    return frame


class MusicPlayerEmbedded:
    """内嵌音乐播放器 - 歌姬偶像风格"""

    def __init__(self, parent, colors, fonts, settings_window=None):
        self.parent = parent
        self.colors = colors
        self.fonts = fonts
        self.settings_window = settings_window
        self.config = load_config()

        # 创建实际的播放器核心（使用 MusicPlayer 的音频功能）
        from ..music_player import MusicPlayer

        # 创建一个隐藏的 Frame 作为 parent，确保 MusicPlayer 正常初始化
        import tkinter as tk

        dummy_frame = tk.Frame(parent)
        self.core_player = MusicPlayer(
            parent=dummy_frame, position_unlock_callback=None
        )

        # 同步音乐文件列表
        self.music_files = self.core_player.music_files
        self.current_index = self.core_player.current_index
        self.is_playing = self.core_player.is_playing
        self.is_paused = self.core_player.is_paused
        self._shared_player_cls = MusicPlayer

        # 从配置加载
        self.music_volume = self.config.get("music_volume", 100)
        self.music_enabled = self.config.get("music_enabled", False)
        self._mci_alias = 'ameath_story_player'
        self._mci_playing_path = ''
        self._mci_total_length = 0
        self._mci_position_ms = 0
        self._updating_progress = False

        # 应用音量设置
        self.core_player.music_volume = self.music_volume

        # 创建UI
        self._create_ui()

        # 加载音乐文件并更新列表显示
        self._load_music_files()
        self.core_player.music_files = list(self.music_files)
        self._hydrate_shared_playback_state()

        # 启动进度更新循环
        self._start_progress_loop()

    def _create_ui(self):
        """创建音乐播放器UI - 歌姬偶像风格"""
        # 主容器
        main_frame = tk.Frame(self.parent, bg=self.colors["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # ===== 演出曲目列表 =====
        playlist_frame = tk.LabelFrame(
            main_frame,
            text="🎵 演出曲目",
            font=self.fonts["subtitle"],
            padx=15,
            pady=12,
            bg=self.colors["card_bg"],
            fg=self.colors["accent_dark"],
            bd=1,
            relief=tk.SOLID,
        )
        playlist_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15), ipady=5)

        # 列表框容器
        list_container = tk.Frame(playlist_frame, bg=self.colors["card_bg"])
        list_container.pack(fill=tk.BOTH, expand=True, pady=5)

        # 滚动条
        scrollbar = tk.Scrollbar(list_container, bg=self.colors["card_bg"])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 歌单列表 - 像素风边框，固定显示5首歌高度
        self.listbox = tk.Listbox(
            list_container,
            yscrollcommand=scrollbar.set,
            bg=self.colors["bg"],
            fg=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground="white",
            font=self.fonts["base"],
            bd=2,
            relief=tk.SUNKEN,
            highlightthickness=0,
            activestyle="none",
            height=8,
            width=45,
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.config(command=self.listbox.yview)

        self.listbox.bind("<Double-Button-1>", self._on_double_click)
        self.listbox.bind("<<ListboxSelect>>", self._on_single_select)

        # 获取用户音乐文件夹路径（首次运行复制自带歌曲）
        self.music_folder = self._get_user_music_folder()

        # 可点击的文件夹路径标签
        folder_label = tk.Label(
            playlist_frame,
            text=f"📁 打开有声小说文件夹: {self.music_folder}",
            font=self.fonts["small"],
            bg=self.colors["card_bg"],
            fg=self.colors["accent"],
            cursor="hand2",
        )
        folder_label.pack(pady=(5, 0))
        folder_label.bind("<Button-1>", lambda e: self._open_music_folder())

        # 刷新按钮
        refresh_btn = tk.Label(
            playlist_frame,
            text="🔄 点击刷新有声小说列表",
            font=self.fonts["small"],
            bg=self.colors["card_bg"],
            fg=self.colors["subtext"],
            cursor="hand2",
        )
        refresh_btn.pack(pady=(3, 0))
        refresh_btn.bind("<Button-1>", lambda e: self._refresh_list())

        # ===== 演出控制台 =====
        console_frame = tk.LabelFrame(
            main_frame,
            text="🎮 演出控制台",
            font=self.fonts["subtitle"],
            padx=15,
            pady=12,
            bg=self.colors["card_bg"],
            fg=self.colors["accent_dark"],
            bd=1,
            relief=tk.SOLID,
        )
        console_frame.pack(fill=tk.X, pady=(0, 15), ipady=5)

        # 播放控制按钮 - 偶像风格
        btn_row = tk.Frame(console_frame, bg=self.colors["card_bg"])
        btn_row.pack(fill=tk.X, pady=(0, 10))

        # 统一按钮样式
        # 统一按钮样式 - 演出控制台
        base_btn = {
            "bg": self.colors["accent"],
            "fg": "white",
            "activebackground": self.colors["accent_dark"],
            "activeforeground": "white",
            "font": self.fonts["control"],
            "relief": tk.FLAT,
            "bd": 0,
            "cursor": "hand2",
            "height": 1,
        }

        self.prev_btn = tk.Button(
            btn_row,
            text="◀◀ 上一曲",
            width=10,
            command=self._previous_track,
            **base_btn,
            state=tk.NORMAL if self.music_enabled else tk.DISABLED,
        )
        self.prev_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.play_btn = tk.Button(
            btn_row,
            text="▶ 有声小说",
            width=12,
            command=self._toggle_play,
            **base_btn,
            state=tk.NORMAL if self.music_enabled else tk.DISABLED,
        )
        self.play_btn.pack(side=tk.LEFT, padx=5)

        self.next_btn = tk.Button(
            btn_row,
            text="下一曲 ▶▶",
            width=10,
            command=self._next_track,
            **base_btn,
            state=tk.NORMAL if self.music_enabled else tk.DISABLED,
        )
        self.next_btn.pack(side=tk.LEFT, padx=(10, 0))

        # 进度条 - 演出进度
        progress_row = tk.Frame(console_frame, bg=self.colors["card_bg"])
        progress_row.pack(fill=tk.X, pady=(10, 5))

        tk.Label(
            progress_row,
            text="演出进度: ",
            font=self.fonts["control"],
            bg=self.colors["card_bg"],
            fg=self.colors["text"],
        ).pack(side=tk.LEFT)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = tk.Scale(
            progress_row,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.progress_var,
            command=self._on_progress_change,
            length=300,
            font=self.fonts["small"],
            bg=self.colors["card_bg"],
            fg=self.colors["text"],
            highlightthickness=0,
            troughcolor=self.colors["tab_bg"],
            activebackground=self.colors["accent"],
            sliderrelief=tk.FLAT,
            state=tk.NORMAL if self.music_enabled else tk.DISABLED,
        )
        self.progress_bar.pack(side=tk.LEFT, padx=(5, 10))

        self.time_label = tk.Label(
            progress_row,
            text="0:00 / 0:00",
            font=self.fonts["control"],
            bg=self.colors["card_bg"],
            fg=self.colors["accent_dark"],
            width=12,
        )
        self.time_label.pack(side=tk.LEFT)

        # ===== 音量与资源管理 =====
        settings_frame = tk.LabelFrame(
            main_frame,
            text="🔧 音效设定",
            font=self.fonts["subtitle"],
            padx=15,
            pady=12,
            bg=self.colors["card_bg"],
            fg=self.colors["accent_dark"],
            bd=1,
            relief=tk.SOLID,
        )
        settings_frame.pack(fill=tk.X, pady=(0, 10), ipady=5)

        # 音量控制
        volume_row = tk.Frame(settings_frame, bg=self.colors["card_bg"])
        volume_row.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            volume_row,
            text="场馆音量: ",
            font=self.fonts["control"],
            bg=self.colors["card_bg"],
            fg=self.colors["text"],
        ).pack(side=tk.LEFT)

        self.volume_var = tk.IntVar(value=self.music_volume)
        volume_scale = tk.Scale(
            volume_row,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.volume_var,
            command=self._on_volume_change,
            length=250,
            font=self.fonts["small"],
            bg=self.colors["card_bg"],
            fg=self.colors["text"],
            highlightthickness=0,
            troughcolor=self.colors["tab_bg"],
            activebackground=self.colors["accent"],
            sliderrelief=tk.FLAT,
            state=tk.NORMAL if self.music_enabled else tk.DISABLED,
        )
        volume_scale.pack(side=tk.LEFT, padx=(5, 10))

        self.volume_label = tk.Label(
            volume_row,
            text=f"{self.music_volume}%",
            font=self.fonts["control"],
            bg=self.colors["card_bg"],
            fg=self.colors["accent_dark"],
            width=5,
        )
        self.volume_label.pack(side=tk.LEFT)

        # 保存按钮引用（空列表，因为已删除按钮）
        self.action_buttons = []

    def _get_user_music_folder(self):
        """获取有声小说目录，直接使用项目内置 sound/music。"""
        music_folder = resource_path("sound/music")
        os.makedirs(music_folder, exist_ok=True)
        return music_folder

    def _open_music_folder(self):
        """打开音乐文件夹"""
        import os
        import subprocess

        try:
            subprocess.Popen(f'explorer "{self.music_folder}"', shell=True)
        except Exception as e:
            print(f"打开文件夹失败: {e}")

    def _load_music_files(self):
        """加载音乐文件列表"""
        music_dir = self.music_folder
        self.music_files = []

        if os.path.exists(music_dir):
            for file in sorted(os.listdir(music_dir)):
                if file.lower().endswith(AUDIOBOOK_EXTENSIONS):
                    self.music_files.append(os.path.join(music_dir, file))

        # 同步到核心播放器
        self.core_player.music_files = self.music_files
        self.core_player.load_music_files_internal()

        self._update_listbox()

    def _update_listbox(self):
        """更新列表框显示"""
        self.listbox.delete(0, tk.END)
        for file in self.music_files:
            self.listbox.insert(tk.END, f" ♪ {Path(file).stem}")

        if self.current_index >= 0 and self.current_index < len(self.music_files):
            self.listbox.selection_set(self.current_index)
            self.listbox.see(self.current_index)

    def _hydrate_shared_playback_state(self):
        shared = self._shared_player_cls
        if getattr(shared, '_shared_backend', '') == 'mci' and getattr(shared, '_shared_current_file', ''):
            self._mci_playing_path = shared._shared_current_file
            self._mci_total_length = getattr(shared, '_shared_total_length', 0) or 0
            self._mci_position_ms = getattr(shared, '_shared_current_position', 0) or 0
            self.current_index = getattr(shared, '_shared_current_index', -1)
            self.is_playing = getattr(shared, '_shared_is_playing', False)
            self.is_paused = getattr(shared, '_shared_is_paused', False)
            if 0 <= self.current_index < len(self.music_files):
                self._update_listbox()
            if self.is_playing:
                self.play_btn.config(text='⏸ 暂停演出')
            elif self.is_paused:
                self.play_btn.config(text='▶ 继续演出')
            if self._mci_playing_path:
                self.time_label.config(
                    text=f"播放中 / {self._format_title_for_display(Path(self._mci_playing_path).stem)}"
                )
            return

        self._sync_player_shared_state(reset_title=True)

    def _on_single_select(self, _event):
        """单击列表项后直接开始播放。"""
        selection = self.listbox.curselection()
        if not selection:
            return
        target_index = selection[0]
        if target_index != self.current_index or not self.is_playing:
            self.current_index = target_index
            self._play_current()

    def _on_progress_change(self, value):
        """进度条拖动"""
        if self._updating_progress:
            return
        if not self.music_files or self.current_index < 0:
            return

        if self._mci_playing_path:
            try:
                target_ms = int((float(value) / 100.0) * max(self._mci_total_length, 1))
            except Exception:
                return
            self._mci_command(f'seek {self._mci_alias} to {target_ms}')
            self._mci_position_ms = target_ms
            self._sync_player_shared_state()
            return

        # 调用核心播放器的进度跳转
        self.core_player.on_progress_change(value)

    def _on_volume_change(self, value):
        """音量改变"""
        volume = int(float(value))
        self.music_volume = volume
        self.volume_label.config(text=f"{volume}%")

        # 同步到核心播放器，实时调整音量
        self.core_player.music_volume = volume
        # 调用apply_current_volume同步到共享变量，确保音频回调读取最新值
        self.core_player.apply_current_volume()

        config = load_config()
        config["music_volume"] = volume
        save_config(config)

        if self._mci_playing_path:
            self._mci_command(f'setaudio {self._mci_alias} volume to {volume * 10}')
            self._sync_player_shared_state()
        
        # 同步到个性化界面的滑块
        if self.settings_window and hasattr(self.settings_window, 'music_volume_var'):
            self.settings_window.music_volume_var.set(volume)

    def _on_double_click(self, event):
        """双击播放"""
        selection = self.listbox.curselection()
        if selection:
            self.current_index = selection[0]
            self._play_current()

    def _toggle_play(self):
        """播放/暂停切换"""
        if self.is_playing:
            self._pause()
        else:
            if self._mci_playing_path and self.is_paused:
                self._mci_command(f'resume {self._mci_alias}')
                self.is_playing = True
                self.is_paused = False
                self.play_btn.config(text="⏸ 暂停演出")
                self._sync_player_shared_state()
                return
            self._play_current()

    def _play_current(self):
        """播放当前选中的有声小说。优先走 Windows 原生播放器以支持 wma。"""
        if not self.music_files:
            return
        
        # 如果没有选中歌曲，随机选择一首
        if self.current_index < 0:
            self.current_index = random.randint(0, len(self.music_files) - 1)
            self._update_listbox()

        current_file = self.music_files[self.current_index]
        if self._play_via_mci(current_file):
            self.is_playing = True
            self.is_paused = False
            self.play_btn.config(text="⏸ 暂停演出")
            self.time_label.config(text=f"播放中 / {self._format_title_for_display(Path(current_file).stem)}")
            return

        self.is_playing = False
        self.is_paused = False
        self.play_btn.config(text="▶ 有声小说")
        self.time_label.config(text="当前文件暂不支持播放")
        self._sync_player_shared_state(reset_title=True)

    def _pause(self):
        """暂停播放"""
        if self._mci_playing_path:
            self._mci_command(f'pause {self._mci_alias}')
            self.is_playing = False
            self.is_paused = True
            self.play_btn.config(text="▶ 继续演出")
            self._sync_player_shared_state()
            return

        # 调用核心播放器暂停
        self.core_player.toggle_play_pause()

        # 更新UI状态
        self.is_playing = self.core_player.is_playing
        self.is_paused = self.core_player.is_paused
        self.play_btn.config(text="▶ 继续演出")

    def _previous_track(self):
        """上一首"""
        if not self.music_files:
            return
        self.current_index = (self.current_index - 1) % len(self.music_files)
        self._update_listbox()
        if self.is_playing:
            self._play_current()

    def _next_track(self):
        """下一首"""
        if not self.music_files:
            return
        self.current_index = (self.current_index + 1) % len(self.music_files)
        self._update_listbox()
        if self.is_playing:
            self._play_current()

    def _start_progress_loop(self):
        """启动进度更新循环"""
        self._update_progress_ui()

    def _update_progress_ui(self):
        """更新进度UI"""
        try:
            if self._mci_playing_path:
                self._update_mci_progress_ui()
            elif self.core_player.is_playing and not self.core_player.is_paused:
                # 更新播放按钮状态
                if self.play_btn.cget("text") != "⏸ 暂停演出":
                    self.play_btn.config(text="⏸ 暂停演出")

                # 更新进度条（如果有进度信息）
                if self.core_player.total_length > 0 and self.core_player.sample_rate:
                    # 用 sample_rate 和 current_position 计算进度
                    current_ms = int(
                        self.core_player.current_position
                        * 1000
                        / self.core_player.sample_rate
                    )
                    progress = (
                        (current_ms / self.core_player.total_length) * 100
                        if self.core_player.total_length > 0
                        else 0
                    )
                    self._updating_progress = True
                    self.progress_var.set(min(progress, 100))
                    self._updating_progress = False

                    # 更新时间显示
                    self.time_label.config(
                        text=f"{self._format_time(current_ms)} / {self._format_time(self.core_player.total_length)}"
                    )
            else:
                # 更新播放按钮状态
                if (
                    self.core_player.is_paused
                    and self.play_btn.cget("text") != "▶ 继续演出"
                ):
                    self.play_btn.config(text="▶ 继续演出")

            # 继续循环 - 检查窗口是否还存在
            if hasattr(self, "parent") and self.parent.winfo_exists():
                self.parent.after(100, self._update_progress_ui)
        except Exception as e:
            # 静默处理更新错误，继续循环
            if hasattr(self, "parent"):
                try:
                    if self.parent.winfo_exists():
                        self.parent.after(100, self._update_progress_ui)
                except Exception:
                    pass

    def _format_time(self, ms):
        """格式化时间显示"""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"

    def _refresh_list(self):
        """刷新音乐列表"""
        self._load_music_files()
        self.core_player.music_files = list(self.music_files)
        self._sync_player_shared_state(reset_title=not bool(self._mci_playing_path))

    def _play_via_mci(self, filepath: str) -> bool:
        # 新开设置页时，本地实例未必持有旧 MCI 状态；先无条件收口同名 alias。
        self._mci_command(f'stop {self._mci_alias}')
        self._mci_command(f'close {self._mci_alias}')
        self._stop_mci_playback()
        quoted = filepath.replace('"', '""')
        if self._mci_command(f'open "{quoted}" alias {self._mci_alias}') != 0:
            return False
        self._mci_command(f'set {self._mci_alias} time format milliseconds')
        if self._mci_command(f'setaudio {self._mci_alias} volume to {self.music_volume * 10}') != 0:
            pass
        if self._mci_command(f'play {self._mci_alias}') != 0:
            self._stop_mci_playback()
            return False
        self._mci_playing_path = filepath
        self._mci_total_length = self._mci_status_int('length')
        self._mci_position_ms = 0
        self._sync_player_shared_state()
        return True

    def _stop_mci_playback(self):
        if not self._mci_playing_path:
            return
        self._mci_command(f'stop {self._mci_alias}')
        self._mci_command(f'close {self._mci_alias}')
        self._mci_playing_path = ''
        self._mci_total_length = 0
        self._mci_position_ms = 0
        self.is_playing = False
        self.is_paused = False
        self._sync_player_shared_state(reset_title=True)

    def _mci_command(self, command: str) -> int:
        try:
            return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
        except Exception:
            return -1

    def _mci_status_text(self, query: str) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        try:
            result = ctypes.windll.winmm.mciSendStringW(
                f'status {self._mci_alias} {query}',
                buffer,
                len(buffer),
                None,
            )
            if result != 0:
                return ''
            return buffer.value.strip()
        except Exception:
            return ''

    def _mci_status_int(self, query: str) -> int:
        value = self._mci_status_text(query)
        try:
            return int(value)
        except Exception:
            return 0

    def _update_mci_progress_ui(self):
        mode = self._mci_status_text('mode')
        self._mci_position_ms = self._mci_status_int('position')
        if self._mci_total_length <= 0:
            self._mci_total_length = self._mci_status_int('length')

        if mode == 'playing':
            self.is_playing = True
            self.is_paused = False
            if self.play_btn.cget('text') != '⏸ 暂停演出':
                self.play_btn.config(text='⏸ 暂停演出')
        elif mode == 'paused':
            self.is_playing = False
            self.is_paused = True
            if self.play_btn.cget('text') != '▶ 继续演出':
                self.play_btn.config(text='▶ 继续演出')
        elif mode == 'stopped' and self._mci_playing_path:
            self.is_playing = False
            self.is_paused = False

        if self._mci_total_length > 0:
            progress = min((self._mci_position_ms / self._mci_total_length) * 100, 100)
            self._updating_progress = True
            self.progress_var.set(progress)
            self._updating_progress = False
            self.time_label.config(
                text=f'{self._format_time(self._mci_position_ms)} / {self._format_time(self._mci_total_length)}'
            )

        self._sync_player_shared_state()

    def _sync_player_shared_state(self, *, reset_title: bool = False):
        from ..music_player import MusicPlayer

        if self._mci_playing_path:
            MusicPlayer._shared_is_playing = self.is_playing
            MusicPlayer._shared_is_paused = self.is_paused
            MusicPlayer._shared_current_index = self.current_index
            MusicPlayer._shared_music_files = list(self.music_files)
            MusicPlayer._shared_song_name = Path(self._mci_playing_path).stem
            MusicPlayer._shared_current_file = self._mci_playing_path
            MusicPlayer._shared_backend = 'mci'
            MusicPlayer._shared_total_length = self._mci_total_length
            MusicPlayer._shared_current_position = self._mci_position_ms
            return

        MusicPlayer._shared_is_playing = False
        MusicPlayer._shared_is_paused = False
        MusicPlayer._shared_current_index = self.current_index
        MusicPlayer._shared_music_files = list(self.music_files)
        if reset_title:
            MusicPlayer._shared_song_name = '未选择歌曲'
            MusicPlayer._shared_total_length = 0
            MusicPlayer._shared_current_position = 0
            MusicPlayer._shared_current_file = ''
            MusicPlayer._shared_backend = ''

    def _format_title_for_display(self, title: str) -> str:
        compact = ' '.join((title or '').split())
        if len(compact) <= 16:
            return compact
        return compact[:16] + '...'

    def _import_music(self):
        """导入音乐文件"""
        import os
        import shutil
        from tkinter import filedialog
        from ..utils import resource_path

        files = filedialog.askopenfilenames(
            title="选择有声小说文件",
            filetypes=[
                ("音频文件", "*.wav *.mp3 *.wma"),
                ("WAV文件", "*.wav"),
                ("MP3文件", "*.mp3"),
                ("WMA文件", "*.wma"),
                ("所有文件", "*.*"),
            ],
        )

        if files:
            music_dir = resource_path("sound/music")
            os.makedirs(music_dir, exist_ok=True)

            for file in files:
                try:
                    if file.lower().endswith(AUDIOBOOK_EXTENSIONS):
                        shutil.copy(file, music_dir)
                except Exception as e:
                    print(f"复制文件失败 {file}: {e}")

            self._load_music_files()
