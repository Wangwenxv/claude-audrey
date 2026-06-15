import os
import sys
import time
import tkinter as tk

os.chdir(r'D:/aiops_wwx/claude-audrey/audrey-hall')
sys.path.insert(0, os.getcwd())

from audrey_hall.chat_window import ChatWindow


class DummyApp:
    def __init__(self, root):
        self.root = root
        self.chat_window = None
        self.pets = []
        self.claude_hook_state = None


def main():
    root = tk.Tk()
    root.withdraw()
    app = DummyApp(root)
    chat = ChatWindow(root, app, 'verify')
    app.chat_window = chat
    chat.show()
    root.after(500, chat._show_terminal_view)
    root.after(3000, chat.close)
    root.after(3200, root.destroy)
    root.mainloop()


if __name__ == '__main__':
    main()
