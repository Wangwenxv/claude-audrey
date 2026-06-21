import pystray
from pystray import MenuItem  # 显式导入，解决打包后MenuItem不可用问题
from PIL import Image

from .config import load_config
from .settings import show_settings_dialog
from .utils import resource_path


def create_tray(app, version):
    """创建系统托盘图标和菜单，返回 pystray.Icon 实例"""

    try:
        icon_gif = Image.open(resource_path('gifs/idle2.gif'))
        icon_gif.seek(0)
        icon_image = icon_gif.convert('RGBA')
        icon_image = icon_image.resize((64, 64), Image.Resampling.BOX)
    except Exception:
        icon_image = Image.new('RGB', (64, 64), color='pink')

    # ============ 回调函数 ============

    def on_toggle_visible(icon, item):
        """切换隐藏/显示"""
        if app.is_visible():
            app.hide_all()
        else:
            app.show_all()
        icon.menu = _create_menu(app)

    def on_toggle_click_through(icon, item):
        """切换鼠标穿透"""
        app.set_click_through(not app.click_through)
        config = load_config()
        config["click_through"] = app.click_through
        # Import here to avoid circular imports
        from .config import save_config

        save_config(config)
        icon.menu = _create_menu(app)

    def on_settings(icon, item):
        """打开设置窗口"""
        show_settings_dialog(app.root, app, version)

    def on_tk_chat(icon, item):
        """打开 Tk AI 对话窗口"""
        if hasattr(app, "show_tk_chat_window"):
            app.root.after(0, lambda: app.show_tk_chat_window(app.root, version))
            return
        app.root.after(0, lambda: app.show_chat_window(app.root, version))

    def on_wpf_chat(icon, item):
        """打开 WPF AI 对话窗口"""
        if hasattr(app, "show_wpf_chat_window"):
            app.root.after(0, lambda: app.show_wpf_chat_window(app.root, version))
            return
        app.root.after(0, lambda: app.show_chat_window(app.root, version))

    def on_quit(icon):
        """退出（只发信号，主线程统一收尾）"""
        if hasattr(app, "request_quit"):
            app.request_quit()
        else:
            app._request_quit = True

    # ============ 菜单构建 ============

    def _create_menu(app_instance):
        """动态创建菜单"""
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: "隐藏" if app_instance.is_visible() else "显示",
                on_toggle_visible,
            ),
            pystray.MenuItem(
                "鼠标穿透",
                on_toggle_click_through,
                checked=lambda it: app_instance.click_through,
            ),
            pystray.MenuItem(
                "与奥黛丽聊聊",
                pystray.Menu(
                    pystray.MenuItem("Tk 经典窗口", on_tk_chat),
                    pystray.MenuItem("WPF 原生窗口", on_wpf_chat),
                ),
            ),
            pystray.MenuItem("设置", on_settings),
            pystray.MenuItem("退出", on_quit),
        )

    # 创建菜单
    menu = _create_menu(app)

    icon = pystray.Icon("audrey-hall", icon_image, "Audrey Hall", menu)
    return icon
