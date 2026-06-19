import base64
import io
import json
import os
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageTk

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

from .claude_agent import (
    CONNECTION_TARGET_LABELS,
    ClaudeCodeSession,
    normalize_connection_target,
)
from .ui import create_button, create_card, create_dropdown, get_theme
from .utils import resource_path


MODEL_QUICK_CHOICES = [
    'default',
    'sonnet',
    'opus',
    'haiku',
    'best',
    'sonnet[1m]',
    'opus[1m]',
    'opusplan',
]

CHOICE_LINE_PATTERNS = (
    re.compile(r'^\s*(?:[-*]|\d+\.)\s+\*\*(.+?)\*\*(?:\s*[—-]\s*(.+))?\s*$'),
    re.compile(r'^\s*(?:[-*]|\d+\.)\s+(.+?)\s*[—-]\s*(.+)\s*$'),
)

MAX_SIDE_CONTEXT_MESSAGES = 6
MAX_SIDE_CONTEXT_CHARS = 2800
MAX_STATUS_WIDTH_PX = 600
MIN_STATUS_CORE_WIDTH_PX = 180
MAX_HISTORY_SESSIONS = 18
MAX_HISTORY_LABEL_CHARS = 14
EVENT_POLL_INTERVAL_MS = 100
WELCOME_MESSAGE = (
    '不属于这个时代的愚者...\n\n'
    '灰雾之上的神秘主宰...\n\n'
    '执掌好运的黄黑之王...\n\n'
    '按 Ctrl+Enter 发送，/btw 可发起旁路问题，Ctrl+V 可粘贴图片。'
)
INPUT_PLACEHOLDER = '输入想对奥黛丽说的话，Ctrl+Enter 发送，Ctrl+V 粘贴图片'
SUPPORTED_IMAGE_FORMATS = {
    'PNG': 'image/png',
    'JPEG': 'image/jpeg',
    'JPG': 'image/jpeg',
    'GIF': 'image/gif',
    'WEBP': 'image/webp',
}
CONNECTION_TARGET_CHOICES = [
    ('auto', '自动抉择'),
    ('project', '奥黛丽agent'),
    ('system', 'claude agent'),
]
MODE_CHOICES = [
    ('default', '默认陪伴'),
    ('acceptEdits', '赐予更改权限'),
    ('auto', '赐予全部权限'),
    ('plan', '还是先做个计划吧'),
]
MODE_LABELS = {key: label for key, label in MODE_CHOICES}
CONNECTION_OPTION_LABELS = {key: label for key, label in CONNECTION_TARGET_CHOICES}
CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'


def _sanitize_project_path(path_text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '-', path_text or '')


class ChatWindow:
    def __init__(self, parent, app, version):
        self.parent = parent
        self.app = app
        self.version = version
        self.window = None
        self.text_area = None
        self.input_box = None
        self.send_button = None
        self.stop_button = None
        self._input_bg_source = None
        self._input_bg_photo = None
        self._input_bg_image_id = None
        self._input_canvas = None
        self._avatar_source = None
        self._assistant_avatar = None
        self._user_avatar_source = None
        self._user_avatar = None
        self._transcript_container = None
        self._transcript_width = 700
        self._message_widgets = []
        self.status_var = tk.StringVar(value='正在唤醒奥黛丽的助手...')
        self._event_queue = queue.Queue()
        self._busy = False
        self._status_dot = None
        self._status_dot_item = None
        self._status_label = None
        self._aurora_bar = None
        self._aurora_bar_item = None
        self._aurora_bar_job = None
        self._aurora_phase = 0
        self._aurora_direction = 1
        self._aurora_colors = ('#DDE9E5', '#B8D1CB')
        self._attachment_preview_frame = None
        self._content_pane = None
        self._auto_allow_tools = set()  # 用户选择“总是允许”的工具名
        self._pending_perm_frames = {}  # request_id -> 内嵌权限卡片 frame
        self._pending_image_attachments = []
        self._conversation_history = []
        self._active_model = 'default'
        self._active_permission_mode = 'default'
        self._connection_target = 'auto'
        self._main_status_text = ''
        self._task_progress_text = ''
        self._current_total_tokens = None
        self._current_input_tokens = None
        self._current_output_tokens = None
        self._last_summary_status = ''
        self._mode_var = tk.StringVar(value=self._format_mode_status())
        self._connection_var = tk.StringVar(value=self._format_connection_status())
        self._resume_session_id = ''
        self._active_session_id = ''
        self._session_label_var = tk.StringVar(value='当前会话：新对话')
        self._history_items = []
        self._history_container = None
        self._history_empty_label = None
        self._history_context_menu = None
        self._connection_start_time = None
        self._connection_time_var = tk.StringVar(value='')
        self._connection_time_timer = None
        self._input_shell_frame = None
        self._input_placeholder_active = False

        self.theme = get_theme()
        self.fonts = self.theme['fonts']
        self.colors = self.theme['colors']
        self.window_theme = self.theme['windows']['chat']
        self.chat_theme = self.theme['chat']
        self.status_var.trace_add('write', self._handle_status_var_change)

        avatar_path = os.path.join(os.path.dirname(__file__), 'img', 'avat.png')
        if os.path.isfile(avatar_path):
            self._avatar_source = Image.open(avatar_path)

        user_avatar_path = os.path.join(os.path.dirname(__file__), 'img', 'avat2.png')
        if os.path.isfile(user_avatar_path):
            self._user_avatar_source = Image.open(user_avatar_path)

        self.session = self._create_session()

    def _create_session(self):
        return ClaudeCodeSession(
            self._enqueue_event,
            connection_target=self._connection_target,
            resume_session_id=self._resume_session_id or None,
        )

    def _format_connection_status(self):
        label = CONNECTION_OPTION_LABELS.get(self._connection_target, self._connection_target)
        return label

    def _refresh_connection_buttons(self):
        self._connection_var.set(self._format_connection_status())

    def _set_connection_target(self, target: str):
        normalized = normalize_connection_target(target)
        if normalized != self._connection_target:
            self._connection_target = normalized
            self.session.connection_target = normalized
        self._refresh_connection_buttons()

    def _switch_connection_target(self, target: str):
        normalized = normalize_connection_target(target)
        if normalized == self._connection_target and self.session.process is not None:
            self.status_var.set(f'已连上{CONNECTION_OPTION_LABELS.get(normalized, normalized)}')
            return

        self._set_connection_target(normalized)
        self._reconnect_session(announce=True)

    def _reconnect_session(self, announce: bool = False):
        try:
            self.session.close()
        except Exception:
            pass

        self._event_queue = queue.Queue()
        self._busy = False
        self._set_busy(False)
        self._pending_perm_frames = {}
        self._main_status_text = ''
        self._task_progress_text = ''
        self._current_total_tokens = None
        self._current_input_tokens = None
        self._current_output_tokens = None
        self._last_summary_status = ''
        self._active_session_id = self._resume_session_id
        self._active_permission_mode = 'default'
        self._refresh_mode_buttons()
        self.session = self._create_session()
        self._session_label_var.set(
            self._format_session_label()
        )

        label = CONNECTION_OPTION_LABELS.get(self._connection_target, self._connection_target)
        if announce:
            self._append_inline_status(f'正在重连：{label}')
        self.status_var.set(f'正在呼唤{label}...')
        self._start_session()

    def _start_session(self):
        self._connection_start_time = datetime.now()
        self._update_connection_time()
        try:
            self.session.start()
        except Exception as exc:
            self._connection_start_time = None
            self._connection_time_var.set('')
            self.status_var.set('呼唤失败')
            self._append_message('error', f'呼唤助手失败：{exc}')

    def _update_connection_time(self):
        """每秒更新连接时长显示"""
        if self.window is None or not self.window.winfo_exists():
            return
        if self._connection_time_timer is not None:
            try:
                self.window.after_cancel(self._connection_time_timer)
            except Exception:
                pass
            self._connection_time_timer = None
        if self._connection_start_time is None:
            self._connection_time_var.set('')
        else:
            elapsed = (datetime.now() - self._connection_start_time).total_seconds()
            if elapsed < 0:
                self._connection_time_var.set('')
            elif elapsed < 60:
                self._connection_time_var.set(f'已连接 {int(elapsed)}s')
            else:
                minutes = int(elapsed // 60)
                seconds = int(elapsed % 60)
                self._connection_time_var.set(f'已连接 {minutes}m{seconds}s')
        self._connection_time_timer = self.window.after(1000, self._update_connection_time)

    def _permission_card_style(self):
        return {
            'card_bg': '#EDF6F4',
            'card_border': '#D6B36A',
            'title_fg': '#3D6667',
            'summary_bg': '#FFFDF8',
            'summary_fg': '#5B7174',
            'accent_line': '#A8CEC7',
            'button_primary': {
                'bg': '#F8FBFA',
                'fg': '#36585B',
                'highlightbackground': '#D6B36A',
                'highlightthickness': 1,
                'hover_bg': '#E7F3F0',
                'hover_fg': '#2E4B4E',
                'hover_border_color': '#E0C386',
                'pressed_bg': '#F2E8D2',
                'pressed_fg': '#2E4B4E',
                'pressed_border_color': '#C79E56',
                'pulse_border_off_color': '#A8CEC7',
            },
            'button_secondary': {
                'bg': '#FFFDF8',
                'fg': '#4C676A',
                'highlightbackground': '#A8CEC7',
                'highlightthickness': 1,
                'hover_bg': '#F2F8F7',
                'hover_fg': '#2E4B4E',
                'hover_border_color': '#D6B36A',
                'pressed_bg': '#F6EEE1',
                'pressed_fg': '#2E4B4E',
                'pressed_border_color': '#C79E56',
                'pulse_border_off_color': '#D8E8E4',
            },
            'button_danger': {
                'bg': '#FFF7F8',
                'fg': '#7A5E64',
                'highlightbackground': '#DAB8BE',
                'highlightthickness': 1,
                'hover_bg': '#FBECEF',
                'hover_fg': '#6B4D54',
                'hover_border_color': '#D6B36A',
                'pressed_bg': '#F6DEE3',
                'pressed_fg': '#6B4D54',
                'pressed_border_color': '#C79E56',
                'pulse_border_off_color': '#EBD8DC',
            },
        }

    def _aurora_button_style(self):
        return {
            'bg': '#F8FCFB',
            'fg': '#2E4245',
            'highlightbackground': '#CFAF5F',
            'highlightthickness': 0,
            
            'hover_bg': '#EDF7F4',
            'hover_fg': '#1F3033',
            'hover_border_color': '#F9BE00',
            'hover_border_thickness': 1,
            'hover_color': '##F9BE00',
            
            'pressed_bg': '#F0E2C8',
            'pressed_fg': '#1F3033',
            'pressed_border_color': '#9A7233',
            
            'pulse_border_off_color': '#FCF9F0',
        }

    def _update_input_background(self, event=None):
        if self._input_canvas is None or self._input_bg_source is None:
            return

        if event is not None:
            width = event.width
            height = event.height
        else:
            width = self._input_canvas.winfo_width()
            height = self._input_canvas.winfo_height()

        if width <= 1 or height <= 1:
            return

        source_width, source_height = self._input_bg_source.size
        scale = max(width / source_width, height / source_height)
        resized_width = max(1, int(source_width * scale))
        resized_height = max(1, int(source_height * scale))
        resized = self._input_bg_source.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

        offset_x = (width - resized_width) // 2
        offset_y = (height - resized_height) // 2
        self._input_bg_photo = ImageTk.PhotoImage(resized)

        if self._input_bg_image_id is None:
            self._input_bg_image_id = self._input_canvas.create_image(offset_x, offset_y, anchor='nw', image=self._input_bg_photo)
        else:
            self._input_canvas.itemconfigure(self._input_bg_image_id, image=self._input_bg_photo)
            self._input_canvas.coords(self._input_bg_image_id, offset_x, offset_y)

        self._input_canvas.tag_lower(self._input_bg_image_id)

    def _schedule_ui(self, callback):
        if self.window is None:
            return
        try:
            self.window.after(0, callback)
        except Exception:
            pass

    def _update_bubble_state(self, hook_type: str, payload: dict | None = None):
        hook_state = getattr(self.app, 'claude_hook_state', None)
        if hook_state is None:
            return
        try:
            hook_state.handle_hook(hook_type, payload or {})
        except Exception:
            pass

    def _clear_bubble_state(self):
        self._update_bubble_state(
            'state',
            {
                'status': 'idle',
                'bubble': '',
                'detail': '',
            },
        )

    def _handle_status_var_change(self, *_args):
        self._refresh_status_visuals()

    def _color(self, key: str) -> str:
        return self.colors.get(key, key)

    def _welcome_message(self) -> str:
        return WELCOME_MESSAGE

    def _set_widget_tree_bg(self, widget, bg: str, *, exclude=None):
        excluded = set(exclude or ())
        if widget in excluded:
            return
        try:
            widget.configure(bg=bg)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._set_widget_tree_bg(child, bg, exclude=excluded)

    def _status_palette(self, text: str) -> tuple[str, str]:
        compact = (text or '').strip()
        if any(token in compact for token in ('失败', '错误', '拒绝', '超时')):
            return self._color('danger_edge'), self._color('text_strong')
        if any(token in compact for token in ('允许', '权限', '模式', '切换')):
            return self._color('line_gold'), self._color('text_strong')
        if any(token in compact for token in ('完成', '已连接', '恢复', '创建', '清除', '空闲')):
            return self._color('accent_dark'), self._color('text_strong')
        if any(token in compact for token in ('思考', '理解', '处理中', '进行中', '呼唤')):
            return self._color('accent'), self._color('text')
        return self._color('line_strong'), self._color('muted')

    def _refresh_status_visuals(self):
        if self._status_dot is None or self._status_dot_item is None:
            return
        dot_color, text_color = self._status_palette(self.status_var.get())
        try:
            self._status_dot.itemconfigure(self._status_dot_item, fill=dot_color, outline=dot_color)
        except Exception:
            pass
        if self._status_label is not None:
            try:
                self._status_label.configure(fg=text_color)
            except Exception:
                pass
        self._refresh_aurora_palette()

    def _refresh_aurora_palette(self):
        text = self.status_var.get()
        primary, _text_color = self._status_palette(text)
        compact = (text or '').strip()
        if any(token in compact for token in ('思考', '理解', '处理中', '进行中')):
            secondary = self._color('accent_dark')
        elif any(token in compact for token in ('权限', '允许', '模式')):
            secondary = self._color('gold')
        elif any(token in compact for token in ('失败', '错误', '拒绝', '超时')):
            secondary = self._color('danger_edge')
        else:
            secondary = self._color('line_soft')
        self._aurora_colors = (primary, secondary)
        self._draw_aurora_bar()

    def _draw_aurora_bar(self):
        if self._aurora_bar is None or self._aurora_bar_item is None:
            return
        width = max(1, int(self._aurora_bar.winfo_width() or 1))
        height = max(1, int(self._aurora_bar.winfo_height() or 1))
        base_color, glow_color = self._aurora_colors
        progress = self._aurora_phase / 12.0
        left = int(width * (0.15 + 0.55 * progress))
        right = min(width, left + max(90, int(width * 0.28)))
        self._aurora_bar.coords(self._aurora_bar_item, 0, 0, width, height)
        try:
            self._aurora_bar.itemconfigure(self._aurora_bar_item, fill=base_color, outline=base_color)
        except Exception:
            pass
        self._aurora_bar.delete('aurora-glow')
        self._aurora_bar.create_rectangle(left, 0, right, height, fill=glow_color, outline=glow_color, tags='aurora-glow')

    def _tick_aurora_bar(self):
        self._aurora_bar_job = None
        if self.window is None or not self.window.winfo_exists() or self._aurora_bar is None:
            return
        self._aurora_phase += self._aurora_direction
        if self._aurora_phase >= 12:
            self._aurora_phase = 12
            self._aurora_direction = -1
        elif self._aurora_phase <= 0:
            self._aurora_phase = 0
            self._aurora_direction = 1
        self._draw_aurora_bar()
        self._aurora_bar_job = self.window.after(180, self._tick_aurora_bar)

    def _start_aurora_bar(self):
        if self.window is None or self._aurora_bar is None or self._aurora_bar_job is not None:
            return
        self._tick_aurora_bar()

    def _has_input_text(self) -> bool:
        if self.input_box is None or self._input_placeholder_active:
            return False
        return bool(self.input_box.get('1.0', tk.END).strip())

    def _show_input_placeholder(self):
        if self.input_box is None or self._has_input_text():
            return
        self._input_placeholder_active = True
        self.input_box.configure(fg=self._color('text_soft'))
        self.input_box.delete('1.0', tk.END)
        self.input_box.insert('1.0', INPUT_PLACEHOLDER)

    def _hide_input_placeholder(self):
        if self.input_box is None or not self._input_placeholder_active:
            return
        self._input_placeholder_active = False
        self.input_box.configure(fg=self._color('text'))
        self.input_box.delete('1.0', tk.END)

    def _handle_input_focus_in(self, _event=None):
        self._set_input_focus_state(True)
        if self._input_placeholder_active:
            self._hide_input_placeholder()

    def _handle_input_focus_out(self, _event=None):
        self._set_input_focus_state(False)
        if not self._has_input_text():
            self._show_input_placeholder()

    def _handle_input_keypress(self, _event=None):
        if self._input_placeholder_active:
            self._hide_input_placeholder()

    def _set_input_focus_state(self, focused: bool):
        if self._input_shell_frame is None:
            return
        border = self._color('input_focus' if focused else 'input_border')
        try:
            self._input_shell_frame.configure(bg=border)
        except Exception:
            pass

    def _initialize_content_split(self, pane, transcript_frame, composer_card):
        if self.window is None or not self.window.winfo_exists():
            return
        try:
            pane.update_idletasks()
            total_height = pane.winfo_height()
            if total_height <= 1:
                return
            composer_target = max(220, min(320, int(total_height * 0.32)))
            sash_y = max(260, total_height - composer_target)
            pane.sash_place(0, 0, sash_y)
        except Exception:
            pass

    def _create_inline_shell(
        self,
        eyebrow: str,
        title: str,
        *,
        accent='accent',
        border='line_soft',
        body_bg='panel_tinted',
        title_fg='text_strong',
    ):
        card = tk.Frame(self.text_area, bg=self._color(border), bd=0, highlightthickness=0)
        body = tk.Frame(card, bg=self._color(body_bg), bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        tk.Frame(body, bg=self._color(accent), height=3).pack(fill=tk.X)
        header = tk.Frame(body, bg=self._color(body_bg))
        header.pack(fill=tk.X, padx=self.chat_theme['inline_card_pad_x'], pady=(10, 6))
        tk.Label(
            header,
            text=eyebrow,
            font=self.fonts['eyebrow'],
            bg=self._color(body_bg),
            fg=self._color('gold'),
            anchor='w',
        ).pack(anchor='w')
        tk.Label(
            header,
            text=title,
            font=self.fonts['control'],
            bg=self._color(body_bg),
            fg=self._color(title_fg),
            anchor='w',
            justify='left',
        ).pack(anchor='w', pady=(4, 0))
        return card, body

    def _clipboard_image_to_attachment(self):
        if ImageGrab is None:
            return None
        try:
            grabbed = ImageGrab.grabclipboard()
        except Exception:
            return None
        if grabbed is None:
            return None

        image = None
        if isinstance(grabbed, Image.Image):
            image = grabbed
        elif isinstance(grabbed, list):
            for item in grabbed:
                try:
                    if isinstance(item, str) and os.path.isfile(item):
                        with Image.open(item) as opened:
                            image = opened.convert('RGBA' if opened.mode in ('RGBA', 'LA') else 'RGB')
                        break
                except Exception:
                    continue
        if image is None:
            return None

        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'A' in image.mode else 'RGB')

        output = io.BytesIO()
        save_format = 'PNG' if image.mode == 'RGBA' else 'JPEG'
        save_kwargs = {}
        if save_format == 'JPEG':
            image = image.convert('RGB')
            save_kwargs['quality'] = 92
        image.save(output, format=save_format, **save_kwargs)
        encoded = base64.b64encode(output.getvalue()).decode('ascii')
        width, height = image.size
        return {
            'type': 'image',
            'media_type': SUPPORTED_IMAGE_FORMATS[save_format],
            'data': encoded,
            'filename': f'clipboard-{datetime.now().strftime("%H%M%S")}.{save_format.lower()}',
            'dimensions': (width, height),
        }

    def _handle_input_paste(self, _event=None):
        attachment = self._clipboard_image_to_attachment()
        if attachment is None:
            return None
        self._pending_image_attachments.append(attachment)
        self._refresh_attachment_preview()
        self.status_var.set(f'已粘贴图片 {len(self._pending_image_attachments)} 张')
        return 'break'

    def _refresh_attachment_preview(self):
        frame = self._attachment_preview_frame
        if frame is None:
            return
        for child in list(frame.winfo_children()):
            child.destroy()

        if not self._pending_image_attachments:
            return

        tk.Label(
            frame,
            text=f'待发送图片 {len(self._pending_image_attachments)} 张',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
            anchor='w',
        ).pack(fill=tk.X, pady=(0, 4))

        chips = tk.Frame(frame, bg=self.colors['panel'])
        chips.pack(fill=tk.X)
        for index, item in enumerate(self._pending_image_attachments):
            chip = tk.Frame(chips, bg=self.colors['panel_tinted'], highlightbackground=self.colors['line_soft'], highlightthickness=1)
            chip.pack(fill=tk.X, pady=(0, 6))
            dims = item.get('dimensions') or ()
            size_text = ''
            if len(dims) == 2:
                size_text = f' ({dims[0]}x{dims[1]})'
            content = tk.Frame(chip, bg=self.colors['panel_tinted'])
            content.pack(fill=tk.X, expand=True)
            tk.Label(
                content,
                text=(item.get('filename') or '图片') + size_text,
                font=self.fonts['small'],
                bg=self.colors['panel_tinted'],
                fg=self.colors['text'],
                padx=8,
                pady=4,
                justify='left',
                anchor='w',
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            remove_button = tk.Label(
                content,
                text='✕',
                font=self.fonts['small'],
                bg=self.colors['panel_tinted'],
                fg=self.colors['subtext'],
                cursor='hand2',
                padx=6,
            )
            remove_button.pack(side=tk.RIGHT)
            remove_button.bind(
                '<Button-1>',
                lambda _event, idx=index: self._remove_pending_image_attachment(idx),
                add='+',
            )

    def _remove_pending_image_attachment(self, index: int):
        if index < 0 or index >= len(self._pending_image_attachments):
            return
        self._pending_image_attachments.pop(index)
        self._refresh_attachment_preview()
        if self._pending_image_attachments:
            self.status_var.set(f'还剩 {len(self._pending_image_attachments)} 张待发送图片')
        else:
            self.status_var.set('图片附件已清空')

    def _clear_pending_image_attachments(self):
        if not self._pending_image_attachments:
            return
        self._pending_image_attachments = []
        self._refresh_attachment_preview()

    def _build_message_content(self, text: str):
        clean_text = (text or '').strip()
        if not self._pending_image_attachments:
            return clean_text
        blocks = []
        for item in self._pending_image_attachments:
            blocks.append(
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': item['media_type'],
                        'data': item['data'],
                    },
                }
            )
        if clean_text:
            blocks.append({'type': 'text', 'text': clean_text})
        return blocks

    def _build_display_text(self, text: str) -> str:
        clean_text = (text or '').strip()
        image_count = len(self._pending_image_attachments)
        if image_count and clean_text:
            return f'[附带 {image_count} 张图片]\n{clean_text}'
        if image_count:
            return f'[附带 {image_count} 张图片]'
        return clean_text

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        self._create_window()
        self._start_session()
        self.window.after(EVENT_POLL_INTERVAL_MS, self._drain_events)
        # 初次把窗口放到桌宠附近；之后由桌宠的 window_snap 逻辑自动附着到本窗口
        # 顶部（与贴靠微信的机制一致），无需窗口反向跟随桌宠。
        self._position_beside_pet(initial=True)

    def _create_window(self):
        self.window = tk.Toplevel(self.parent)
        self.window.title('与奥黛丽聊聊')

        # 进程开启了 DPI 感知（main.py 中的 SetProcessDpiAwareness），但 tkinter
        # 不会自动缩放窗口几何尺寸。在高缩放屏（如 150%）上，字体会按 DPI 放大，
        # 而写死的像素高度会导致内容溢出、底部输入框被挤出窗口。这里按 DPI 缩放
        # 窗口尺寸，并限制在屏幕工作区内，保证输入区始终可见。
        try:
            scale = self.window.winfo_fpixels('1i') / 96.0
        except Exception:
            scale = 1.0
        scale = max(1.0, scale)
        base_w = self.window_theme['base_width']
        base_h = self.window_theme['base_height']
        win_w = int(base_w * scale)
        win_h = int(base_h * scale)
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        win_w = min(win_w, screen_w - 40)
        win_h = min(win_h, screen_h - 80)
        self.window.geometry(f'{win_w}x{win_h}')
        self.window.minsize(
            int(self.window_theme['min_width'] * scale),
            int(self.window_theme['min_height'] * scale),
        )
        # 全局 Ctrl+C 复制快捷键
        self.window.bind('<Control-c>', self._handle_window_copy)
        self.window.bind('<Control-C>', self._handle_window_copy)
        self.window.configure(bg=self.colors['bg_app'])
        self.window.protocol('WM_DELETE_WINDOW', self.close)

        try:
            icon_path = resource_path('gifs/audrey-hall.ico')
            self.window.iconbitmap(icon_path)
        except Exception:
            pass

        main_frame = tk.Frame(self.window, bg=self.colors['bg_app'])
        main_frame.pack(
            fill=tk.BOTH,
            expand=True,
            padx=self.window_theme['outer_pad'],
            pady=self.window_theme['outer_pad'],
        )

        body_frame = tk.Frame(main_frame, bg=self.colors['bg_app'])
        body_frame.pack(fill=tk.BOTH, expand=True)

        side_panel = create_card(
            body_frame,
            self.theme,
            bg='panel',
            border='line_soft',
        )
        side_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))
        side_panel.configure(width=self.chat_theme['sidebar_width'])
        side_panel.pack_propagate(False)

        content_frame = tk.Frame(body_frame, bg=self.colors['bg_app'])
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        header_card = create_card(
            content_frame,
            self.theme,
            bg='panel',
            border='line_soft',
        )
        header_card.pack(fill=tk.X, pady=(0, self.window_theme['header_gap']))
        tk.Frame(header_card, bg=self.colors['accent'], height=3).pack(fill=tk.X)

        header = tk.Frame(header_card, bg=self.colors['panel'])
        header.pack(
            fill=tk.X,
            padx=self.chat_theme['header_pad_x'],
            pady=self.chat_theme['header_pad_y'],
        )

        title_row = tk.Frame(header, bg=self.colors['panel'])
        title_row.pack(fill=tk.X)

        title_col = tk.Frame(title_row, bg=self.colors['panel'])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            title_col,
            text='与奥黛丽聊聊',
            font=self.fonts['hero'],
            bg=self.colors['panel'],
            fg=self.colors['text_strong'],
        ).pack(anchor='w')
        tk.Label(
            title_col,
            text='Audrey Hall x Claude Code',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
        ).pack(anchor='w', pady=(4, 0))
        tk.Label(
            title_col,
            textvariable=self._session_label_var,
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['subtext'],
        ).pack(anchor='w', pady=(6, 0))

        status_chip = create_card(
            title_row,
            self.theme,
            bg='panel_tinted',
            border='line_soft',
        )
        status_chip.pack(side=tk.RIGHT, anchor='n')
        tk.Label(
            status_chip,
            text='连接状态',
            font=self.fonts['eyebrow'],
            bg=self.colors['panel_tinted'],
            fg=self.colors['gold'],
            anchor='e',
        ).pack(anchor='e', padx=12, pady=(8, 2))
        tk.Label(
            status_chip,
            textvariable=self._connection_time_var,
            font=self.fonts['small'],
            bg=self.colors['panel_tinted'],
            fg=self.colors['accent_dark'],
            width=14,
            anchor='e',
        ).pack(anchor='e', padx=12, pady=(0, 8))

        control_card = create_card(
            content_frame,
            self.theme,
            bg='panel',
            border='line_soft',
        )
        control_card.pack(fill=tk.X, pady=(0, self.window_theme['header_gap']))
        tk.Frame(control_card, bg=self.colors['gold'], height=2).pack(fill=tk.X)

        controls = tk.Frame(control_card, bg=self.colors['panel'])
        controls.pack(
            fill=tk.X,
            padx=self.chat_theme['control_pad_x'],
            pady=self.chat_theme['control_pad_y'],
        )

        left_controls = tk.Frame(controls, bg=self.colors['panel'])
        left_controls.pack(side=tk.LEFT, fill=tk.X, expand=True)
        right_controls = tk.Frame(controls, bg=self.colors['panel'])
        right_controls.pack(side=tk.RIGHT)

        connection_dropdown = create_dropdown(
            left_controls,
            theme=self.theme,
            label='连接目标',
            value_getter=lambda: self._connection_var.get(),
            options=CONNECTION_TARGET_CHOICES,
            on_select=self._switch_connection_target,
            font=self.fonts['small'],
            width=220,
        )
        connection_dropdown.pack(side=tk.LEFT, padx=(0, self.chat_theme['control_gap']))
        self._refresh_connection_buttons()

        mode_dropdown = create_dropdown(
            left_controls,
            theme=self.theme,
            label='对话模式',
            value_getter=lambda: self._mode_var.get(),
            options=MODE_CHOICES,
            on_select=self._apply_permission_mode,
            font=self.fonts['small'],
            width=250,
        )
        mode_dropdown.pack(side=tk.LEFT)
        self._refresh_mode_buttons()

        create_button(
            right_controls,
            text='再次呼唤',
            command=lambda: self._reconnect_session(announce=True),
            theme=self.theme,
            variant='primary',
            font=self.fonts['small'],
            padx=12,
            pady=8,
        ).pack(side=tk.RIGHT)

        split_host = tk.Frame(content_frame, bg=self.colors['bg_app'])
        split_host.pack(fill=tk.BOTH, expand=True)

        content_pane = tk.PanedWindow(
            split_host,
            orient=tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.colors['bg_app'],
            opaqueresize=True,
            showhandle=False,
        )
        content_pane.pack(fill=tk.BOTH, expand=True)
        self._content_pane = content_pane

        composer_card = create_card(
            content_pane,
            self.theme,
            bg='panel',
            border='line_soft',
        )
        tk.Frame(composer_card, bg=self.colors['accent_soft'], height=2).pack(fill=tk.X)

        composer = tk.Frame(composer_card, bg=self.colors['panel'])
        composer.pack(
            fill=tk.BOTH,
            expand=True,
            padx=self.chat_theme['composer_pad_x'],
            pady=self.chat_theme['composer_pad_y'],
        )

        tk.Label(
            composer,
            text='输入工作台',
            font=self.fonts['eyebrow'],
            bg=self.colors['panel'],
            fg=self.colors['gold'],
            anchor='w',
        ).pack(anchor='w')
        tk.Label(
            composer,
            text='和奥黛丽继续对话，Ctrl+Enter 发送。',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
            anchor='w',
        ).pack(anchor='w', pady=(4, 10))

        self._attachment_preview_frame = tk.Frame(composer, bg=self.colors['panel'])
        self._attachment_preview_frame.pack(fill=tk.X, pady=(0, 8))

        self._input_shell_frame = tk.Frame(
            composer,
            bg=self.colors['input_border'],
            bd=0,
            highlightthickness=0,
        )
        self._input_shell_frame.pack(fill=tk.BOTH, expand=True)
        input_inner = tk.Frame(self._input_shell_frame, bg=self.colors['input_bg'], bd=0, highlightthickness=0)
        input_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._input_canvas = None

        self.input_box = tk.Text(
            input_inner,
            height=self.window_theme['input_height'],
            wrap=tk.WORD,
            font=self.fonts['base'],
            bg=self.colors['input_bg'],
            fg=self.colors['text'],
            relief=tk.FLAT,
            insertbackground=self.colors['accent_dark'],
            highlightthickness=0,
            bd=0,
            padx=self.chat_theme['input_pad_x'],
            pady=self.chat_theme['input_pad_y'],
        )
        self.input_box.pack(fill=tk.BOTH, expand=True)
        self.input_box.bind('<Control-Return>', self._handle_send_shortcut)
        self.input_box.bind('<Control-v>', self._handle_input_paste, add='+')
        self.input_box.bind('<Control-V>', self._handle_input_paste, add='+')
        self.input_box.bind('<<Paste>>', self._handle_input_paste, add='+')
        self.input_box.bind('<FocusIn>', self._handle_input_focus_in, add='+')
        self.input_box.bind('<FocusOut>', self._handle_input_focus_out, add='+')
        self.input_box.bind('<KeyPress>', self._handle_input_keypress, add='+')

        composer_bottom = tk.Frame(composer, bg=self.colors['panel'])
        composer_bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        status_block = tk.Frame(composer_bottom, bg=self.colors['panel'])
        status_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._aurora_bar = tk.Canvas(status_block, height=4, bg=self.colors['panel'], highlightthickness=0, bd=0)
        self._aurora_bar.pack(fill=tk.X, pady=(0, 6))
        self._aurora_bar_item = self._aurora_bar.create_rectangle(0, 0, 1, 4, fill=self.colors['line_soft'], outline=self.colors['line_soft'])
        self._aurora_bar.bind('<Configure>', lambda _event: self._draw_aurora_bar(), add='+')
        self._status_dot = tk.Canvas(status_block, width=14, height=14, bg=self.colors['panel'], highlightthickness=0, bd=0)
        self._status_dot_item = self._status_dot.create_oval(3, 3, 11, 11, fill=self.colors['line_strong'], outline=self.colors['line_strong'])
        self._status_dot.pack(side=tk.LEFT, pady=(2, 0))
        self._status_label = tk.Label(
            status_block,
            textvariable=self.status_var,
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
            anchor='w',
        )
        self._status_label.pack(side=tk.LEFT, padx=(8, 0))

        action_row = tk.Frame(composer_bottom, bg=self.colors['panel'])
        action_row.pack(side=tk.RIGHT)
        create_button(
            action_row,
            text='清除对话',
            command=self._clear_conversation,
            theme=self.theme,
            variant='ghost',
            font=self.fonts['control'],
            padx=12,
            pady=8,
        ).pack(side=tk.RIGHT)
        self.stop_button = create_button(
            action_row,
            text='中止对话',
            command=self._on_stop,
            theme=self.theme,
            variant='secondary',
            font=self.fonts['control'],
            padx=12,
            pady=8,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.send_button = create_button(
            action_row,
            text='发送',
            command=self._on_send,
            theme=self.theme,
            variant='primary',
            font=self.fonts['control'],
            padx=18,
            pady=8,
        )
        self.send_button.pack(side=tk.RIGHT, padx=(0, 8))

        transcript_frame = create_card(
            content_pane,
            self.theme,
            bg='panel',
            border='line_soft',
        )
        tk.Frame(transcript_frame, bg=self.colors['accent_soft'], height=3).pack(fill=tk.X)

        transcript_header = tk.Frame(transcript_frame, bg=self.colors['panel'])
        transcript_header.pack(
            fill=tk.X,
            padx=self.chat_theme['transcript_header_pad_x'],
            pady=self.chat_theme['transcript_header_pad_y'],
        )
        tk.Label(
            transcript_header,
            text='对话实况',
            font=self.fonts['control'],
            bg=self.colors['panel'],
            fg=self.colors['text_strong'],
            anchor='w',
        ).pack(side=tk.LEFT)
        tk.Label(
            transcript_header,
            text='陪伴中',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
            anchor='e',
        ).pack(side=tk.RIGHT)

        transcript_body = tk.Frame(transcript_frame, bg=self.colors['panel'])
        transcript_body.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(transcript_body)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_area = tk.Text(
            transcript_body,
            wrap=tk.WORD,
            font=self.fonts['base'],
            bg=self.colors['panel'],
            fg=self.colors['text'],
            bd=0,
            padx=self.chat_theme['transcript_pad_x'],
            pady=self.chat_theme['transcript_pad_y'],
            yscrollcommand=scrollbar.set,
            state=tk.DISABLED,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)
        self._transcript_container = transcript_frame
        scrollbar.config(command=self.text_area.yview)

        def sync_transcript_width(event):
            new_width = max(320, event.width - self.chat_theme['transcript_pad_x'] * 2 - 24)
            if new_width == self._transcript_width:
                return
            self._transcript_width = new_width
            self._refresh_message_layout()

        self.text_area.bind('<Configure>', sync_transcript_width, add='+')

        def _refresh_message_layout():
            """当窗口大小变化时，刷新所有消息组件的宽度，并保持滚动位置"""
            if not self._message_widgets:
                return
            # 记住当前是否在底部
            was_at_bottom = False
            try:
                yview = self.text_area.yview()
                was_at_bottom = yview[1] >= 0.99
            except Exception:
                pass
            for widget in self._message_widgets:
                try:
                    if widget.winfo_exists():
                        widget.configure(width=self._transcript_width)
                        bubble = getattr(widget, '_message_bubble', None)
                        if bubble is not None and bubble.winfo_exists():
                            max_px = getattr(widget, '_bubble_width_px', self.chat_theme['bubble_max_width'])
                            bubble.configure(width=self._pixels_to_chars(min(max_px, self._transcript_width - 140)))
                        widget.update_idletasks()
                        widget.configure(height=widget.winfo_reqheight())
                except Exception:
                    pass
            # 清理已销毁的组件引用
            self._message_widgets = [
                w for w in self._message_widgets
                if w.winfo_exists()
            ]
            # 如果之前在底部，延迟滚动回去（等 tk 完成内部重新布局）
            if was_at_bottom:
                self.text_area.after(10, lambda: self.text_area.see(tk.END))

        self._refresh_message_layout = _refresh_message_layout

        self.text_area.tag_configure('status', foreground=self.colors['muted'])
        self.text_area.tag_configure('main_status', foreground=self.colors['muted'])
        self.text_area.tag_configure('task_progress', foreground=self.colors['muted'])

        content_pane.add(transcript_frame, minsize=260, stretch='always')
        content_pane.add(composer_card, minsize=200, stretch='never')
        self.window.after(40, lambda: self._initialize_content_split(content_pane, transcript_frame, composer_card))

        self._build_history_sidebar(side_panel)
        self._refresh_history_sidebar()
        self._show_input_placeholder()
        self._refresh_status_visuals()
        self._start_aurora_bar()

        self._append_message(
            'assistant',
            self._welcome_message(),
        )

    def _build_history_sidebar(self, parent):
        tk.Frame(parent, bg=self.colors['gold'], height=3).pack(fill=tk.X)
        tk.Label(
            parent,
            text='AURORA HISTORY',
            font=self.fonts['eyebrow'],
            bg=self.colors['panel'],
            fg=self.colors['gold'],
            anchor='w',
        ).pack(fill=tk.X, padx=14, pady=(14, 4))
        tk.Label(
            parent,
            text='最近会话',
            font=self.fonts['control'],
            bg=self.colors['panel'],
            fg=self.colors['text_strong'],
            anchor='w',
        ).pack(fill=tk.X, padx=14)
        tk.Label(
            parent,
            text='恢复最近的对话记录，继续陪伴或工作。',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
            anchor='w',
            justify='left',
            wraplength=220,
        ).pack(fill=tk.X, padx=14, pady=(4, 10))

        toolbar = tk.Frame(parent, bg=self.colors['panel'])
        toolbar.pack(fill=tk.X, padx=14, pady=(0, 10))
        create_button(
            toolbar,
            text='新建会话',
            command=self._new_conversation,
            theme=self.theme,
            variant='ghost',
            font=self.fonts['small'],
            padx=8,
            pady=4,
        ).pack(side=tk.RIGHT)
        create_button(
            toolbar,
            text='刷新',
            command=self._refresh_history_sidebar,
            theme=self.theme,
            variant='ghost',
            font=self.fonts['small'],
            padx=8,
            pady=4,
        ).pack(side=tk.RIGHT, padx=(0, 6))

        tk.Frame(parent, bg=self.colors['separator'], height=1).pack(fill=tk.X, padx=14, pady=(0, 10))

        list_frame = tk.Frame(parent, bg=self.colors['panel'])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        canvas = tk.Canvas(list_frame, bg=self.colors['panel'], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._history_container = tk.Frame(canvas, bg=self.colors['panel'])
        canvas_window = canvas.create_window((0, 0), window=self._history_container, anchor='nw')

        def _sync_history_width(event):
            canvas.itemconfigure(canvas_window, width=event.width)

        def _sync_history_scroll(_event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        canvas.bind('<Configure>', _sync_history_width, add='+')
        self._history_container.bind('<Configure>', _sync_history_scroll, add='+')

        self._history_empty_label = tk.Label(
            self._history_container,
            text='还没有可恢复的历史会话。',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['muted'],
            justify='left',
            anchor='w',
            wraplength=220,
        )
        self._history_empty_label.pack(fill=tk.X, padx=6, pady=6)

        self._history_context_menu = tk.Menu(parent, tearoff=0)
        self._history_context_menu.add_command(
            label='删除会话',
            command=lambda: self._delete_session(getattr(self, '_history_context_session_id', '')),
        )

    def _history_project_dir(self) -> Path:
        return CLAUDE_PROJECTS_DIR / _sanitize_project_path(str(Path(self.session.working_dir)))

    def _read_recent_sessions(self) -> list[dict]:
        project_dir = self._history_project_dir()
        if not project_dir.exists() or not project_dir.is_dir():
            return []

        session_files = sorted(
            project_dir.glob('*.jsonl'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        items = []
        for path in session_files[:MAX_HISTORY_SESSIONS]:
            try:
                item = self._read_session_preview(path)
            except Exception:
                continue
            if item:
                items.append(item)
        return items

    def _read_session_preview(self, path: Path) -> dict | None:
        session_id = path.stem
        title = ''
        summary = ''
        first_prompt = ''
        last_timestamp = ''

        with path.open('r', encoding='utf-8', errors='replace') as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = entry.get('timestamp')
                if isinstance(timestamp, str) and timestamp.strip():
                    last_timestamp = timestamp.strip()

                entry_type = entry.get('type')
                if not title and entry_type in {'custom-title', 'summary'}:
                    candidate = entry.get('customTitle') or entry.get('summary')
                    if isinstance(candidate, str) and candidate.strip():
                        title = candidate.strip()

                if entry_type == 'last-prompt':
                    candidate = entry.get('lastPrompt')
                    if isinstance(candidate, str) and candidate.strip():
                        first_prompt = candidate.strip()

                if entry_type == 'user' and not first_prompt:
                    message = entry.get('message') or {}
                    content = message.get('content') if isinstance(message, dict) else None
                    if isinstance(content, str) and content.strip():
                        first_prompt = content.strip()

                candidate_summary = entry.get('summary')
                if isinstance(candidate_summary, str) and candidate_summary.strip():
                    summary = candidate_summary.strip()

        display_title = self._compact_history_label(title or first_prompt or session_id)
        display_summary = self._compact_history_label(summary or first_prompt)
        return {
            'session_id': session_id,
            'title': display_title or session_id,
            'summary': display_summary,
            'timestamp': last_timestamp,
            'path': str(path),
        }

    def _compact_history_label(self, value) -> str:
        if not isinstance(value, str):
            return ''
        first_line = value.splitlines()[0].strip() if value.splitlines() else ''
        compact = ' '.join(first_line.split())
        if not compact:
            return ''
        if len(compact) <= MAX_HISTORY_LABEL_CHARS:
            return compact
        return compact[:MAX_HISTORY_LABEL_CHARS] + '...'

    def _format_session_label(self) -> str:
        session_id = (self._active_session_id or self._resume_session_id or '').strip()
        if not session_id:
            return '当前会话：新对话'
        return f'当前会话：{session_id[:8]}'

    def _current_session_id(self) -> str:
        return (self._active_session_id or self._resume_session_id or '').strip()

    def _refresh_history_sidebar(self):
        self._history_items = self._read_recent_sessions()
        if self._history_container is None:
            return

        for child in list(self._history_container.winfo_children()):
            child.destroy()

        if not self._history_items:
            self._history_empty_label = tk.Label(
                self._history_container,
                text='还没有可恢复的历史会话。\n开始一次新的对话，记录就会出现在这里。',
                font=self.fonts['small'],
                bg=self.colors['panel'],
                fg=self.colors['muted'],
                justify='left',
                anchor='w',
                wraplength=self.chat_theme['history_wraplength'],
            )
            self._history_empty_label.pack(fill=tk.X, padx=8, pady=8)
            return

        for item in self._history_items:
            self._render_history_item(item)

    def _render_history_item(self, item: dict):
        session_id = item.get('session_id') or ''
        is_active = session_id == self._current_session_id()
        card_bg = self.colors['gold_soft'] if is_active else self.colors['panel_tinted']
        border = self.colors['line_gold'] if is_active else self.colors['line_soft']
        accent = self.colors['gold'] if is_active else self.colors['accent_soft']
        card = tk.Frame(self._history_container, bg=border, bd=0, highlightthickness=0, cursor='hand2')
        inner = tk.Frame(card, bg=card_bg, bd=0, highlightthickness=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        card.pack(fill=tk.X, padx=4, pady=4)
        accent_bar = tk.Frame(inner, bg=accent, width=4)
        accent_bar.pack(side=tk.LEFT, fill=tk.Y)
        content = tk.Frame(inner, bg=card_bg)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title = item.get('title') or item.get('session_id')
        summary = item.get('summary') or ''
        timestamp = self._format_history_timestamp(item.get('timestamp') or '')

        title_row = tk.Frame(content, bg=card_bg)
        title_row.pack(fill=tk.X, padx=10, pady=(8, 2))
        tk.Label(
            title_row,
            text=title,
            font=self.fonts['control'],
            bg=card_bg,
            fg=self.colors['text_strong'],
            justify='left',
            anchor='w',
            wraplength=self.chat_theme['history_wraplength'] - 24,
        ).pack(side=tk.LEFT)

        delete_btn = tk.Label(
            title_row,
            text='✕',
            font=self.fonts['small'],
            bg=card_bg,
            fg=self.colors['subtext'],
            cursor='hand2',
            padx=6,
        )
        delete_btn.pack(side=tk.RIGHT)

        def handle_delete(_event=None, sid=session_id):
            self._delete_session(sid)
            return 'break'

        delete_btn.bind('<Button-1>', handle_delete, add='+')
        def _on_delete_enter(_event, btn=delete_btn):
            btn.configure(fg=self.colors['text_strong'])
        def _on_delete_leave(_event, btn=delete_btn):
            btn.configure(fg=self.colors['subtext'])
        delete_btn.bind('<Enter>', _on_delete_enter, add='+')
        delete_btn.bind('<Leave>', _on_delete_leave, add='+')

        def show_context_menu(event, sid=session_id):
            if not sid or self._history_context_menu is None:
                return
            self._history_context_session_id = sid
            try:
                self._history_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._history_context_menu.grab_release()
            return 'break'

        if summary:
            tk.Label(
                content,
                text=summary,
                font=self.fonts['small'],
                bg=card_bg,
                fg=self.colors['muted'],
                justify='left',
                anchor='w',
                wraplength=self.chat_theme['history_wraplength'],
            ).pack(fill=tk.X, padx=10)
        tk.Label(
            content,
            text=f'{timestamp}  {session_id[:8]}',
            font=self.fonts['small'],
            bg=card_bg,
            fg=self.colors['subtext'],
            justify='left',
            anchor='w',
        ).pack(fill=tk.X, padx=10, pady=(6, 8))

        def _apply_history_hover(active: bool):
            if is_active:
                return
            current_bg = self.colors['panel_elevated'] if active else card_bg
            current_border = self.colors['line_strong'] if active else border
            card.configure(bg=current_border)
            inner.configure(bg=current_bg)
            content.configure(bg=current_bg)
            accent_bar.configure(bg=self.colors['accent'] if active else accent)
            self._set_widget_tree_bg(content, current_bg, exclude={delete_btn})
            delete_btn.configure(bg=current_bg)

        card.bind('<Enter>', lambda _event: _apply_history_hover(True), add='+')
        card.bind('<Leave>', lambda _event: _apply_history_hover(False), add='+')
        inner.bind('<Enter>', lambda _event: _apply_history_hover(True), add='+')
        inner.bind('<Leave>', lambda _event: _apply_history_hover(False), add='+')

        def handle_click(_event=None, target_session_id=session_id):
            self._resume_history_session(target_session_id)

        for widget in (card, inner):
            widget.bind('<Button-1>', handle_click, add='+')
            widget.bind('<Button-3>', show_context_menu, add='+')
        for widget in content.winfo_children():
            widget.bind('<Button-1>', handle_click, add='+')
            if widget is not delete_btn:
                widget.bind('<Button-3>', show_context_menu, add='+')
            for grandchild in widget.winfo_children():
                if grandchild is not delete_btn:
                    grandchild.bind('<Button-1>', handle_click, add='+')
                    grandchild.bind('<Button-3>', show_context_menu, add='+')

    def _format_history_timestamp(self, value: str) -> str:
        if not value:
            return '未知时间'
        try:
            normalized = value.replace('Z', '+00:00')
            parsed = datetime.fromisoformat(normalized)
            return parsed.strftime('%m-%d %H:%M')
        except Exception:
            return value[:16]

    def _resume_history_session(self, session_id: str):
        target = (session_id or '').strip()
        if not target:
            return
        if self._busy:
            self._append_inline_status('Claude 正在处理当前请求，稍后再恢复历史会话。')
            return

        self._resume_session_id = target
        self._active_session_id = target
        self._reset_transcript_view()
        self._load_session_transcript_preview(target)
        self._append_inline_status(f'正在恢复历史会话：{target[:8]}')
        self._reconnect_session(announce=True)
        self._refresh_history_sidebar()
        # 侧边栏重建可能触发布局变化导致滚动位置跳动，延迟确保视图在底部
        if self.text_area is not None:
            self.text_area.after(50, lambda: self.text_area.see(tk.END))

    def _delete_session_file(self, session_id: str):
        """删除磁盘上的会话记录文件"""
        if not session_id or not session_id.strip():
            return
        project_dir = self._history_project_dir()
        session_path = project_dir / f'{session_id.strip()}.jsonl'
        try:
            if session_path.exists():
                session_path.unlink()
        except Exception:
            pass

    def _delete_session(self, session_id: str):
        """从侧边栏删除一个历史会话"""
        sid = (session_id or '').strip()
        if not sid:
            return

        # 如果删除的是当前正在使用的会话，先清除对话
        if sid == self._current_session_id():
            if self._busy:
                self._append_inline_status('Claude 正在处理当前请求，暂时不能删除当前会话。')
                return
            self._resume_session_id = ''
            self._active_session_id = ''
            self._reset_transcript_view()
            self._append_message(
                'assistant',
                self._welcome_message(),
            )
            self._append_inline_status('已删除当前会话，准备开启新对话。')
            self._reconnect_session(announce=True)

        self._delete_session_file(sid)
        self._refresh_history_sidebar()

    def _clear_conversation(self):
        if self._busy:
            self._append_inline_status('Claude 正在处理当前请求，暂时不能清除对话。')
            return

        # 保存当前会话 ID，用于后续删除文件
        current_session_id = self._current_session_id()

        self._resume_session_id = ''
        self._active_session_id = ''
        self._reset_transcript_view()
        self._append_message(
            'assistant',
            self._welcome_message(),
        )
        self._append_inline_status('已清除当前对话，准备开启新会话。')
        self._reconnect_session(announce=True)

        # 同时删除旧的会话文件，这样侧边栏也会随之更新
        if current_session_id:
            self._delete_session_file(current_session_id)

        self._refresh_history_sidebar()

    def _new_conversation(self):
        if self._busy:
            self._append_inline_status('Claude 正在处理当前请求，请稍后再新建会话。')
            return

        self._resume_session_id = ''
        self._active_session_id = ''
        self._reset_transcript_view()
        self._append_message(
            'assistant',
            self._welcome_message(),
        )
        self._append_inline_status('已创建新会话。')
        self._reconnect_session(announce=True)
        self._refresh_history_sidebar()

    def _reset_transcript_view(self):
        self._conversation_history = []
        self._pending_perm_frames = {}
        self._message_widgets = []
        self._main_status_text = ''
        self._task_progress_text = ''
        self._last_summary_status = ''
        self._current_total_tokens = None
        self._current_input_tokens = None
        self._current_output_tokens = None
        if self.text_area is not None:
            self.text_area.config(state=tk.NORMAL)
            self.text_area.delete('1.0', tk.END)
            self.text_area.config(state=tk.DISABLED)
        self.status_var.set('正在唤醒奥黛丽的助手...')

    def _load_session_transcript_preview(self, session_id: str):
        project_dir = self._history_project_dir()
        session_path = project_dir / f'{session_id}.jsonl'
        if not session_path.exists():
            return

        loaded = 0
        try:
            with session_path.open('r', encoding='utf-8', errors='replace') as handle:
                for raw_line in handle:
                    if loaded >= 24:
                        break
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry_type = entry.get('type')
                    if entry_type not in {'user', 'assistant'}:
                        continue
                    role, text = self._extract_transcript_entry(entry)
                    if not role or not text:
                        continue
                    self._append_message(role, text, record_history=False)
                    loaded += 1
        except Exception:
            return

    def _extract_transcript_entry(self, entry: dict) -> tuple[str, str]:
        entry_type = entry.get('type')
        if entry_type not in {'user', 'assistant'}:
            return '', ''

        role = 'assistant' if entry_type == 'assistant' else 'user'
        message = entry.get('message') or {}
        content = message.get('content') if isinstance(message, dict) else None
        if isinstance(content, str):
            text = content.strip()
            return role, text
        if not isinstance(content, list):
            return '', ''

        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get('type')
            if block_type == 'text':
                value = block.get('text')
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            elif block_type == 'thinking':
                continue
        text = '\n\n'.join(parts).strip()
        if not text:
            return '', ''
        return role, text

    def _get_pet(self):
        """获取主桌宠对象（manager.pets[0]）"""
        pets = getattr(self.app, 'pets', None)
        if pets:
            return pets[0]
        return None

    def _position_beside_pet(self, initial=False):
        """初次把对话窗口摆到桌宠附近。之后桌宠会自动附着到窗口顶部。"""
        pet = self._get_pet()
        if pet is None or self.window is None or not self.window.winfo_exists():
            return
        try:
            pet_x = int(getattr(pet, 'x', pet.root.winfo_x()))
            pet_y = int(getattr(pet, 'y', pet.root.winfo_y()))
            pet_h = int(getattr(pet, 'h', pet.root.winfo_height()))
        except Exception:
            return

        win_w = self.window.winfo_width() or self.window.winfo_reqwidth()
        win_h = self.window.winfo_height() or self.window.winfo_reqheight()
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()

        gap = 8
        # 桌宠会贴靠到窗口顶部，所以把窗口放在桌宠正下方，左对齐桌宠。
        x = pet_x
        y = pet_y + pet_h + gap
        x = max(0, min(x, screen_w - win_w))
        # 若下方放不下，则放到桌宠上方
        if y + win_h > screen_h:
            y = max(0, pet_y - win_h - gap)
        self.window.geometry(f'+{int(x)}+{int(y)}')

    def _handle_send_shortcut(self, _event):
        self._on_send()
        return 'break'

    def _on_send(self):
        if self._input_placeholder_active:
            text = ''
        else:
            text = self.input_box.get('1.0', tk.END).strip()
        if not text and not self._pending_image_attachments:
            return

        if text and self._handle_local_command(text):
            self.input_box.delete('1.0', tk.END)
            self._show_input_placeholder()
            return

        if self._busy:
            if self._pending_image_attachments:
                self._append_inline_status('当前正在对话中；图片附件暂不支持旁路插话。')
                return
            if not text:
                return
            self._append_inline_status(f'旁路提问：{text}')
            self.input_box.delete('1.0', tk.END)
            self._show_input_placeholder()
            self._handle_btw_command(text)
            return

        self.input_box.delete('1.0', tk.END)
        self._show_input_placeholder()
        payload = self._build_message_content(text)
        display_text = self._build_display_text(text)
        self._submit_prompt(payload, display_text=display_text)

    def _submit_prompt(self, text: str | list[dict], display_text: str | None = None):
        if isinstance(text, str):
            prompt_text = text.strip()
            if not prompt_text:
                return
            visible_text = display_text or prompt_text
            payload = prompt_text
        else:
            payload = text
            if not payload:
                return
            visible_text = (display_text or '').strip() or '[图片消息]'

        self._append_message('user', visible_text)
        self.status_var.set('奥黛丽 正在思考...')
        self._set_busy(True)
        self._update_bubble_state('thinking', {'prompt': visible_text})

        try:
            self.session.send_user_message(payload)
            self._clear_pending_image_attachments()
        except Exception as exc:
            self._set_busy(False)
            self.status_var.set('发送失败')
            self._clear_bubble_state()
            self._append_message('error', f'发送失败：{exc}')
            self._show_input_placeholder()

    def _handle_local_command(self, text: str) -> bool:
        if not text.startswith('/'):
            return False

        command_text = text[1:].strip()
        if not command_text:
            return False

        command, _, raw_args = command_text.partition(' ')
        command = command.lower()
        args = raw_args.strip()

        if command == 'model':
            self._append_message('user', text, record_history=False)
            self._handle_model_command(args)
            return True

        if command == 'mode':
            self._append_message('user', text, record_history=False)
            self._handle_mode_command(args)
            return True

        if command == 'btw':
            self._append_message('user', text, record_history=False)
            self._handle_btw_command(args)
            return True

        if command == 'cost':
            return False

        self._append_message('user', text, record_history=False)
        self._append_message(
            'warn',
            f'当前对话框尚未适配本地命令：/{command}。当前已支持：/model、/mode、/btw；/cost 将交给 Claude Code 处理。',
        )
        return True

    def _format_mode_status(self):
        return MODE_LABELS.get(self._active_permission_mode, self._active_permission_mode)

    def _refresh_mode_buttons(self):
        self._mode_var.set(self._format_mode_status())

    def _set_active_permission_mode(self, mode: str, *, announce: bool = False):
        normalized = (mode or 'default').strip() or 'default'
        if normalized not in MODE_LABELS:
            normalized = 'default'
        changed = normalized != self._active_permission_mode
        self._active_permission_mode = normalized
        self._refresh_mode_buttons()
        if announce and changed:
            label = MODE_LABELS.get(normalized, normalized)
            self.status_var.set(f'模式已切换：{label}')
            self._append_inline_status(f'模式已切换：{label}')

    def _apply_permission_mode(self, mode: str):
        normalized = (mode or '').strip()
        if normalized not in MODE_LABELS:
            self._append_message('error', f'不支持的模式：{mode}')
            return
        try:
            self.session.set_permission_mode(normalized)
        except Exception as exc:
            self._append_message('error', f'切换模式失败：{exc}')
            return

        label = MODE_LABELS[normalized]
        self.status_var.set(f'正在切换模式：{label}')

    def _handle_mode_command(self, args: str):
        normalized = args.strip()
        lowered = normalized.lower()

        if not normalized:
            available = ' | '.join(mode for mode, _ in MODE_CHOICES)
            self._append_inline_status(
                f'当前模式：{MODE_LABELS.get(self._active_permission_mode, self._active_permission_mode)}；可用：{available}'
            )
            return

        if lowered in {'help', '-h', '--help', '?'}:
            self._append_inline_status('用法：/mode [default|acceptEdits|auto|plan]')
            return

        if lowered in {'info', 'status'}:
            self._append_inline_status(self._format_mode_status())
            return

        mode_aliases = {
            'default': 'default',
            'acceptedits': 'acceptEdits',
            'accept': 'acceptEdits',
            'edits': 'acceptEdits',
            'auto': 'auto',
            'plan': 'plan',
        }
        target_mode = mode_aliases.get(lowered)
        if target_mode is None:
            self._append_message('warn', '不支持的模式。可用：default、acceptEdits、auto、plan。')
            return

        self._apply_permission_mode(target_mode)

    def _handle_model_command(self, args: str):
        normalized = args.strip()
        lowered = normalized.lower()

        if not normalized:
            self._show_model_picker_card()
            return

        if lowered in {'help', '-h', '--help', '?'}:
            self._append_inline_status(
                '用法：/model [default|sonnet|opus|haiku|best|sonnet[1m]|opus[1m]|opusplan]'
            )
            return

        if lowered in {'info', 'status'}:
            self._append_inline_status(f'当前模型：{self._active_model}')
            return

        target_model = None if lowered == 'default' else normalized
        self._apply_model_selection(target_model)

    def _apply_model_selection(self, model: str | None):
        try:
            self.session.set_model(model)
        except Exception as exc:
            self._append_message('error', f'切换模型失败：{exc}')
            return

        self._active_model = 'default' if model is None else model
        self.status_var.set(f'模型已切换：{self._active_model}')
        self._append_inline_status(f'模型已切换：{self._active_model}')

    def _show_model_picker_card(self):
        card, body = self._create_inline_shell('MODEL PICKER', '选择模型', accent='accent', body_bg='assistant')
        tk.Label(
            text='点击按钮切换，或直接输入 /model <模型名>',
            font=self.fonts['small'],
            bg=self.colors['assistant'],
            fg=self.colors['muted'],
            anchor='w',
        ).pack(in_=body, fill=tk.X, padx=14, pady=(0, 8))

        rows = [MODEL_QUICK_CHOICES[index : index + 2] for index in range(0, len(MODEL_QUICK_CHOICES), 2)]
        for row_choices in rows:
            row = tk.Frame(body, bg=self.colors['assistant'])
            row.pack(fill=tk.X, padx=14, pady=(0, 8))
            for choice in row_choices:
                create_button(
                    row,
                    text=choice,
                    command=lambda selected=choice: self._handle_model_choice(selected, card),
                    theme=self.theme,
                    variant='secondary',
                    font=self.fonts['control'],
                    padx=10,
                ).pack(side=tk.LEFT, padx=(0, 8))

        self._insert_inline_card(card)

    def _handle_model_choice(self, selected: str, card):
        try:
            card.destroy()
        except Exception:
            pass
        self._apply_model_selection(None if selected == 'default' else selected)

    def _handle_btw_command(self, args: str):
        question = args.strip()
        if not question:
            self._append_inline_status('用法：/btw <你的旁路问题>')
            return

        card, body = self._create_inline_shell('SIDE QUESTION', '/btw 旁路问题', accent='accent', body_bg='assistant')
        tk.Label(
            text=question,
            font=self.fonts['base'],
            bg=self.colors['assistant'],
            fg=self.colors['text'],
            wraplength=self.chat_theme['permission_wraplength'],
            justify='left',
            anchor='w',
        ).pack(in_=body, fill=tk.X, padx=14, pady=(0, 6))

        status_label = tk.Label(
            body,
            text='回答中...',
            font=self.fonts['small'],
            bg=self.colors['assistant'],
            fg=self.colors['muted'],
            justify='left',
            anchor='w',
            wraplength=self.chat_theme['permission_wraplength'],
        )
        status_label.pack(fill=tk.X, padx=14, pady=(0, 8))

        action_row = tk.Frame(body, bg=self.colors['assistant'])
        action_row.pack(fill=tk.X, padx=14, pady=(0, 10))
        create_button(
            action_row,
            text='关闭',
            command=lambda: self._destroy_widget(card),
            theme=self.theme,
            variant='secondary',
            font=self.fonts['control'],
            padx=12,
        ).pack(side=tk.LEFT)

        self._insert_inline_card(card)

        worker = threading.Thread(
            target=self._run_side_question,
            args=(question, status_label),
            daemon=True,
        )
        worker.start()

    def _run_side_question(self, question: str, status_label):
        ready_event = threading.Event()
        done_event = threading.Event()
        state = {'answer': '', 'error': ''}

        def on_event(event: dict):
            kind = event.get('kind')
            if kind == 'status' and event.get('status') == 'ready':
                ready_event.set()
                return
            if kind == 'assistant':
                text = (event.get('text') or '').strip()
                if text:
                    state['answer'] = text
                return
            if kind == 'done':
                if event.get('ok'):
                    if not state['answer']:
                        state['answer'] = (event.get('text') or '').strip()
                else:
                    state['error'] = (event.get('text') or '旁路问题执行失败').strip()
                done_event.set()
                return
            if kind == 'error':
                state['error'] = (event.get('text') or '旁路问题执行失败').strip()
                done_event.set()

        side_session = ClaudeCodeSession(
            on_event,
            working_dir=getattr(self.session, 'working_dir', None),
            connection_target=self._connection_target,
        )

        try:
            side_session.start()
            if not ready_event.wait(20):
                state['error'] = '旁路问题会话初始化超时'
            else:
                side_session.send_user_message(self._build_side_question_prompt(question))
                if not done_event.wait(120):
                    state['error'] = '旁路问题等待超时'
        except Exception as exc:
            state['error'] = f'旁路问题失败：{exc}'
        finally:
            try:
                side_session.close()
            except Exception:
                pass

        final_text = state['error'] or state['answer'] or '未收到结果'
        self._schedule_ui(lambda: self._update_side_question_result(status_label, final_text, bool(state['error'])))

    def _build_side_question_prompt(self, question: str) -> str:
        recent = self._conversation_history[-MAX_SIDE_CONTEXT_MESSAGES:]
        excerpt_parts = []
        total_chars = 0
        for item in reversed(recent):
            entry = f"{'用户' if item['role'] == 'user' else '助手'}: {item['text'].strip()}"
            if not item['text'].strip():
                continue
            if excerpt_parts and total_chars + len(entry) > MAX_SIDE_CONTEXT_CHARS:
                break
            excerpt_parts.append(entry)
            total_chars += len(entry)

        excerpt = '\n\n'.join(reversed(excerpt_parts)).strip() or '无最近主对话上下文。'
        return (
            '你是 Claude Code 的旁路问答助手。下面是当前主对话最近的上下文，仅供回答侧边问题参考。'
            '不要继续执行主任务，也不要假设你能修改主会话状态。\n\n'
            f'主对话摘录：\n{excerpt}\n\n'
            f'侧边问题：{question}\n\n'
            '请直接、简洁地回答这个侧边问题。'
        )

    def _update_side_question_result(self, status_label, text: str, is_error: bool):
        if status_label is None:
            return
        try:
            status_label.config(
                text=text,
                fg=self.colors['text'] if not is_error else self.colors['danger_edge'],
            )
        except Exception:
            pass

    def _destroy_widget(self, widget):
        try:
            widget.destroy()
        except Exception:
            pass

    def _insert_inline_card(self, card):
        self.text_area.config(state=tk.NORMAL)
        self.text_area.insert(tk.END, '\n')
        self.text_area.window_create(tk.END, window=card, padx=6, pady=4)
        self.text_area.insert(tk.END, '\n\n')
        self.text_area.config(state=tk.DISABLED)
        self.text_area.see(tk.END)

    def _on_stop(self):
        try:
            self.session.interrupt()
            self.status_var.set('已请求停止')
        except Exception as exc:
            self._append_message('error', f'停止失败：{exc}')

    def _enqueue_event(self, event: dict):
        self._event_queue.put(event)

    def _drain_events(self):
        if self.window is None or not self.window.winfo_exists():
            return

        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

        self.window.after(EVENT_POLL_INTERVAL_MS, self._drain_events)

    def _handle_event(self, event: dict):
        kind = event.get('kind')

        if kind == 'assistant':
            text = event.get('text') or ''
            self._update_total_tokens(event.get('total_tokens'))
            self._update_total_io_tokens(event.get('input_tokens'), event.get('output_tokens'))
            reminder_text = self._translate_system_reminder(text)
            if reminder_text:
                self._render_summary_status(reminder_text)
                return
            if text:
                self._append_message('assistant', text)
                self._maybe_show_choice_buttons(text)
            return

        if kind == 'working':
            tool_name = event.get('tool_name')
            input_payload = event.get('input') or {}
            self._update_total_tokens(event.get('total_tokens'))
            self._update_total_io_tokens(event.get('input_tokens'), event.get('output_tokens'))
            self._update_bubble_state(
                'working',
                {
                    'tool_name': tool_name,
                    'input': input_payload,
                },
            )
            self._render_main_status(self._format_main_tool_status(event))
            return

        if kind == 'thinking':
            self._update_total_tokens(event.get('total_tokens'))
            self._update_total_io_tokens(event.get('input_tokens'), event.get('output_tokens'))
            reminder_text = self._translate_system_reminder(event.get('text') or '')
            if reminder_text:
                self._render_main_status(reminder_text)
                return
            self._render_thinking_status(event.get('output_tokens'))
            return

        if kind == 'status':
            text = event.get('text') or ''
            session_id = event.get('session_id')
            if isinstance(session_id, str) and session_id.strip():
                normalized_session_id = session_id.strip()
                self._active_session_id = normalized_session_id
                if self._resume_session_id and self._resume_session_id != normalized_session_id:
                    self._resume_session_id = normalized_session_id
                elif not self._resume_session_id:
                    self._resume_session_id = normalized_session_id
                self._session_label_var.set(self._format_session_label())

            status = event.get('status')

            # 连接成功：重置计时器到实际连上时刻，显示已连接确认
            if status == 'ready':
                self._connection_start_time = datetime.now()
                self._update_connection_time()
                target_label = CONNECTION_OPTION_LABELS.get(self._connection_target, self._connection_target)
                self._append_inline_status(f'已连接：{target_label}')
                self.status_var.set(self._compose_status_text(f'已连接：{target_label}'))

            # 连接断开：清除计时器
            if status == 'disconnected':
                self._connection_start_time = None
                self._connection_time_var.set('')
                if self._connection_time_timer is not None:
                    try:
                        self.window.after_cancel(self._connection_time_timer)
                    except Exception:
                        pass
                    self._connection_time_timer = None

            if text:
                self._render_main_status(text)
                connection_target = event.get('connection_target')
                if isinstance(connection_target, str):
                    self._set_connection_target(connection_target)
                if status == 'working' and not event.get('tool_name') and event.get('source') != 'system':
                    self._update_bubble_state('working', {'message': text})
            return

        if kind == 'task_progress':
            self._update_total_tokens_from_task(event)
            self._render_task_progress(event)
            return

        if kind == 'tool_use_summary':
            self._render_main_status(event.get('summary') or '')
            return

        if kind == 'tool_progress':
            self._render_main_status(self._format_tool_progress(event))
            return

        if kind == 'hook_status':
            self._render_main_status(self._format_hook_status(event))
            return

        if kind == 'sdk_status':
            self._handle_sdk_status(event)
            return

        if kind == 'session_state':
            self._handle_session_state(event)
            return

        if kind == 'post_turn_summary':
            self._render_post_turn_summary(event)
            return

        if kind == 'permission_mode':
            mode = event.get('mode')
            if isinstance(mode, str):
                self._set_active_permission_mode(mode, announce=True)
            return

        if kind == 'stderr':
            text = event.get('text') or ''
            if text:
                reminder_text = self._translate_system_reminder(text)
                if reminder_text:
                    self._render_main_status(reminder_text)
                else:
                    self._append_message('warn', text)
            return

        if kind == 'permission':
            self._update_bubble_state(
                'permission',
                {
                    'tool_name': event.get('tool_name'),
                    'input': event.get('input') or {},
                },
            )
            self._handle_permission_request(event)
            return

        if kind == 'done':
            self._set_busy(False)
            self._update_total_tokens(event.get('total_tokens'))
            self._update_total_io_tokens(event.get('input_tokens'), event.get('output_tokens'))
            self._clear_main_status()
            self._clear_task_progress()
            self._update_bubble_state('done', {'result': event.get('text') or ''})
            self._refresh_history_sidebar()
            if event.get('ok'):
                self.status_var.set(self._compose_status_text('本轮对话完成'))
            else:
                self.status_var.set(self._compose_status_text('Claude Code 返回错误'))
                text = event.get('text') or '执行失败'
                self._append_message('error', text)
            return

        if kind == 'error':
            self._set_busy(False)
            self._clear_main_status()
            self._clear_task_progress()
            if event.get('request_subtype') == 'set_permission_mode':
                self.status_var.set(self._compose_status_text('模式切换失败'))
            else:
                self.status_var.set(self._compose_status_text('Claude Code 发生错误'))
            self._clear_bubble_state()
            self._append_message('error', event.get('text') or '未知错误')

    def _handle_permission_request(self, event: dict):
        tool_name = event.get('tool_name') or '未知工具'
        request_id = event.get('request_id')

        # 该工具已被“总是允许” -> 直接放行，不再打扰
        if tool_name in self._auto_allow_tools:
            self.session.respond_permission(request_id, True)
            self._append_inline_status(f'已自动允许工具调用：{tool_name}')
            self._update_bubble_state(
                'working',
                {
                    'tool_name': tool_name,
                    'input': event.get('input') or {},
                },
            )
            return

        self._show_permission_card(request_id, tool_name, event.get('input') or {})

    def _show_permission_card(self, request_id, tool_name, input_payload):
        """在对话流中内嵌一张权限确认卡片，不再弹出抢焦点的模态窗。"""
        summary = json.dumps(input_payload, ensure_ascii=False, indent=2)
        if len(summary) > self.chat_theme['permission_summary_max_chars']:
            summary = summary[: self.chat_theme['permission_summary_max_chars']] + ' …'
        style = self._permission_card_style()

        self.text_area.config(state=tk.NORMAL)
        self.text_area.insert(tk.END, '\n')

        card, card_body = self._create_inline_shell(
            'AURORA PERMISSION',
            f'请求执行工具：{tool_name}',
            accent='gold',
            border='line_gold',
            body_bg='panel_tinted',
        )

        if input_payload:
            summary_frame = tk.Frame(card_body, bg=style['summary_bg'])
            summary_frame.pack(fill=tk.X, padx=14, pady=(0, 10))
            tk.Label(
                summary_frame,
                text=summary,
                font=self.fonts['mono'],
                bg=style['summary_bg'],
                fg=style['summary_fg'],
                anchor='w',
                justify='left',
                wraplength=self.chat_theme['permission_wraplength'],
                padx=12,
                pady=10,
            ).pack(fill=tk.X)

        btn_row = tk.Frame(card_body, bg=style['card_bg'])
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 12))

        def resolve(allow, always=False):
            if always and allow:
                self._auto_allow_tools.add(tool_name)
            self.session.respond_permission(request_id, allow)
            self._clear_main_status()
            self._clear_task_progress()
            frame = self._pending_perm_frames.pop(request_id, None)
            if frame is not None:
                try:
                    frame.destroy()
                except Exception:
                    pass
            if allow:
                txt = f'总是允许工具：{tool_name}' if always else f'已允许工具调用：{tool_name}'
                self._update_bubble_state(
                    'working',
                    {
                        'tool_name': tool_name,
                        'input': input_payload or {},
                    },
                )
            else:
                txt = f'已拒绝工具调用：{tool_name}'
            self._render_main_status(txt)

        create_button(
            btn_row,
            text='允许',
            command=lambda: resolve(True),
            theme=self.theme,
            variant='primary',
            font=self.fonts['control'],
            style_overrides=style['button_primary'],
            padx=12,
            pady=7,
        ).pack(side=tk.LEFT)
        create_button(
            btn_row,
            text='总是允许',
            command=lambda: resolve(True, always=True),
            theme=self.theme,
            variant='secondary',
            font=self.fonts['control'],
            style_overrides=style['button_secondary'],
            padx=12,
            pady=7,
        ).pack(side=tk.LEFT, padx=(8, 0))
        create_button(
            btn_row,
            text='拒绝',
            command=lambda: resolve(False),
            theme=self.theme,
            variant='secondary',
            font=self.fonts['control'],
            style_overrides=style['button_danger'],
            padx=12,
            pady=7,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.text_area.window_create(tk.END, window=card, padx=6, pady=4)
        self.text_area.insert(tk.END, '\n\n')
        self.text_area.config(state=tk.DISABLED)
        self.text_area.see(tk.END)
        self._pending_perm_frames[request_id] = card

    def _set_busy(self, busy: bool):
        self._busy = busy
        if self.send_button is not None:
            self.send_button.config(
                state=tk.NORMAL,
                text='我插个话...' if busy else '发送',
            )
        if self.stop_button is not None:
            self.stop_button.config(state=tk.NORMAL if busy else tk.DISABLED)

    def _append_inline_status(self, text: str):
        if self.text_area is None:
            compact = self._task_progress_compact_text(text)
            if compact:
                self.status_var.set(compact)
            return
        self.text_area.config(state=tk.NORMAL)
        self.text_area.insert(tk.END, f'[状态] {text}\n\n', ('status',))
        self.text_area.config(state=tk.DISABLED)
        self.text_area.see(tk.END)

    def _clear_main_status(self):
        if self.text_area is None:
            self._main_status_text = ''
            return
        if not self._main_status_text:
            return
        ranges = self.text_area.tag_ranges('main_status')
        self.text_area.config(state=tk.NORMAL)
        if len(ranges) >= 2:
            self.text_area.delete(ranges[0], ranges[-1])
        self.text_area.config(state=tk.DISABLED)
        self._main_status_text = ''

    def _render_main_status(self, text: str):
        compact = self._compose_status_text(text)
        if not compact:
            return
        if compact == self._main_status_text:
            self.status_var.set(compact)
            return

        if self.text_area is None:
            self._main_status_text = compact
            self.status_var.set(compact)
            return

        ranges = self.text_area.tag_ranges('main_status')
        self.text_area.config(state=tk.NORMAL)
        if len(ranges) >= 2:
            self.text_area.delete(ranges[0], ranges[-1])
        self.text_area.insert(tk.END, f'[状态] {compact}\n\n', ('status', 'main_status'))
        self.text_area.config(state=tk.DISABLED)
        self.text_area.see(tk.END)
        self._main_status_text = compact
        self.status_var.set(compact)

    def _clear_task_progress(self):
        if self.text_area is None:
            self._task_progress_text = ''
            return
        if not self._task_progress_text:
            return
        ranges = self.text_area.tag_ranges('task_progress')
        self.text_area.config(state=tk.NORMAL)
        if len(ranges) >= 2:
            self.text_area.delete(ranges[0], ranges[-1])
        self.text_area.config(state=tk.DISABLED)
        self._task_progress_text = ''

    def _render_task_progress(self, event: dict):
        text = self._format_task_progress(event)
        if not text:
            return
        if text == self._task_progress_text:
            return

        self.status_var.set(text)
        if self.text_area is None:
            self._task_progress_text = text
            return

        ranges = self.text_area.tag_ranges('task_progress')
        self.text_area.config(state=tk.NORMAL)
        if len(ranges) >= 2:
            self.text_area.delete(ranges[0], ranges[-1])
        self.text_area.insert(tk.END, f'[状态] {text}\n\n', ('status', 'task_progress'))
        self.text_area.config(state=tk.DISABLED)
        self.text_area.see(tk.END)
        self._task_progress_text = text
        self._last_summary_status = ''

    def _format_task_progress(self, event: dict) -> str:
        status = str(event.get('status') or 'running').strip().lower()
        task_id = str(event.get('task_id') or '').strip()
        description = self._task_progress_compact_text(event.get('description'))
        summary = self._task_progress_compact_text(event.get('summary'))
        tool_name = self._task_progress_compact_text(event.get('last_tool_name'))
        workflow = event.get('workflow_progress')
        workflow_text = self._extract_workflow_progress_text(workflow)
        task_tokens = self._task_usage_total_tokens(event.get('usage'))
        action = workflow_text or tool_name or summary or description or '处理中'
        status_label = {
            'started': '启动',
            'running': '进行中',
            'completed': '完成',
            'failed': '失败',
            'stopped': '停止',
        }.get(status, '进行中')

        details = []
        if task_id:
            details.append(task_id[:8])
        if description:
            details.append(description)
        detail_text = ' | '.join(details)

        base = f'子任务[{status_label}] {action}'
        if detail_text:
            base = f'{base} ({detail_text})'
        suffix_parts = []
        if task_tokens is not None:
            suffix_parts.append(f'<task {self._format_token_count(task_tokens)}>')
        suffix = (' ' + ' '.join(suffix_parts)) if suffix_parts else ''
        available_px = MAX_STATUS_WIDTH_PX - self._measure_status_text_px(suffix)
        available_px = max(MIN_STATUS_CORE_WIDTH_PX, available_px)
        base = self._truncate_text_to_px(base, available_px)
        return base + suffix

    def _update_total_tokens(self, total_tokens):
        if isinstance(total_tokens, int) and total_tokens > 0:
            self._current_total_tokens = total_tokens

    def _update_total_io_tokens(self, input_tokens, output_tokens):
        if isinstance(input_tokens, int) and input_tokens > 0:
            self._current_input_tokens = input_tokens
        if isinstance(output_tokens, int) and output_tokens > 0:
            self._current_output_tokens = output_tokens

    def _update_total_tokens_from_task(self, event: dict):
        task_tokens = self._task_usage_total_tokens(event.get('usage'))
        if task_tokens is not None and (
            self._current_total_tokens is None or task_tokens > self._current_total_tokens
        ):
            self._current_total_tokens = task_tokens

    def _task_usage_total_tokens(self, usage) -> int | None:
        if not isinstance(usage, dict):
            return None
        total = usage.get('total_tokens')
        if isinstance(total, int) and total > 0:
            return total

        fields = (
            'input_tokens',
            'output_tokens',
            'cache_creation_input_tokens',
            'cache_read_input_tokens',
            'cache_deleted_input_tokens',
        )
        values = []
        for field in fields:
            value = usage.get(field)
            if isinstance(value, int) and value > 0:
                values.append(value)
        if values:
            return sum(values)
        return None

    def _usage_input_output_tokens(self, usage) -> tuple[int | None, int | None]:
        if not isinstance(usage, dict):
            return None, None
        input_tokens = usage.get('input_tokens')
        output_tokens = usage.get('output_tokens')
        return (
            input_tokens if isinstance(input_tokens, int) and input_tokens > 0 else None,
            output_tokens if isinstance(output_tokens, int) and output_tokens > 0 else None,
        )

    def _with_total_tokens(self, text: str) -> str:
        if not isinstance(self._current_total_tokens, int) or self._current_total_tokens <= 0:
            return text
        return f'{text} <total {self._format_token_count(self._current_total_tokens)}>'

    def _format_token_count(self, value: int) -> str:
        if value >= 1_000_000:
            return f'{value / 1_000_000:.1f}M tok'
        if value >= 1_000:
            return f'{value / 1_000:.1f}k tok'
        return f'{value} tok'

    def _extract_workflow_progress_text(self, workflow_progress) -> str:
        if not isinstance(workflow_progress, list):
            return ''
        for item in reversed(workflow_progress):
            if not isinstance(item, dict):
                continue
            for key in ('label', 'message', 'status', 'title', 'text', 'kind'):
                text = self._task_progress_compact_text(item.get(key))
                if text:
                    return text
        return ''

    def _task_progress_compact_text(self, value) -> str:
        if not isinstance(value, str):
            return ''
        text = ' '.join(value.strip().split())
        if not text:
            return ''
        return text if len(text) <= 240 else text[:237] + '...'

    def _render_summary_status(self, text: str):
        compact = self._task_progress_compact_text(text)
        if not compact:
            return
        compact = self._compose_status_text(compact)
        if compact == self._last_summary_status:
            return
        self._append_inline_status(compact)
        self.status_var.set(compact)
        self._last_summary_status = compact

    def _render_thinking_status(self, output_tokens: int | None = None):
        compact = '正在理解...'
        thinking_tokens = output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else None
        if thinking_tokens is None:
            current_output = getattr(self, '_current_output_tokens', None)
            if isinstance(current_output, int) and current_output > 0:
                thinking_tokens = current_output
        if thinking_tokens is not None:
            compact = f'{compact} <{self._format_token_count(thinking_tokens)}>'
        self._render_main_status(compact)

    def _compose_status_text(self, core_text: str, task_tokens: int | None = None) -> str:
        core = self._task_progress_compact_text(core_text)
        if not core:
            return ''
        suffix = self._build_status_suffix(task_tokens)
        available_px = MAX_STATUS_WIDTH_PX - self._measure_status_text_px(suffix)
        available_px = max(MIN_STATUS_CORE_WIDTH_PX, available_px)
        core = self._truncate_text_to_px(core, available_px)
        return core + suffix

    def _build_status_suffix(self, task_tokens: int | None = None) -> str:
        if task_tokens is not None:
            return f' <task {self._format_token_count(task_tokens)}>'
        current_total_tokens = getattr(self, '_current_total_tokens', None)
        if isinstance(current_total_tokens, int) and current_total_tokens > 0:
            return f' <task {self._format_token_count(current_total_tokens)}>'
        return ''

    def _compose_arrow_tokens(self, *, input_tokens: int | None, output_tokens: int | None) -> str:
        parts = []
        if input_tokens is not None:
            parts.append(f'↓ {self._format_token_count(input_tokens)}')
        if output_tokens is not None:
            parts.append(f'↑ {self._format_token_count(output_tokens)}')
        return f"<{', '.join(parts)}>" if parts else ''

    def _measure_status_text_px(self, text: str) -> int:
        if not text:
            return 0
        try:
            font = tkfont.Font(font=self.fonts['base'])
            return int(font.measure(text))
        except Exception:
            return len(text) * 8

    def _truncate_text_to_px(self, text: str, max_px: int) -> str:
        if not text or max_px <= 0:
            return ''
        if self._measure_status_text_px(text) <= max_px:
            return text

        ellipsis = '...'
        ellipsis_px = self._measure_status_text_px(ellipsis)
        if ellipsis_px >= max_px:
            return ellipsis

        low = 0
        high = len(text)
        best = ellipsis
        while low <= high:
            mid = (low + high) // 2
            candidate = text[:mid].rstrip() + ellipsis
            if self._measure_status_text_px(candidate) <= max_px:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _translate_system_reminder(self, text: str) -> str:
        if not isinstance(text, str):
            return ''
        match = re.fullmatch(r'\s*<system-reminder>\s*([\s\S]*?)\s*</system-reminder>\s*', text)
        if match:
            reminder = ' '.join(match.group(1).strip().split())
        else:
            partial = re.search(r'<system-reminder>\s*([\s\S]*?)\s*</system-reminder>', text)
            if not partial:
                return ''
            reminder = ' '.join(partial.group(1).strip().split())
        mode_change = re.search(r'operational mode has changed from\s+(\w+)\s+to\s+(\w+)', reminder, re.IGNORECASE)
        if mode_change:
            old_mode = mode_change.group(1)
            new_mode = mode_change.group(2)
            old_mode = {'plan': '计划', 'build': '构建'}.get(old_mode.lower(), old_mode)
            new_mode = {'plan': '计划', 'build': '构建'}.get(new_mode.lower(), new_mode)
            detail = f'模式切换：{old_mode} -> {new_mode}'
            if 'no longer in read-only mode' in reminder.lower():
                detail += '，已解除只读'
            if 'permitted to make file changes' in reminder.lower():
                detail += '，可改文件/跑命令/用工具'
            return detail

        return reminder

    def _format_tool_progress(self, event: dict) -> str:
        tool_name = self._task_progress_compact_text(event.get('tool_name')) or '工具'
        elapsed = event.get('elapsed_time_seconds')
        task_id = self._task_progress_compact_text(event.get('task_id'))
        parts = [f'{tool_name} 运行中']
        if isinstance(elapsed, (int, float)) and elapsed >= 0:
            parts.append(f'{int(elapsed)}s')
        if task_id:
            parts.append(task_id[:8])
        return ' | '.join(parts)

    def _format_hook_status(self, event: dict) -> str:
        hook_name = self._task_progress_compact_text(event.get('hook_name')) or 'Hook'
        hook_event = self._task_progress_compact_text(event.get('hook_event'))
        phase = self._task_progress_compact_text(event.get('phase'))
        outcome = self._task_progress_compact_text(event.get('outcome'))
        detail = (
            self._task_progress_compact_text(event.get('output'))
            or self._task_progress_compact_text(event.get('stdout'))
            or self._task_progress_compact_text(event.get('stderr'))
        )
        parts = [hook_name]
        if hook_event:
            parts.append(hook_event)
        if phase:
            parts.append(phase)
        if outcome:
            parts.append(outcome)
        text = ' | '.join(parts)
        if detail:
            text = f'{text} | {detail}'
        return text

    def _format_main_tool_status(self, event: dict) -> str:
        tool_name = self._task_progress_compact_text(event.get('tool_name')) or '工具'
        summary = self._task_progress_compact_text(event.get('summary'))
        if summary:
            return f'{tool_name} ({summary})'
        return tool_name

    def _handle_sdk_status(self, event: dict):
        permission_mode = event.get('permission_mode')
        if isinstance(permission_mode, str):
            self._set_active_permission_mode(permission_mode, announce=True)
        status = event.get('status')
        if status == 'compacting':
            self._render_main_status('正在压缩上下文...')
        elif isinstance(status, str) and status:
            if status == 'thinking_tokens':
                self._render_main_status('正在思考...')
            else:
                self._render_main_status(status)

    def _handle_session_state(self, event: dict):
        state = self._task_progress_compact_text(event.get('state'))
        if state == 'running':
            return
        if state == 'idle':
            self._render_main_status('当前轮次已空闲')
        elif state:
            self._render_main_status(f'会话状态：{state}')

    def _render_post_turn_summary(self, event: dict):
        title = self._task_progress_compact_text(event.get('title'))
        description = self._task_progress_compact_text(event.get('description'))
        recent_action = self._task_progress_compact_text(event.get('recent_action'))
        needs_action = self._task_progress_compact_text(event.get('needs_action'))
        status_category = self._task_progress_compact_text(event.get('status_category'))
        status_detail = self._task_progress_compact_text(event.get('status_detail'))

        parts = []
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        if recent_action:
            parts.append(f'最近动作: {recent_action}')
        if needs_action:
            parts.append(f'后续: {needs_action}')
        if status_category or status_detail:
            parts.append(f'状态: {(status_category + " " + status_detail).strip()}')
        if parts:
            self._append_message('warn', '\n'.join(parts))

    def _get_assistant_avatar(self):
        if self._assistant_avatar is not None or self._avatar_source is None:
            return self._assistant_avatar

        avatar = self._avatar_source.resize((48, 48), Image.Resampling.LANCZOS)
        self._assistant_avatar = ImageTk.PhotoImage(avatar)
        return self._assistant_avatar

    def _get_user_avatar(self):
        if self._user_avatar is not None or self._user_avatar_source is None:
            return self._user_avatar

        avatar = self._user_avatar_source.resize((48, 48), Image.Resampling.LANCZOS)
        self._user_avatar = ImageTk.PhotoImage(avatar)
        return self._user_avatar

    def _create_message_widget(self, role: str, text: str):
        container = tk.Frame(self.text_area, bg=self.colors['panel'], width=self._transcript_width)
        is_user = role == 'user'
        is_assistant = role == 'assistant'
        is_error = role == 'error'
        is_warn = role == 'warn'

        bubble_bg = self.colors['assistant_bubble']
        border_color = self.colors['assistant_edge']
        strip_color = self.colors['accent_soft']
        label_text = '奥黛丽'
        bubble_width_px = self.chat_theme['bubble_max_width']
        if is_user:
            bubble_bg = self.colors['user_bubble']
            border_color = self.colors['user_edge']
            strip_color = self.colors['gold_soft']
            label_text = '你'
            bubble_width_px = self.chat_theme['user_bubble_max_width']
        elif is_error:
            bubble_bg = self.colors['danger_bg']
            border_color = self.colors['danger_edge']
            strip_color = self.colors['danger_edge']
            label_text = '系统'
        elif is_warn:
            bubble_bg = self.colors['warn']
            border_color = self.colors['warn_edge']
            strip_color = self.colors['gold_soft']
            label_text = '提示'

        row = tk.Frame(container, bg=self.colors['panel'], width=self._transcript_width)
        row.pack(fill=tk.X)

        timestamp = datetime.now().strftime('%Y年%m月%d日 %H:%M')

        if is_user:
            avatar_col = tk.Frame(row, bg=self.colors['panel'])
            avatar_col.pack(side=tk.RIGHT, anchor='s', padx=(12, 0))

            user_avatar = self._get_user_avatar()
            if user_avatar is not None:
                tk.Label(avatar_col, image=user_avatar, bg=self.colors['panel'], bd=0).pack(anchor='e')
            else:
                fallback = tk.Canvas(avatar_col, width=48, height=48, bg='#E8F1FF', highlightthickness=0, bd=0)
                fallback.create_text(24, 24, text='你', font=self.fonts['title'], fill=self.colors['accent_dark'])
                fallback.pack(anchor='e')

            content_col = tk.Frame(row, bg=self.colors['panel'])
            content_col.pack(side=tk.RIGHT, fill=tk.X, expand=True)

            bubble_wrap = tk.Frame(content_col, bg=border_color)
            bubble_wrap.pack(anchor='e', fill=tk.NONE)

            bubble_inner = tk.Frame(bubble_wrap, bg=bubble_bg)
            bubble_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            tk.Frame(bubble_inner, bg=strip_color, height=self.chat_theme['bubble_strip_height']).pack(fill=tk.X)

            text_width_chars = self._pixels_to_chars(bubble_width_px)
            text_height = self._calc_text_display_lines(text, text_width_chars)
            bubble = tk.Text(
                bubble_inner,
                font=self.fonts['base'],
                bg=bubble_bg,
                fg=self.colors['text_strong'],
                wrap=tk.WORD,
                width=text_width_chars,
                height=text_height,
                padx=self.chat_theme['bubble_pad_x'],
                pady=self.chat_theme['bubble_pad_y'],
                highlightthickness=0,
                bd=0,
                relief=tk.FLAT,
                cursor='arrow',
                exportselection=True,
                spacing1=4,
                spacing3=4,
            )
            bubble.insert('1.0', text)
            bubble.configure(state=tk.DISABLED)
            bubble.pack(anchor='e')
            container._message_bubble = bubble
            container._bubble_width_px = bubble_width_px
            self._bind_message_copy_events(bubble, text)

            meta = tk.Frame(content_col, bg=self.colors['panel'])
            meta.pack(anchor='e', pady=(6, 0))
            tk.Label(
                meta,
                text=label_text,
                font=self.fonts['control'],
                bg=self.colors['panel'],
                fg=self.colors['muted'],
            ).pack(side=tk.LEFT)
            tk.Label(
                meta,
                text=timestamp,
                font=self.fonts['small'],
                bg=self.colors['panel'],
                fg=self.colors['subtext'],
            ).pack(side=tk.LEFT, padx=(10, 0))
        else:
            avatar_col = tk.Frame(row, bg=self.colors['panel'])
            avatar_col.pack(side=tk.LEFT, anchor='n', padx=(0, 12))

            avatar = self._get_assistant_avatar()
            if avatar is not None:
                tk.Label(avatar_col, image=avatar, bg=self.colors['panel'], bd=0).pack(anchor='n')
            else:
                fallback = tk.Canvas(avatar_col, width=48, height=48, bg=self.colors['gold_soft'], highlightthickness=0, bd=0)
                fallback.create_text(24, 24, text='奥', font=self.fonts['title'], fill=self.colors['gold_deep'])
                fallback.pack(anchor='n')

            content_col = tk.Frame(row, bg=self.colors['panel'])
            content_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

            bubble_wrap = tk.Frame(content_col, bg=border_color)
            bubble_wrap.pack(anchor='w', fill=tk.NONE)
            bubble_inner = tk.Frame(bubble_wrap, bg=bubble_bg)
            bubble_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            tk.Frame(bubble_inner, bg=strip_color, height=self.chat_theme['bubble_strip_height']).pack(fill=tk.X)

            text_width_chars = self._pixels_to_chars(bubble_width_px)
            text_height = self._calc_text_display_lines(text, text_width_chars)
            bubble = tk.Text(
                bubble_inner,
                font=self.fonts['base'],
                bg=bubble_bg,
                fg=self.colors['text_strong'],
                wrap=tk.WORD,
                width=text_width_chars,
                height=text_height,
                padx=self.chat_theme['bubble_pad_x'],
                pady=self.chat_theme['bubble_pad_y'],
                highlightthickness=0,
                bd=0,
                relief=tk.FLAT,
                cursor='arrow',
                exportselection=True,
                spacing1=4,
                spacing3=4,
            )
            bubble.insert('1.0', text)
            bubble.configure(state=tk.DISABLED)
            bubble.pack(anchor='w')
            container._message_bubble = bubble
            container._bubble_width_px = bubble_width_px
            self._bind_message_copy_events(bubble, text)

            meta = tk.Frame(content_col, bg=self.colors['panel'])
            meta.pack(anchor='w', pady=(6, 0))
            tk.Label(
                meta,
                text=label_text,
                font=self.fonts['control'],
                bg=self.colors['panel'],
                fg=self.colors['muted'],
            ).pack(side=tk.LEFT)
            tk.Label(
                meta,
                text=timestamp,
                font=self.fonts['small'],
                bg=self.colors['panel'],
                fg=self.colors['subtext'],
            ).pack(side=tk.LEFT, padx=(10, 0))

        container.update_idletasks()
        container.configure(width=self._transcript_width, height=row.winfo_reqheight())
        container.pack_propagate(False)
        self._message_widgets.append(container)
        return container

    def _append_message(self, role: str, text: str, *, record_history: bool = True):
        reminder_text = self._translate_system_reminder(text)
        if reminder_text:
            self._render_main_status(reminder_text)
            return
        self.text_area.config(state=tk.NORMAL)
        card = self._create_message_widget(role, text)
        self.text_area.insert(tk.END, '\n')
        self.text_area.window_create(tk.END, window=card, padx=4, pady=4)
        self.text_area.insert(tk.END, '\n')
        self.text_area.config(state=tk.DISABLED)
        self.text_area.see(tk.END)

        if record_history and role in {'user', 'assistant'}:
            self._conversation_history.append({'role': role, 'text': text})
            self._conversation_history = self._conversation_history[-12:]

    def _maybe_show_choice_buttons(self, text: str):
        options = self._extract_choice_options(text)
        if len(options) < 2:
            return

        card, body = self._create_inline_shell('QUICK REPLY', '快速选择', accent='accent', body_bg='panel_tinted')
        tk.Label(
            text='点击按钮可直接回复，也可以继续手动输入。',
            font=self.fonts['small'],
            bg=self.colors['panel_tinted'],
            fg=self.colors['muted'],
            anchor='w',
        ).pack(in_=body, fill=tk.X, padx=14, pady=(0, 8))

        for option in options:
            button_text = option['label']
            if option['detail']:
                button_text = f"{option['label']}\n{option['detail']}"
            create_button(
                body,
                text=button_text,
                command=lambda reply=option['label'], frame=card: self._handle_choice_selection(reply, frame),
                theme=self.theme,
                variant='secondary',
                font=self.fonts['control'],
                padx=12,
                pady=6,
                justify='left',
                anchor='w',
                wraplength=self.chat_theme['permission_wraplength'],
            ).pack(fill=tk.X, padx=14, pady=(0, 8))

        self._insert_inline_card(card)

    def _handle_choice_selection(self, reply_text: str, card):
        self._destroy_widget(card)
        if self._busy:
            self._append_inline_status('Claude 正在处理上一个请求，请稍后再试。')
            return
        self._submit_prompt(reply_text)

    def _extract_choice_options(self, text: str):
        options = []
        seen = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = None
            for pattern in CHOICE_LINE_PATTERNS:
                match = pattern.match(line)
                if match:
                    break
            if not match:
                continue

            label = (match.group(1) or '').strip().strip('`')
            detail = (match.group(2) or '').strip()
            if not label or label in seen:
                continue
            seen.add(label)
            options.append({'label': label, 'detail': detail})

        if 2 <= len(options) <= 6:
            return options
        return []

    # ── 文本选择与复制支持 ──────────────────────────────────────────

    def _pixels_to_chars(self, pixel_width: int) -> int:
        """将像素宽度转换为以当前字体为基准的字符宽度。"""
        try:
            font = tkfont.Font(font=self.fonts['base'])
            # 使用中文字符测量，因为对话主要是中文
            char_px = font.measure('中')
            if char_px <= 0:
                char_px = 10
            return max(20, pixel_width // char_px)
        except Exception:
            return 50

    def _calc_text_display_lines(self, text: str, char_width: int) -> int:
        """估算文本在给定字符宽度下所需的显示行数。"""
        lines = text.count('\n') + 1
        # 为每行中超出宽度的部分增加额外的换行估算
        for line in text.split('\n'):
            if len(line) > char_width:
                lines += len(line) // char_width
        return max(1, min(lines, 40))

    def _copy_to_clipboard(self, text: str):
        """将文本复制到系统剪贴板。"""
        if not text or self.window is None:
            return
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
        except Exception:
            pass

    def _copy_selection_to_clipboard(self, widget):
        """将 Text 组件中选中的文本复制到剪贴板。"""
        try:
            if not widget.winfo_exists():
                return
            if hasattr(widget, 'tag_ranges'):
                ranges = widget.tag_ranges(tk.SEL)
                if ranges and len(ranges) >= 2:
                    selected = widget.get(ranges[0], ranges[-1])
                    if selected:
                        self._copy_to_clipboard(selected)
                        return True
        except Exception:
            pass
        return False

    def _handle_window_copy(self, event):
        """窗口级 Ctrl+C 处理器：优先复制选中文本，否则复制焦点组件内容。"""
        try:
            focused = self.window.focus_get()
            if focused is not None and hasattr(focused, 'tag_ranges'):
                if self._copy_selection_to_clipboard(focused):
                    return
            # 如果焦点在主 text_area，尝试从中取选中文本
            if self.text_area is not None:
                try:
                    ranges = self.text_area.tag_ranges(tk.SEL)
                    if ranges and len(ranges) >= 2:
                        selected = self.text_area.get(ranges[0], ranges[-1])
                        if selected:
                            self._copy_to_clipboard(selected)
                except Exception:
                    pass
        except Exception:
            pass

    # ── 消息组件右键复制菜单 ──────────────────────────────────────

    def _show_message_context_menu(self, event, text: str, widget):
        """在消息气泡上显示右键复制菜单。"""
        menu = tk.Menu(event.widget, tearoff=0)
        menu.add_command(
            label='复制全文',
            command=lambda: self._copy_to_clipboard(text),
        )
        menu.add_command(
            label='复制选中内容',
            command=lambda: self._copy_selection_to_clipboard(widget),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _bind_message_copy_events(self, widget, full_text: str):
        """为消息 Text 组件绑定选择/复制相关事件。"""
        # 右键菜单
        widget.bind(
            '<Button-3>',
            lambda e, t=full_text, w=widget: self._show_message_context_menu(e, t, w),
        )
        # 允许通过点击获得焦点（用于 Ctrl+C 复制）
        widget.bind('<Button-1>', lambda e: e.widget.focus_set(), add='+')

    def close(self):
        if self._aurora_bar_job is not None and self.window is not None:
            try:
                self.window.after_cancel(self._aurora_bar_job)
            except Exception:
                pass
            self._aurora_bar_job = None
        if self._connection_time_timer is not None:
            try:
                self.window.after_cancel(self._connection_time_timer)
            except Exception:
                pass
            self._connection_time_timer = None

        try:
            self.session.close()
        except Exception:
            pass

        self._clear_bubble_state()

        if getattr(self.app, 'chat_window', None) is self:
            self.app.chat_window = None

        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None


def show_chat_dialog(parent, app, version):
    if hasattr(app, 'show_chat_window'):
        app.show_chat_window(parent, version)
        return

    chat = ChatWindow(parent, app, version)
    chat.show()
