from copy import deepcopy

from ..fonts import get_font_config
from .theme_overrides import THEME_OVERRIDES


_BASE_THEME = {
    'colors': {
        'bg': '#F2F7F6',
        'panel': '#FFFDF8',
        'card_bg': '#FFFDF8',
        'card_alt': '#F6FBFA',
        'input_bg': '#FFFCF7',
        'input_border': '#C7DDD8',
        'border': '#C7DDD8',
        'border_strong': '#9CBFB8',
        'accent': '#7FB5AD',
        'accent_dark': '#5F8E8B',
        'accent_soft': '#D6ECE7',
        'gold': '#D6B36A',
        'gold_bright': '#E8C987',
        'gold_deep': '#A57B39',
        'gold_soft': '#F3E3BF',
        'pink_soft': '#F6E4E8',
        'text': '#334B4E',
        'text_strong': '#223639',
        'muted': '#5F7375',
        'subtext': '#7A8E90',
        'hover': '#E8F4F1',
        'separator': '#D7E7E2',
        'tab_bg': '#E7F1EE',
        'tab_active': '#FFF4E7',
        'user': '#EAF5F2',
        'assistant': '#FBF1F3',
        'warn': '#FBF1DD',
        'error': '#F7E2E1',
        'success': '#E4F2E6',
        'info': '#E7F3F5',
        'white': '#FFFFFF',
    },
    'spacing': {
        'window_pad': 18,
        'section_gap': 14,
        'button_gap': 10,
        'card_pad_x': 12,
        'card_pad_y': 10,
    },
    'windows': {
        'chat': {
            'base_width': 820,
            'base_height': 720,
            'min_width': 620,
            'min_height': 480,
            'outer_pad': 22,
            'header_gap': 16,
            'composer_gap': 14,
            'button_gap': 12,
            'input_height': 5,
        },
        'settings': {
            'base_width': 1000,
            'base_height': 1000,
            'min_width': 600,
            'min_height': 600,
            'outer_pad_x': 24,
            'outer_pad_y': 20,
        },
        'menu': {
            'title_height': 24,
            'screen_margin': 12,
            'slide_offset_y': 8,
            'slide_steps': 5,
            'slide_interval_ms': 18,
        },
    },
    'chat': {
        'transcript_pad_x': 16,
        'transcript_pad_y': 14,
        'input_pad_x': 12,
        'input_pad_y': 10,
        'permission_wraplength': 520,
        'permission_summary_max_chars': 600,
    },
    'menu': {
        'title_text': 'Quick Menu',
        'subtitle_text': 'Control Center',
        'item_pad_x': 14,
        'item_pad_y': 10,
        'item_frame_pad_x': 10,
        'item_frame_pad_y': 4,
        'item_indicator_width': 5,
        'item_border_width': 1,
        'separator_pad_x': 18,
        'separator_pad_y': 8,
        'title_pad_x': 14,
        'title_pad_y': 12,
        'header_pad_x': 10,
        'header_pad_y': 10,
        'body_pad_x': 10,
        'body_pad_y': 10,
    },
    'settings': {
        'tab_padding': (14, 7),
        'tab_padding_selected': (18, 9),
    },
    'buttons': {
        'primary': {
            'bg': 'panel',
            'fg': 'text',
            'activebackground': 'gold_soft',
            'activeforeground': 'text',
            'highlightbackground': 'gold',
            'highlightthickness': 2,
            'relief': 'flat',
            'bd': 0,
            'cursor': 'hand2',
            'compound': 'center',
            'hover_bg': 'white',
            'hover_fg': 'text',
            'hover_border_color': 'gold_bright',
            'hover_highlightthickness': 2,
            'pressed_bg': 'gold_soft',
            'pressed_fg': 'text',
            'pressed_border_color': 'gold_deep',
            'pressed_highlightthickness': 2,
            'pulse_border_off_color': 'panel',
            'pulse_step_ms': 40,
            'pulse_steps': 20,
            'image': None,
            'hover_image': None,
            'pressed_image': None,
            'image_size': None,
        },
        'secondary': {
            'bg': 'transparent',
            'fg': 'text',
            'activebackground': 'hover',
            'activeforeground': 'text',
            'highlightbackground': 'accent',
            'highlightthickness': 1,
            'normal_side_border_only': False,
            'content_pady': 8,
            'relief': 'flat',
            'bd': 0,
            'cursor': 'hand2',
            'compound': 'center',
            'hover_bg': 'panel',
            'hover_fg': 'gold',
            'hover_border_color': 'gold_bright',
            'hover_highlightthickness': 1,
            'pressed_bg': 'hover',
            'pressed_fg': 'text',
            'pressed_border_color': 'border_strong',
            'pulse_border_off_color': 'gold_bright',
            'pulse_border_mid_color': 'accent',
            'pulse_step_ms': 40,
            'pulse_steps': 20,
            'image': None,
            'hover_image': None,
            'pressed_image': None,
            'image_size': None,
        },
        'ghost': {
            'bg': 'card_alt',
            'fg': 'text',
            'activebackground': 'hover',
            'activeforeground': 'text',
            'highlightbackground': 'border',
            'highlightthickness': 1,
            'relief': 'flat',
            'bd': 0,
            'cursor': 'hand2',
            'compound': 'center',
            'hover_bg': 'panel',
            'hover_fg': 'text',
            'hover_border_color': 'gold',
            'pressed_bg': 'hover',
            'pressed_fg': 'text',
            'pressed_border_color': 'border_strong',
            'pulse_border_off_color': 'card_alt',
            'pulse_step_ms': 40,
            'pulse_steps': 20,
            'image': None,
            'hover_image': None,
            'pressed_image': None,
            'image_size': None,
        },
    },
    'bubble': {
        'permission_bg': 'info',
        'permission_border': 'accent_soft',
        'celebrating_bg': 'success',
        'celebrating_border': 'accent',
        'building_bg': 'warn',
        'building_border': 'gold',
        'fetching_bg': 'info',
        'fetching_border': 'accent',
        'searching_bg': 'pink_soft',
        'searching_border': 'gold_soft',
        'analyzing_bg': 'warn',
        'analyzing_border': 'gold_soft',
    },
}


def _build_fonts(font_config):
    family = font_config['family']
    base_size = font_config['base'][1]
    small_size = font_config['small'][1]
    control_size = font_config['control'][1]
    return {
        'family': family,
        'title': font_config['title'],
        'subtitle': font_config['subtitle'],
        'base': font_config['base'],
        'small': font_config['small'],
        'control': font_config['control'],
        'menu_title': (family, max(base_size, small_size + 1), 'bold'),
        'menu_item': (family, base_size),
        'caption': (family, small_size),
        'button': (family, control_size),
    }


def _deep_merge(base, overrides):
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def get_theme():
    theme = deepcopy(_BASE_THEME)
    theme['fonts'] = _build_fonts(get_font_config())
    _deep_merge(theme, deepcopy(THEME_OVERRIDES))
    return theme
