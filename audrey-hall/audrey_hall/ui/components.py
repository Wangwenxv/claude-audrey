from copy import deepcopy
from functools import lru_cache
import tkinter as tk

from PIL import Image, ImageTk

from ..utils import resource_path


def _resolve_color(theme, value):
    if value is None:
        return None
    return theme['colors'].get(value, value)


def _hex_to_rgb(color):
    color = color.lstrip('#')
    if len(color) != 6:
        raise ValueError(f'Unsupported color value: {color}')
    return tuple(int(color[index:index + 2], 16) for index in range(0, 6, 2))


def _rgb_to_hex(rgb):
    red, green, blue = rgb
    return f'#{red:02x}{green:02x}{blue:02x}'


def _blend_colors(start, end, progress):
    progress = max(0.0, min(1.0, progress))
    start_rgb = _hex_to_rgb(start)
    end_rgb = _hex_to_rgb(end)
    blended = tuple(
        int(start_channel + (end_channel - start_channel) * progress)
        for start_channel, end_channel in zip(start_rgb, end_rgb)
    )
    return _rgb_to_hex(blended)


def _ease_out_cubic(progress):
    """ease-out：进入快、收尾慢，符合 Material/HIG 的微交互手感。"""
    progress = max(0.0, min(1.0, progress))
    return 1 - (1 - progress) ** 3


class ColorTween:
    """在一组命名颜色之间做带缓动的过渡，统一所有控件的动效节奏。

    用法：维护若干 (起始色 -> 目标色) 通道，每帧把插值后的颜色交给 apply 回调。
    重新设定目标时从当前值续接，保证打断（hover->leave->hover）也顺滑。
    """

    def __init__(self, widget, apply_callback, *, duration_ms=160, steps=10):
        self._widget = widget
        self._apply = apply_callback
        self._duration_ms = max(1, int(duration_ms))
        self._steps = max(1, int(steps))
        self._interval = max(8, self._duration_ms // self._steps)
        self._job = None
        self._current = {}
        self._targets = {}

    def set_immediate(self, colors):
        self._cancel()
        self._current = dict(colors)
        self._targets = dict(colors)
        self._apply(self._current)

    def animate_to(self, colors, *, duration_ms=None):
        if not self._current:
            self.set_immediate(colors)
            return
        self._targets = dict(colors)
        if duration_ms is not None:
            self._duration_ms = max(1, int(duration_ms))
            self._interval = max(8, self._duration_ms // self._steps)
        self._cancel()
        self._start = {key: self._current.get(key, value) for key, value in self._targets.items()}
        self._tick(1)

    def _tick(self, step):
        progress = _ease_out_cubic(step / self._steps)
        frame = {}
        for key, target in self._targets.items():
            start = self._start.get(key, target)
            try:
                frame[key] = _blend_colors(start, target, progress)
            except Exception:
                frame[key] = target
        self._current.update(frame)
        try:
            self._apply(self._current)
        except Exception:
            self._job = None
            return
        if step < self._steps:
            self._job = self._widget.after(self._interval, lambda: self._tick(step + 1))
        else:
            self._current.update(self._targets)
            self._job = None

    def _cancel(self):
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    cancel = _cancel


@lru_cache(maxsize=32)
def _load_photo_image(asset_path, size=None):
    image = Image.open(resource_path(asset_path))
    if size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(image)


def create_card(parent, theme, bg='panel', border='border', border_width=1, **kwargs):
    return tk.Frame(
        parent,
        bg=_resolve_color(theme, bg),
        highlightbackground=_resolve_color(theme, border),
        highlightthickness=border_width,
        **kwargs,
    )


def bind_hover_style(
    widget,
    *,
    theme,
    normal_bg,
    hover_bg,
    normal_fg=None,
    hover_fg=None,
    extra_widgets=None,
):
    extra_widgets = list(extra_widgets or [])
    normal_bg = _resolve_color(theme, normal_bg)
    hover_bg = _resolve_color(theme, hover_bg)
    normal_fg = _resolve_color(theme, normal_fg) if normal_fg else None
    hover_fg = _resolve_color(theme, hover_fg) if hover_fg else None

    targets = [widget, *extra_widgets]

    def _apply(bg, fg):
        for target in targets:
            config = {'bg': bg}
            if fg is not None:
                config['fg'] = fg
            try:
                target.config(**config)
            except Exception:
                pass

    widget.bind('<Enter>', lambda _event: _apply(hover_bg, hover_fg), add='+')
    widget.bind('<Leave>', lambda _event: _apply(normal_bg, normal_fg), add='+')


class AnimatedButton(tk.Frame):
    def __init__(
        self,
        parent,
        *,
        text,
        command,
        theme,
        variant='primary',
        font=None,
        style_overrides=None,
        **kwargs,
    ):
        self._theme = theme
        self._style = deepcopy(theme['buttons'][variant])
        if style_overrides:
            self._style.update(style_overrides)

        requested_state = kwargs.pop('state', tk.NORMAL)
        container_bg = kwargs.pop('container_bg', None)
        if container_bg is None:
            try:
                container_bg = parent.cget('bg')
            except Exception:
                container_bg = _resolve_color(theme, 'bg')

        super().__init__(parent, bg=container_bg, bd=0, highlightthickness=0)
        for color_key in ('bg', 'hover_bg'):
            if self._style.get(color_key) == 'transparent':
                self._style[color_key] = container_bg

        self._command = command
        self._font = font or theme['fonts']['button']
        self._state = requested_state
        self._images = {}
        self._pulse_job = None
        self._pulse_index = 0
        self._pulse_direction = 1
        self._pulse_on_color = None
        self._pulse_off_color = _resolve_color(
            theme,
            self._style.get('pulse_border_off_color', self._style.get('hover_bg', self._style['bg'])),
        )
        self._pulse_mid_color = _resolve_color(theme, self._style.get('pulse_border_mid_color'))
        self._pulse_step_ms = int(self._style.get('pulse_step_ms', 32))
        self._pulse_steps = max(2, int(self._style.get('pulse_steps', 18)))

        # 带缓动的颜色过渡：hover / press / 复位都不再是生硬的瞬切
        self._color_tween = ColorTween(self, self._apply_content_colors, duration_ms=170, steps=11)
        self._enter_ms = int(self._style.get('transition_enter_ms', 170))
        self._leave_ms = int(self._style.get('transition_leave_ms', 130))

        content_pady = self._style.get('content_pady')
        if content_pady is not None:
            kwargs['pady'] = max(int(kwargs.get('pady', 0) or 0), int(content_pady))

        self._content = tk.Label(
            self,
            bd=0,
            relief=tk.FLAT,
            text=text,
            font=self._font,
            compound=self._style['compound'],
            **kwargs,
        )
        self._content.pack(fill=tk.BOTH, expand=True)

        image_assets = {
            'normal': self._style.get('image'),
            'hover': self._style.get('hover_image'),
            'pressed': self._style.get('pressed_image'),
        }
        if any(image_assets.values()):
            size = self._style.get('image_size')
            for key, asset_path in image_assets.items():
                if asset_path:
                    self._images[key] = _load_photo_image(asset_path, size)
            fallback = self._images.get('normal')
            if fallback is not None:
                self._content.config(image=fallback)
                self._content._theme_images = self._images

        for widget in (self, self._content):
            widget.bind('<Enter>', self._on_enter, add='+')
            widget.bind('<Leave>', self._on_leave, add='+')
            widget.bind('<ButtonPress-1>', self._on_press, add='+')
            widget.bind('<ButtonRelease-1>', self._on_release, add='+')

        self.bind('<Destroy>', self._on_destroy, add='+')
        self._apply_state('normal')

    def _style_value(self, state, suffix, fallback=None):
        key = f'{state}_{suffix}' if state else suffix
        return self._style.get(key, self._style.get(suffix, fallback))

    def _visual_state_name(self, state):
        if self._state == tk.DISABLED:
            return 'disabled'
        return state

    def _swap_image(self, name):
        image = self._images.get(name) or self._images.get('normal')
        if image is not None:
            self._content.config(image=image)

    def _apply_content_colors(self, colors):
        bg = colors.get('bg')
        fg = colors.get('fg')
        border = colors.get('border')
        if border is not None:
            tk.Frame.config(self, bg=border)
        content_cfg = {}
        if bg is not None:
            content_cfg['bg'] = bg
        if fg is not None:
            content_cfg['fg'] = fg
        if content_cfg:
            self._content.config(**content_cfg)

    def _state_colors(self, state):
        bg = _resolve_color(self._theme, self._style_value(state, 'bg', self._style['bg']))
        fg = _resolve_color(
            self._theme,
            self._style_value(state, 'fg', self._theme['colors'].get('subtext', self._style['fg'])),
        )
        border = _resolve_color(
            self._theme,
            self._style_value(state, 'border_color', self._style.get('highlightbackground')),
        )
        return {'bg': bg, 'fg': fg, 'border': border}

    def _apply_visual_state(self, state, *, animate=False, duration_ms=None):
        state = self._visual_state_name(state)
        colors = self._state_colors(state)
        # 边框由 pulse 单独驱动，这里立即落定，避免与 tween 抢同一像素而闪烁
        border = colors.pop('border', None)
        thickness = int(self._style_value(state, 'highlightthickness', self._style['highlightthickness']))
        cursor = self._style['cursor'] if self._state != tk.DISABLED and self._command else 'arrow'
        tk.Frame.config(self, bg=border, cursor=cursor)
        self._content.config(cursor=cursor, font=self._font)
        self._content.pack_configure(padx=thickness, pady=thickness)
        if animate:
            self._color_tween.animate_to(colors, duration_ms=duration_ms)
        else:
            self._color_tween.set_immediate(colors)

    def _cancel_pulse(self):
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None

    def _run_pulse(self):
        if not self._pulse_on_color or not self._pulse_off_color:
            return
        try:
            progress = self._pulse_index / self._pulse_steps
            if self._pulse_mid_color:
                if progress <= 0.5:
                    color = _blend_colors(self._pulse_on_color, self._pulse_mid_color, progress * 2)
                else:
                    color = _blend_colors(self._pulse_mid_color, self._pulse_off_color, (progress - 0.5) * 2)
            else:
                color = _blend_colors(self._pulse_on_color, self._pulse_off_color, progress)
            tk.Frame.config(self, bg=color)
            if self._pulse_index >= self._pulse_steps:
                self._pulse_index = 0
            else:
                self._pulse_index += 1
            self._pulse_job = self.after(self._pulse_step_ms, self._run_pulse)
        except Exception:
            self._pulse_job = None

    def _apply_state(self, state, *, pulse=False, animate=False, duration_ms=None):
        self._cancel_pulse()
        self._apply_visual_state(state, animate=animate, duration_ms=duration_ms)
        self._swap_image(self._visual_state_name(state))
        self._pulse_on_color = _resolve_color(
            self._theme,
            self._style_value(self._visual_state_name(state), 'border_color', self._style.get('highlightbackground')),
        )
        if pulse and self._state != tk.DISABLED and self._pulse_on_color and self._pulse_off_color:
            self._pulse_index = 0
            self._pulse_direction = 1
            self._run_pulse()

    def _pointer_inside(self):
        current = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
        return current in {self, self._content}

    def _on_enter(self, _event):
        if self._state == tk.DISABLED:
            return
        self._apply_state('hover', pulse=True, animate=True, duration_ms=self._enter_ms)

    def _on_leave(self, _event):
        if self._state == tk.DISABLED:
            return
        if not self._pointer_inside():
            # 退出比进入更快（~70%），符合 MD 动效：响应更跟手
            self._apply_state('normal', animate=True, duration_ms=self._leave_ms)

    def _on_press(self, _event):
        if self._state == tk.DISABLED or not self._command:
            return
        # 按下要立刻给反馈（<100ms），不做缓动
        self._apply_state('pressed')

    def _on_release(self, _event):
        if self._state == tk.DISABLED or not self._command:
            return
        if self._pointer_inside():
            self._apply_state('hover', pulse=True, animate=True, duration_ms=self._enter_ms)
            self._command()
        else:
            self._apply_state('normal', animate=True, duration_ms=self._leave_ms)

    def _on_destroy(self, _event):
        self._cancel_pulse()
        try:
            self._color_tween.cancel()
        except Exception:
            pass

    def invoke(self):
        if self._state != tk.DISABLED and self._command:
            return self._command()
        return None

    def config(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)

        state = kwargs.pop('state', None)
        command = kwargs.pop('command', None)
        font = kwargs.pop('font', None)

        content_options = {}
        for key in (
            'text',
            'image',
            'compound',
            'width',
            'height',
            'anchor',
            'justify',
            'padx',
            'pady',
            'wraplength',
            'textvariable',
        ):
            if key in kwargs:
                content_options[key] = kwargs.pop(key)

        if command is not None:
            self._command = command
        if font is not None:
            self._font = font
        if content_options:
            self._content.config(**content_options)
        if kwargs:
            tk.Frame.config(self, **kwargs)
        if state is not None:
            self._state = state
        self._apply_state('normal')

    configure = config

    def cget(self, key):
        if key == 'state':
            return self._state
        try:
            return self._content.cget(key)
        except Exception:
            return tk.Frame.cget(self, key)


def create_button(
    parent,
    *,
    text,
    command,
    theme,
    variant='primary',
    font=None,
    style_overrides=None,
    **kwargs,
):
    return AnimatedButton(
        parent,
        text=text,
        command=command,
        theme=theme,
        variant=variant,
        font=font,
        style_overrides=style_overrides,
        **kwargs,
    )


class StyledDropdown(tk.Frame):
    def __init__(
        self,
        parent,
        *,
        theme,
        label,
        value_getter,
        options,
        on_select,
        font=None,
        width=220,
    ):
        super().__init__(parent, bg=_resolve_color(theme, 'bg'), bd=0, highlightthickness=0)
        self._theme = theme
        self._label = label
        self._value_getter = value_getter
        self._dropdown_options = list(options)
        self._on_select = on_select
        self._font = font or theme['fonts']['control']
        self._width = width
        self._menu = None
        self._outside_bind_id = None

        self._button = AnimatedButton(
            self,
            text='',
            command=self.toggle,
            theme=theme,
            variant='secondary',
            font=self._font,
            width=max(18, int(width / 12)),
            style_overrides={
                'bg': 'transparent',
                'fg': 'text',
                'hover_bg': 'transparent',
                'hover_fg': 'gold',
                'pressed_bg': 'gold_soft',
                'pressed_fg': 'gold',
                'highlightbackground': 'accent',
                'highlightthickness': 1,
                'normal_side_border_only': False,
                'hover_border_color': 'gold_bright',
                'hover_highlightthickness': 1,
                'pressed_border_color': 'gold_deep',
                'pulse_border_off_color': 'panel',
            },
            anchor='w',
            justify='left',
            padx=12,
            pady=8,
        )
        self._button.pack(fill=tk.X)
        self.refresh()

    def refresh(self):
        current = self._value_getter()
        caret = '⌃' if (self._menu is not None and self._menu.winfo_exists()) else '⌄'
        self._button.config(text=f'{self._label}: {current}   {caret}')

    def toggle(self):
        if self._menu is not None and self._menu.winfo_exists():
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        self.close_menu()
        overlay_host = self.winfo_toplevel()
        panel = _resolve_color(self._theme, 'panel')
        gold = _resolve_color(self._theme, 'gold')
        gold_soft = _resolve_color(self._theme, 'gold_soft')
        text_color = _resolve_color(self._theme, 'text')
        text_strong = _resolve_color(self._theme, 'text_strong')
        menu = tk.Frame(
            overlay_host,
            bg=panel,
            highlightbackground=gold,
            highlightthickness=1,
            bd=0,
        )
        self._menu = menu
        card = menu
        current_display = self._value_getter()

        for key, display in self._dropdown_options:
            is_active = display == current_display
            row = tk.Frame(card, bg=panel, cursor='hand2')
            row.pack(fill=tk.X)
            indicator = tk.Frame(row, width=3, bg=gold if is_active else panel)
            indicator.pack(side=tk.LEFT, fill=tk.Y)
            label = tk.Label(
                row,
                text=display,
                font=self._font,
                bg=gold_soft if is_active else panel,
                fg=text_strong if is_active else text_color,
                anchor='w',
                justify='left',
                padx=12,
                pady=10,
                cursor='hand2',
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            tween = ColorTween(
                row,
                lambda colors, _row=row, _ind=indicator, _lbl=label: (
                    _row.config(bg=colors['row']),
                    _ind.config(bg=colors['ind']),
                    _lbl.config(bg=colors['row'], fg=colors['fg']),
                ),
                duration_ms=150,
                steps=9,
            )
            rest = {
                'row': gold_soft if is_active else panel,
                'ind': gold if is_active else panel,
                'fg': text_strong if is_active else text_color,
            }
            hot = {'row': panel, 'ind': gold, 'fg': gold}
            tween.set_immediate(rest)

            def _choose(_event, selected=key):
                self.close_menu()
                self._on_select(selected)
                self.refresh()

            def _hover_on(_event, _tween=tween, _hot=hot):
                _tween.animate_to(_hot, duration_ms=150)

            def _hover_off(_event, _tween=tween, _rest=rest):
                _tween.animate_to(_rest, duration_ms=120)

            for target in (row, indicator, label):
                target.bind('<Button-1>', _choose, add='+')
                target.bind('<Enter>', _hover_on, add='+')
                target.bind('<Leave>', _hover_off, add='+')

        menu.update_idletasks()
        try:
            rel_x = self.winfo_rootx() - overlay_host.winfo_rootx()
            rel_y = self.winfo_rooty() - overlay_host.winfo_rooty() + self.winfo_height() + 6
        except Exception:
            rel_x = 0
            rel_y = self.winfo_height() + 6
        height = card.winfo_reqheight()
        menu.place(x=rel_x, y=rel_y, width=self._width, height=height)
        try:
            menu.lift()
        except Exception:
            pass
        self._animate_menu_in(menu, rel_x, rel_y)
        self.refresh()
        try:
            root = self.winfo_toplevel()
            self._outside_bind_id = root.bind('<Button-1>', self._handle_root_click, add='+')
        except Exception:
            self._outside_bind_id = None

    def _animate_menu_in(self, menu, target_x, target_y, *, steps=7, interval_ms=14, offset=10):
        """菜单从触发按钮下方轻轻滑出，符合 modal-motion 的空间连续性。"""
        def _tick(step):
            if not menu.winfo_exists():
                return
            progress = _ease_out_cubic(step / steps)
            current_y = int((target_y - offset) + offset * progress)
            try:
                menu.place_configure(x=target_x, y=current_y)
            except Exception:
                return
            if step < steps:
                menu.after(interval_ms, lambda: _tick(step + 1))

        _tick(0)

    def close_menu(self):
        try:
            root = self.winfo_toplevel()
            if self._outside_bind_id is not None:
                root.unbind('<Button-1>', self._outside_bind_id)
        except Exception:
            pass
        self._outside_bind_id = None
        if self._menu is not None:
            try:
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None
            try:
                self.refresh()
            except Exception:
                pass

    def _handle_root_click(self, event):
        if self._menu is None:
            return
        widget = event.widget
        while widget is not None:
            if widget in {self, self._button, self._menu}:
                return
            widget = getattr(widget, 'master', None)
        self.close_menu()


def create_dropdown(
    parent,
    *,
    theme,
    label,
    value_getter,
    options,
    on_select,
    font=None,
    width=220,
):
    return StyledDropdown(
        parent,
        theme=theme,
        label=label,
        value_getter=value_getter,
        options=options,
        on_select=on_select,
        font=font,
        width=width,
    )
