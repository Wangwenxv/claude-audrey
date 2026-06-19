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
    'colors': {
        'bg': '#DDEDEA',
        'panel': '#F8FFFB',
        'card_bg': '#FCFFFB',
        'card_alt': '#EEF8F1',
        'input_bg': '#F4FBF2',
        'input_border': '#D9C281',
        'border': '#B8D6CF',
        'border_strong': '#8EBBB2',
        'accent': '#8CCFB2',
        'accent_dark': '#4F827B',
        'accent_soft': '#D7EFE5',
        'gold': '#D1AE61',
        'gold_bright': '#F0D88D',
        'gold_deep': '#8D6835',
        'gold_soft': '#F6EBCB',
        'pink_soft': '#F6DDE5',
        'text': '#314C4D',
        'text_strong': '#22383A',
        'muted': '#638083',
        'subtext': '#84989B',
        'hover': '#EAF7F2',
        'separator': '#D2E6DF',
        'tab_bg': '#E4F1ED',
        'tab_active': '#FFF5DB',
        'user': '#F6E5EA',
        'assistant': '#EFF9F0',
        'warn': '#FFF1D0',
        'error': '#F7E2E1',
        'success': '#E2F4DE',
        'info': '#E6F5F3',
    },
    'windows': {
        'chat': {
            'base_width': 900,
            'base_height': 740,
            'min_width': 680,
            'min_height': 520,
            'outer_pad': 18,
            'header_gap': 12,
            'composer_gap': 14,
        },
    },
    'chat': {
        'transcript_pad_x': 18,
        'transcript_pad_y': 16,
        'input_pad_x': 16,
        'input_pad_y': 12,
        'permission_wraplength': 560,
    },
    'buttons': {
        'secondary': {
            'bg': 'panel',
            'fg': 'text',
            'highlightbackground': 'gold',
            'hover_bg': 'gold_soft',
            'hover_fg': 'text_strong',
            'hover_border_color': 'gold_bright',
            'pressed_bg': 'accent_soft',
            'pressed_border_color': 'gold_deep',
            'pulse_border_off_color': 'panel',
        },
    },
}
