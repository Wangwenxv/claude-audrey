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
        self._pulse_step_ms = int(self._style.get('pulse_step_ms', 32))
        self._pulse_steps = max(2, int(self._style.get('pulse_steps', 18)))

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

    def _apply_visual_state(self, state):
        state = self._visual_state_name(state)
        bg = _resolve_color(self._theme, self._style_value(state, 'bg', self._style['bg']))
        fg = _resolve_color(
            self._theme,
            self._style_value(state, 'fg', self._theme['colors'].get('subtext', self._style['fg'])),
        )
        border = _resolve_color(
            self._theme,
            self._style_value(state, 'border_color', self._style.get('highlightbackground')),
        )
        thickness = int(self._style_value(state, 'highlightthickness', self._style['highlightthickness']))
        cursor = self._style['cursor'] if self._state != tk.DISABLED and self._command else 'arrow'
        tk.Frame.config(self, bg=border, cursor=cursor)
        self._content.config(bg=bg, fg=fg, cursor=cursor, font=self._font)
        self._content.pack_configure(padx=thickness, pady=thickness)

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
            color = _blend_colors(self._pulse_on_color, self._pulse_off_color, progress)
            tk.Frame.config(self, bg=color)
            if self._pulse_index >= self._pulse_steps:
                self._pulse_direction = -1
            elif self._pulse_index <= 0:
                self._pulse_direction = 1
            self._pulse_index += self._pulse_direction
            self._pulse_job = self.after(self._pulse_step_ms, self._run_pulse)
        except Exception:
            self._pulse_job = None

    def _apply_state(self, state, *, pulse=False):
        self._cancel_pulse()
        self._apply_visual_state(state)
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
        self._apply_state('hover')

    def _on_leave(self, _event):
        if self._state == tk.DISABLED:
            return
        if not self._pointer_inside():
            self._apply_state('normal')

    def _on_press(self, _event):
        if self._state == tk.DISABLED or not self._command:
            return
        self._apply_state('pressed')

    def _on_release(self, _event):
        if self._state == tk.DISABLED or not self._command:
            return
        if self._pointer_inside():
            self._apply_state('hover')
            self._command()
        else:
            self._apply_state('normal')

    def _on_destroy(self, _event):
        self._cancel_pulse()

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
                'bg': 'panel_elevated',
                'fg': 'text',
                'hover_bg': 'panel_tinted',
                'hover_fg': 'text',
                'pressed_bg': 'hover',
                'pressed_fg': 'text',
                'highlightbackground': 'line_strong',
                'highlightthickness': 1,
                'hover_border_color': 'line_gold',
                'pressed_border_color': 'line_strong',
                'pulse_border_off_color': 'panel_elevated',
            },
            anchor='w',
            justify='left',
            padx=12,
            pady=9,
        )
        self._button.pack(fill=tk.X)
        self.refresh()

    def refresh(self):
        current = self._value_getter()
        self._button.config(text=f'{self._label}  {current}  v')

    def toggle(self):
        if self._menu is not None and self._menu.winfo_exists():
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        self.close_menu()
        overlay_host = self.winfo_toplevel()
        menu = tk.Frame(
            overlay_host,
            bg=_resolve_color(self._theme, 'panel_elevated'),
            highlightbackground=_resolve_color(self._theme, 'line_strong'),
            highlightthickness=1,
            bd=0,
        )
        self._menu = menu
        card = menu

        for key, display in self._dropdown_options:
            row = tk.Label(
                card,
                text=display,
                font=self._font,
                bg=_resolve_color(self._theme, 'panel_elevated'),
                fg=_resolve_color(self._theme, 'text'),
                anchor='w',
                justify='left',
                padx=14,
                pady=10,
                cursor='hand2',
            )
            row.pack(fill=tk.X)

            def _choose(_event, selected=key):
                self.close_menu()
                self._on_select(selected)
                self.refresh()

            def _hover_on(_event, widget=row):
                widget.config(bg=_resolve_color(self._theme, 'panel_tinted'))

            def _hover_off(_event, widget=row):
                widget.config(bg=_resolve_color(self._theme, 'panel_elevated'))

            row.bind('<Button-1>', _choose, add='+')
            row.bind('<Enter>', _hover_on, add='+')
            row.bind('<Leave>', _hover_off, add='+')

        menu.update_idletasks()
        try:
            rel_x = self.winfo_rootx() - overlay_host.winfo_rootx()
            rel_y = self.winfo_rooty() - overlay_host.winfo_rooty() + self.winfo_height() + 6
        except Exception:
            rel_x = 0
            rel_y = self.winfo_height() + 6
        menu.place(x=rel_x, y=rel_y, width=self._width, height=card.winfo_reqheight())
        try:
            menu.lift()
        except Exception:
            pass
        try:
            root = self.winfo_toplevel()
            self._outside_bind_id = root.bind('<Button-1>', self._handle_root_click, add='+')
        except Exception:
            self._outside_bind_id = None

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
