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
            self.wpf_chat_bridge = None
            self.wpf_chat_process = None
            self.chat_picker = None
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
            if self.wpf_chat_bridge is not None:
                try:
                    self.wpf_chat_bridge.close()
                except Exception:
                    pass
                self.wpf_chat_bridge = None
                self.wpf_chat_process = None
            for pet in self.pets:
                pet._request_quit = True

        def show_chat_window(self, parent, version):
            if threading.current_thread() is not threading.main_thread():
                self.root.after(0, lambda: self.show_chat_window(parent, version))
                return

            self._close_chat_picker()
            self._show_tk_chat_window(parent, version)

        def show_tk_chat_window(self, parent, version):
            if threading.current_thread() is not threading.main_thread():
                self.root.after(0, lambda: self.show_tk_chat_window(parent, version))
                return
            self._close_chat_picker()
            self._show_tk_chat_window(parent, version)

        def show_wpf_chat_window(self, parent, version):
            if threading.current_thread() is not threading.main_thread():
                self.root.after(0, lambda: self.show_wpf_chat_window(parent, version))
                return
            self._close_chat_picker()
            if not self._show_wpf_chat_window(version):
                self._show_tk_chat_window(parent, version)

        def _show_chat_picker(self, parent, version):
            if self.chat_picker is not None:
                try:
                    if self.chat_picker.winfo_exists():
                        self.chat_picker.lift()
                        self.chat_picker.focus_force()
                        return
                except Exception:
                    pass
                self.chat_picker = None

            picker = tk.Toplevel(parent)
            self.chat_picker = picker
            picker.title('选择聊天窗口')
            picker.resizable(False, False)
            picker.transient(parent)
            picker.configure(bg='#F8F6F0')
            picker.protocol('WM_DELETE_WINDOW', lambda: self._close_chat_picker())

            frame = tk.Frame(picker, bg='#F8F6F0', padx=18, pady=18)
            frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(
                frame,
                text='与奥黛丽聊聊',
                font=('Microsoft YaHei UI', 15, 'bold'),
                bg='#F8F6F0',
                fg='#24383C',
            ).pack(anchor='w')
            tk.Label(
                frame,
                text='请选择这次使用的聊天窗口：',
                font=('Microsoft YaHei UI', 10),
                bg='#F8F6F0',
                fg='#667C80',
            ).pack(anchor='w', pady=(8, 16))

            button_row = tk.Frame(frame, bg='#F8F6F0')
            button_row.pack(fill=tk.X)

            tk.Button(
                button_row,
                text='经典 Tk',
                width=14,
                command=lambda: self._choose_chat_variant('tk', parent, version),
                bg='#FFFDF8',
                fg='#24383C',
                relief=tk.FLAT,
                highlightbackground='#D6B36A',
                highlightthickness=1,
                padx=8,
                pady=10,
                cursor='hand2',
            ).pack(side=tk.LEFT)

            tk.Button(
                button_row,
                text='原生 WPF(EXE)',
                width=16,
                command=lambda: self._choose_chat_variant('wpf', parent, version),
                bg='#EEF6F3',
                fg='#24383C',
                relief=tk.FLAT,
                highlightbackground='#A8CEC7',
                highlightthickness=1,
                padx=8,
                pady=10,
                cursor='hand2',
            ).pack(side=tk.LEFT, padx=(10, 0))

            tk.Label(
                frame,
                text='Tk 更稳定；WPF 版仍在优化性能与展示流。',
                font=('Microsoft YaHei UI', 9),
                bg='#F8F6F0',
                fg='#8A9C9E',
            ).pack(anchor='w', pady=(14, 0))

            picker.update_idletasks()
            try:
                parent_x = parent.winfo_rootx()
                parent_y = parent.winfo_rooty()
                parent_w = max(parent.winfo_width(), parent.winfo_reqwidth())
                parent_h = max(parent.winfo_height(), parent.winfo_reqheight())
                picker_w = picker.winfo_width()
                picker_h = picker.winfo_height()
                x = parent_x + max(0, (parent_w - picker_w) // 2)
                y = parent_y + max(0, (parent_h - picker_h) // 2)
                picker.geometry(f'+{x}+{y}')
            except Exception:
                pass
            picker.lift()
            picker.focus_force()
            picker.grab_set()

        def _close_chat_picker(self):
            if self.chat_picker is None:
                return
            try:
                self.chat_picker.grab_release()
            except Exception:
                pass
            try:
                self.chat_picker.destroy()
            except Exception:
                pass
            self.chat_picker = None

        def _choose_chat_variant(self, variant, parent, version):
            self._close_chat_picker()
            if variant == 'wpf':
                if self._show_wpf_chat_window(version):
                    return
            self._show_tk_chat_window(parent, version)

        def _show_tk_chat_window(self, parent, version):
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

        def _show_wpf_chat_window(self, version):
            try:
                self._ensure_wpf_chat_bridge(version)
                return self.wpf_chat_bridge.show()
            except Exception:
                return False

        def _ensure_wpf_chat_bridge(self, version):
            from audrey_hall.chat_bridge import WpfChatBridge
            from audrey_hall.chat_process import ChatProcessManager

            if self.wpf_chat_process is None:
                self.wpf_chat_process = ChatProcessManager(
                    self.root,
                    lambda command: self.wpf_chat_bridge.handle_command(command)
                    if self.wpf_chat_bridge is not None
                    else None,
                )
            if self.wpf_chat_bridge is None:
                self.wpf_chat_bridge = WpfChatBridge(self, version, self.wpf_chat_process)

        def preheat_chat_window(self, version):
            try:
                self._ensure_wpf_chat_bridge(version)
                self.wpf_chat_process.preheat()
            except Exception:
                pass

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
