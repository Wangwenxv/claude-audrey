import ctypes
import sys
import threading
import tkinter as tk
import webbrowser

from audrey_hall.hook_server import ClaudeHookServer
from audrey_hall.hook_state import ClaudeHookState

# 启用 Windows DPI 感知（解决高DPI屏幕模糊问题）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    from audrey_hall.config import load_config
    from audrey_hall.pet import DesktopGif
    from audrey_hall.utils import check_new_version, get_version, version_greater_than
    from audrey_hall.settings import SettingsWindow

    VERSION = get_version()

    root = tk.Tk()
    # 立即隐藏窗口，避免闪烁
    root.withdraw()

    # 创建根窗口后立即加载自定义字体
    from audrey_hall.fonts import _load_zpix_font

    _load_zpix_font()

    class PetManager:
        def __init__(self, master, count):
            self.root = master
            self.pets = []
            self.chat_window = None
            self.claude_hook_state = ClaudeHookState()
            self.claude_hook_server = ClaudeHookServer(self.claude_hook_state)
            self._visible = True
            self._request_quit = False
            self.is_paused = False
            # 从配置文件读取所有设置
            config = load_config()
            self.follow_mouse = False
            self.click_through = config.get("click_through", False)
            self.display_priority = config.get("display_priority", 1)
            self.voice_enabled = config.get("voice_enabled", True)
            self.voice_volume = config.get("voice_volume", 100)
            self.claude_hook_state.add_listener(self._on_claude_state_change)
            self._create_instances(count)
            self.claude_hook_server.start()
            self.root.after(500, self._show_startup_greeting)

        def _create_instances(self, count):
            for _ in range(count):
                pet_root = self.root if not self.pets else tk.Toplevel(self.root)
                pet = DesktopGif(pet_root)
                self.pets.append(pet)
                self._apply_state_to_pet(pet)
            self._sync_state_from_primary()

        def _sync_state_from_primary(self):
            if not self.pets:
                return
            primary = self.pets[0]
            self.is_paused = primary.is_paused
            self.follow_mouse = False
            self.click_through = primary.click_through
            self.display_priority = primary.display_priority

        def _on_claude_state_change(self, state):
            self.root.after(0, lambda: self._apply_claude_state(state))

        def _apply_claude_state(self, state):
            bubble = (state or {}).get('bubble') or ''
            status = (state or {}).get('status') or 'idle'
            for pet in self.pets:
                if bubble:
                    pet.set_claude_bubble(bubble, status=status)
                else:
                    pet.hide_claude_bubble()

        def _show_startup_greeting(self):
            if not self.pets:
                return
            primary = self.pets[0]
            try:
                primary.root.update_idletasks()
                if primary.root.winfo_ismapped() != 1:
                    self.root.after(300, self._show_startup_greeting)
                    return
            except Exception:
                self.root.after(300, self._show_startup_greeting)
                return
            for pet in self.pets:
                try:
                    pet.show_startup_greeting()
                except Exception:
                    pass

        def set_instance_count(self, count):
            count = max(1, int(count))
            current = len(self.pets)
            if count > current:
                for _ in range(count - current):
                    pet_root = tk.Toplevel(self.root)
                    pet = DesktopGif(pet_root)
                    self._apply_state_to_pet(pet)
                    self.pets.append(pet)
            elif count < current:
                for pet in self.pets[count:]:
                    try:
                        pet._request_quit = True
                    except Exception:
                        pass
                    try:
                        pet.root.destroy()
                    except Exception:
                        pass
                self.pets = self.pets[:count]
            self._sync_state_from_primary()

        def _apply_state_to_pet(self, pet):
            pet.follow_mouse = False
            pet.click_through = self.click_through
            pet.set_click_through(self.click_through)
            if self.is_paused and not pet.is_paused:
                pet.toggle_pause()
            pet.set_display_priority(self.display_priority, persist=False)
            if not self._visible:
                pet.root.withdraw()
            pet._sync_bubble_visibility()
            # 应用语音设置
            if pet.voice_player:
                pet.voice_player.set_enabled(self.voice_enabled)
                pet.voice_player.set_volume(self.voice_volume)
            # 设置管理器引用
            pet.manager = self

        def set_click_through(self, enable):
            self.click_through = enable
            for pet in self.pets:
                pet.click_through = enable
                pet.set_click_through(enable)

        def set_follow_mouse(self, enable):
            self.follow_mouse = False
            for pet in self.pets:
                pet.follow_mouse = False

        def toggle_pause(self):
            for pet in self.pets:
                pet.toggle_pause()
            self._sync_state_from_primary()

        def set_scale(self, index):
            for pet in self.pets:
                pet.set_scale(index)

        def set_transparency(self, index):
            for pet in self.pets:
                pet.set_transparency(index)

        def set_display_priority(self, mode, persist=True):
            self.display_priority = mode
            for pet in self.pets:
                pet.set_display_priority(mode, persist=persist)

        def set_wander_idle_stay_mode(self, mode):
            return

        def set_voice_enabled(self, enabled):
            """设置所有宠物的语音开关"""
            self.voice_enabled = enabled
            for pet in self.pets:
                if pet.voice_player:
                    pet.voice_player.set_enabled(enabled)

        def set_voice_volume(self, volume):
            """设置所有宠物的语音音量"""
            self.voice_volume = volume
            for pet in self.pets:
                if pet.voice_player:
                    pet.voice_player.set_volume(volume)

        def hide_all(self):
            self._visible = False
            for pet in self.pets:
                pet._user_hidden = True  # 标记为用户手动隐藏
                pet.root.withdraw()
                pet._sync_bubble_visibility()

        def show_all(self):
            self._visible = True
            for pet in self.pets:
                pet._user_hidden = False  # 清除用户手动隐藏标记
                pet.root.deiconify()
                pet._sync_bubble_visibility()

        def is_visible(self):
            return self._visible

        def request_quit(self):
            try:
                self.claude_hook_server.stop()
            except Exception:
                pass
            if self.chat_window is not None:
                try:
                    self.chat_window.close()
                except Exception:
                    pass
                self.chat_window = None
            for pet in self.pets:
                pet._request_quit = True

        def show_chat_window(self, parent, version):
            from audrey_hall.chat_window import ChatWindow

            if self.chat_window is not None and self.chat_window.window is not None:
                try:
                    if self.chat_window.window.winfo_exists():
                        self.chat_window.show()
                        return
                except Exception:
                    pass

            self.chat_window = ChatWindow(parent, self, version)
            self.chat_window.show()

    # 先创建 app 实例（在后台线程之前）
    try:
        from audrey_hall.tray import create_tray

        config = load_config()
        instance_count = config.get("instance_count", 1)
        app = PetManager(root, instance_count)

        icon = create_tray(app, VERSION)
        if app.pets:
            app.pets[0].app = icon

        def check_version_and_notify(root):
            """检查版本并通知（后台线程调用）"""
            latest = check_new_version()
            if latest and version_greater_than(latest, VERSION):
                config = load_config()
                if config.get("skip_updates"):
                    return
                if config.get("skip_version") == latest:
                    return
                # 在主线程打开设置窗口并切换到更新标签页
                root.after(
                    0, lambda: SettingsWindow(root, app, VERSION).show_with_update_tab()
                )

        # 后台检查版本（非阻塞）
        threading.Thread(
            target=check_version_and_notify, args=(root,), daemon=True
        ).start()

        # 延迟启动托盘，让窗口完全初始化后再显示
        root.update_idletasks()
        root.deiconify()  # 显示窗口（避免边框闪烁）
        root.after(500, lambda: icon.run_detached())

        root.mainloop()

    except ImportError:
        # 没有pystray时正常运行窗口
        print("未安装pystray，将只显示窗口。可运行: pip install pystray")

        # 创建 app（没有托盘时）
        config = load_config()
        instance_count = config.get("instance_count", 1)
        app = PetManager(root, instance_count)

        def check_version_and_notify(root):
            """检查版本并通知（后台线程调用）"""
            latest = check_new_version()
            if latest and version_greater_than(latest, VERSION):
                config = load_config()
                if config.get("skip_updates"):
                    return
                if config.get("skip_version") == latest:
                    return
                # 在主线程打开设置窗口并切换到更新标签页
                root.after(
                    0, lambda: SettingsWindow(root, app, VERSION).show_with_update_tab()
                )

        # 后台检查版本（非阻塞）
        threading.Thread(
            target=check_version_and_notify, args=(root,), daemon=True
        ).start()

        root.deiconify()  # 显示窗口
        root.mainloop()

        # 结束


if __name__ == "__main__":
    main()
