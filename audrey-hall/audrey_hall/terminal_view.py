import json
import tkinter as tk

from .ui import create_button, create_card
from .ui.animations import animate_toplevel_slide_in


class TerminalViewWindow:
    def __init__(self, parent, theme, *, on_close=None):
        self.parent = parent
        self.theme = theme
        self.on_close = on_close
        self.fonts = theme['fonts']
        self.colors = theme['colors']
        self.window = None
        self.text_area = None
        self._events = []
        self._show_raw = False
        self._auto_scroll = True
        self._raw_button = None
        self._scroll_button = None
        self._width = 560
        self._height = 720
        self._geometry_initialized = False

    def is_open(self) -> bool:
        return self.window is not None and self.window.winfo_exists()

    def show(self, *, initial_events=None, host_window=None):
        if self.is_open():
            if initial_events is not None:
                self.load_buffer(initial_events)
            if host_window is not None:
                self.sync_with_host(host_window)
            self.window.lift()
            return

        self._create_window()
        if initial_events is not None:
            self.load_buffer(initial_events)
        else:
            self._rerender()
        if host_window is not None:
            self.sync_with_host(host_window, animate=True)
        self.window.lift()

    def hide(self, *, notify=True):
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        self.window = None
        self.text_area = None
        self._raw_button = None
        self._scroll_button = None
        self._geometry_initialized = False
        if notify and self.on_close is not None:
            try:
                self.on_close()
            except Exception:
                pass

    close = hide

    def set_show_raw(self, value: bool):
        self._show_raw = bool(value)
        self._refresh_button_labels()
        self._rerender()

    def load_buffer(self, events):
        self._events = list(events or [])[-800:]
        self._rerender()

    def consume_event(self, event: dict):
        kind = event.get('kind')
        if kind not in {'terminal_line', 'stdout_raw_line', 'stderr_raw_line'}:
            return
        self._events.append(dict(event))
        self._events = self._events[-800:]
        if self.is_open():
            self._append_event(event)

    def clear_view(self):
        self._events = []
        if self.text_area is None:
            return
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete('1.0', tk.END)
        self.text_area.config(state=tk.DISABLED)

    def sync_with_host(self, host_window, *, animate=False):
        if host_window is None or not self.is_open():
            return
        try:
            host_window.update_idletasks()
            self.window.update_idletasks()
            host_x = host_window.winfo_x()
            host_y = host_window.winfo_y()
            host_w = host_window.winfo_width() or host_window.winfo_reqwidth()
            screen_w = host_window.winfo_screenwidth()
            screen_h = host_window.winfo_screenheight()
            width = self.window.winfo_width() or self._width
            height = self.window.winfo_height() or self._height
            gap = 12
            x = host_x + host_w + gap
            if x + width > screen_w:
                x = max(0, host_x - width - gap)
            y = max(0, min(host_y, screen_h - height - 40))
            geometry = f'{width}x{height}+{int(x)}+{int(y)}'
            if animate and not self._geometry_initialized:
                animate_toplevel_slide_in(self.window, int(x), int(y), width, height)
            else:
                self.window.geometry(geometry)
            self._geometry_initialized = True
        except Exception:
            pass

    def _create_window(self):
        host = self.parent.winfo_toplevel() if self.parent is not None else None
        self.window = tk.Toplevel(host)
        self.window.title('终端实况')
        self.window.configure(bg=self.colors['bg'])
        self.window.minsize(420, 320)
        self.window.geometry(f'{self._width}x{self._height}')
        self.window.protocol('WM_DELETE_WINDOW', self.hide)

        frame = tk.Frame(self.window, bg=self.colors['bg'])
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        header = create_card(frame, self.theme, bg='panel', border='border')
        header.pack(fill=tk.X, pady=(0, 10))

        title_row = tk.Frame(header, bg=self.colors['panel'])
        title_row.pack(fill=tk.X, padx=12, pady=(12, 6))
        tk.Label(
            title_row,
            text='AURORA TERMINAL VIEW',
            font=self.fonts['small'],
            bg=self.colors['panel'],
            fg=self.colors['gold'],
            anchor='w',
        ).pack(anchor='w')
        tk.Label(
            title_row,
            text='Claude 流式输出镜像（非 PTY 真终端）',
            font=self.fonts['control'],
            bg=self.colors['panel'],
            fg=self.colors['text'],
            anchor='w',
        ).pack(anchor='w', pady=(4, 0))

        toolbar = tk.Frame(header, bg=self.colors['panel'])
        toolbar.pack(fill=tk.X, padx=12, pady=(0, 12))
        self._raw_button = create_button(
            toolbar,
            text='原始 JSON：关',
            command=self._toggle_raw,
            theme=self.theme,
            variant='secondary',
            font=self.fonts['small'],
            padx=8,
            pady=4,
        )
        self._raw_button.pack(side=tk.LEFT)
        self._scroll_button = create_button(
            toolbar,
            text='自动滚动：开',
            command=self._toggle_auto_scroll,
            theme=self.theme,
            variant='secondary',
            font=self.fonts['small'],
            padx=8,
            pady=4,
        )
        self._scroll_button.pack(side=tk.LEFT, padx=(8, 0))
        create_button(
            toolbar,
            text='清空',
            command=self.clear_view,
            theme=self.theme,
            variant='secondary',
            font=self.fonts['small'],
            padx=8,
            pady=4,
        ).pack(side=tk.RIGHT)
        create_button(
            toolbar,
            text='隐藏',
            command=self.hide,
            theme=self.theme,
            variant='secondary',
            font=self.fonts['small'],
            padx=8,
            pady=4,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        body = create_card(frame, self.theme, bg='panel', border='border')
        body.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(body)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_area = tk.Text(
            body,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg='#F9FBFA',
            fg='#334344',
            bd=0,
            padx=14,
            pady=14,
            yscrollcommand=scrollbar.set,
            state=tk.DISABLED,
            insertbackground='#334344',
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_area.yview)

        self.text_area.tag_configure('meta', foreground='#8A9C9E')
        self.text_area.tag_configure('thinking', foreground='#7A6B56')
        self.text_area.tag_configure('tool', foreground='#2F7D79')
        self.text_area.tag_configure('result', foreground='#586265')
        self.text_area.tag_configure('stderr', foreground='#B24444')
        self.text_area.tag_configure('raw', foreground='#9AA8AA')
        self.text_area.tag_configure('done', foreground='#4C7F4C')

        self._refresh_button_labels()

    def _toggle_raw(self):
        self._show_raw = not self._show_raw
        self._refresh_button_labels()
        self._rerender()

    def _toggle_auto_scroll(self):
        self._auto_scroll = not self._auto_scroll
        self._refresh_button_labels()

    def _refresh_button_labels(self):
        if self._raw_button is not None:
            self._raw_button.config(text=f'原始 JSON：{"开" if self._show_raw else "关"}')
        if self._scroll_button is not None:
            self._scroll_button.config(text=f'自动滚动：{"开" if self._auto_scroll else "关"}')

    def _rerender(self):
        if self.text_area is None:
            return
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete('1.0', tk.END)
        for event in self._events:
            self._append_event(event, mutate_state=False)
        self.text_area.config(state=tk.DISABLED)
        if self._auto_scroll:
            self.text_area.see(tk.END)

    def _append_event(self, event: dict, *, mutate_state=True):
        if self.text_area is None:
            return
        kind = event.get('kind')
        if kind in {'stdout_raw_line', 'stderr_raw_line'} and not self._show_raw:
            return

        if mutate_state:
            self.text_area.config(state=tk.NORMAL)

        if kind == 'terminal_line':
            self._append_terminal_line(event)
        elif kind == 'stdout_raw_line':
            parsed_type = str(event.get('parsed_type') or 'json')
            raw_line = str(event.get('raw_line') or '')
            self._append_prefixed_block(f'[stdout:{parsed_type}] {raw_line}', 'raw', event.get('ts'))
        elif kind == 'stderr_raw_line':
            raw_line = str(event.get('raw_line') or '')
            self._append_prefixed_block(f'[stderr] {raw_line}', 'raw', event.get('ts'))

        if mutate_state:
            self.text_area.config(state=tk.DISABLED)
            if self._auto_scroll:
                self.text_area.see(tk.END)

    def _append_terminal_line(self, event: dict):
        text = str(event.get('text') or '').strip()
        if not text:
            return
        line_kind = str(event.get('line_kind') or 'info')
        if line_kind == 'thinking':
            tag = 'thinking'
        elif line_kind in {'tool_use', 'task_progress', 'hook_status', 'permission'}:
            tag = 'tool'
        elif line_kind in {'tool_result', 'status'}:
            tag = 'result'
        elif line_kind in {'stderr', 'error'}:
            tag = 'stderr'
        elif line_kind == 'done':
            tag = 'done'
        else:
            tag = 'meta'
        self._append_prefixed_block(text, tag, event.get('ts'))

    def _append_prefixed_block(self, text: str, tag: str, ts):
        prefix = f'[{ts}] ' if isinstance(ts, str) and ts else ''
        lines = text.splitlines() or ['']
        for index, line in enumerate(lines):
            head = prefix if index == 0 else ' ' * len(prefix)
            self.text_area.insert(tk.END, head, ('meta',))
            self.text_area.insert(tk.END, line + '\n', (tag,))
