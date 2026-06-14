"""样式覆盖入口。

以后主要改这里，不需要去改聊天窗口、快捷菜单、设置页的功能代码。

常见可改项：
- colors: 全局颜色
- windows: 各窗口尺寸、间距
- menu: 快捷菜单标题/间距
- chat: 聊天区内边距、权限卡片宽度
- buttons: 按钮样式与图片

按钮图片路径相对项目根目录，例如：
buttons.primary.image = 'gifs/ui/send-normal.png'
buttons.primary.hover_image = 'gifs/ui/send-hover.png'
buttons.primary.pressed_image = 'gifs/ui/send-pressed.png'
buttons.primary.image_size = (120, 40)
"""


THEME_OVERRIDES = {
    # 'colors': {
    #     'bg': '#10131A',
    #     'panel': '#1A2030',
    #     'accent': '#7C5CFF',
    #     'text': '#F5F7FF',
    # },
    # 'windows': {
    #     'chat': {
    #         'base_width': 520,
    #         'base_height': 500,
    #     },
    # }
    # 'buttons': {
    #     'primary': {
    #         'image': 'gifs/ui/send-normal.png',
    #         'hover_image': 'gifs/ui/send-hover.png',
    #         'pressed_image': 'gifs/ui/send-pressed.png',
    #         'image_size': (120, 40),
    #         'bg': 'accent',
    #     },
    # },
}
