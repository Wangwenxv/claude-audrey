"""关于标签页"""

import tkinter as tk
from tkinter import ttk
import webbrowser

from PIL import Image, ImageTk

from ..constants import GITEE_RELEASES_URL
from ..utils import resource_path


def create_about_tab(settings_window, parent):
    """创建关于标签页

    Args:
        settings_window: SettingsWindow 实例
        parent: 父容器

    Returns:
        创建的标签页 frame
    """
    frame = ttk.Frame(parent, padding=20)

    # 顶部留白
    tk.Frame(frame, height=15, bg=settings_window.colors["bg"]).pack()

    try:
        gif_image = gif_image.resize((100, 100), Image.Resampling.LANCZOS)
        gif_photo = ImageTk.PhotoImage(gif_image)
        gif_label = tk.Label(
            frame, image=gif_photo, border=0, bg=settings_window.colors["bg"]
        )
        gif_label.image = gif_photo  # type: ignore[attr-defined]
        gif_label.pack(pady=(0, 15))
    except Exception as e:
        print(f"加载关于窗口GIF失败: {e}")

    # 标题
    tk.Label(
        frame,
        text="Audrey Hall",
        font=(settings_window.font_family, 20, "bold"),
        fg=settings_window.colors["accent_dark"],
        bg=settings_window.colors["bg"],
    ).pack(pady=(0, 10))

    # 版本号
    tk.Label(
        frame,
        text=f"版本 {settings_window.version}",
        font=settings_window.fonts["base"],
        fg=settings_window.colors["subtext"],
        bg=settings_window.colors["bg"],
    ).pack(pady=(0, 5))


    # 分隔线
    separator = ttk.Separator(frame, orient="horizontal")
    separator.pack(fill=tk.X, pady=10)

    # 描述文本
    desc_frame = tk.Frame(frame, bg=settings_window.colors["bg"])
    desc_frame.pack(pady=15)

    desc_lines = [
        '"奥黛丽，Audrey Hall 的数字化身。',
        "现在的我，会在你的桌面上静静陪伴。",
        '很高兴见到你。"',
    ]



    return frame
