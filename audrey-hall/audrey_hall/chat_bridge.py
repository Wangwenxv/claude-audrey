import base64
import json
import mimetypes
import re
import threading
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from .claude_agent import ClaudeCodeSession, normalize_connection_target


MAX_HISTORY_SESSIONS = 18
MAX_HISTORY_LABEL_CHARS = 24
MAX_TOOL_DETAIL_CHARS = 160
UNSELECTED_CONNECTION_TARGET = ''
CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'
BRIDGE_LOG_PATH = Path(gettempdir()) / 'audrey-chat-bridge.log'
TOOL_ICONS = {
    'read': '📖', 'grep': '🔍', 'glob': '📂',
    'bash': '⚡', 'powershell': '⚡',
    'write': '✏️', 'edit': '✏️', 'notebookedit': '✏️',
    'websearch': '🌐', 'webfetch': '🌐',
    'task': '🤖', 'agent': '🤖', 'taskcreate': '🤖',
}


def _sanitize_project_path(path_text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '-', path_text or '')


class WpfChatBridge:
    """Bridge WPF chat commands to ClaudeCodeSession events."""

    def __init__(self, app, version: str, process_manager):
        self.app = app
        self.version = version
        self.process_manager = process_manager
        self.session = ClaudeCodeSession(self._handle_session_event)
        self._busy = False
        self._started = False
        self._active_session_id = ''
        self._connection_target = UNSELECTED_CONNECTION_TARGET
        self._active_permission_mode = 'default'
        self._resume_session_id = ''
        self._pending_image_paths = []
        self._starting_session = False
        self._last_stream_texts = {}
        self._last_status_bar_text = ''
        self._auto_allow_tools = set()
        self._pending_permission_tools = {}

    def _log(self, message: str):
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            BRIDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with BRIDGE_LOG_PATH.open('a', encoding='utf-8') as handle:
                handle.write(f'[{timestamp}] {message}\n')
        except Exception:
            pass

    def show(self) -> bool:
        if not self.process_manager.show():
            return False
        self._send_state()
        return True

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
        try:
            self.process_manager.close()
        except Exception:
            pass
        self._clear_bubble_state()

    def handle_command(self, command: dict):
        command_type = command.get('type')
        if command_type == 'chat.ready':
            self._log('chat.ready')
            self._send_state()
            self._send_history_items()
            return
        if command_type == 'chat.show':
            self._log('chat.show')
            self._send_state()
            self._send_history_items()
            return
        if command_type == 'session.connect':
            self._log('session.connect')
            if not self._connection_target:
                self._send_status('请先选择思维链，再点击连接。')
                self._append_stream_message('status', '请先选择思维链，再点击连接。', stream_key='connect-required')
                return
            self._ensure_session_started(async_start=True)
            return
        if command_type == 'message.send':
            text = command.get('text')
            image_paths = command.get('image_paths')
            if isinstance(text, str):
                self._send_user_message(text, image_paths if isinstance(image_paths, list) else [])
            return
        if command_type == 'message.clear':
            self._new_session('已清空当前对话，准备开启新会话。')
            return
        if command_type == 'message.stop':
            try:
                self.session.interrupt()
                self._send_status('已请求停止')
            except Exception as exc:
                self._send_error(f'停止失败：{exc}')
            return
        if command_type == 'permission.respond':
            request_id = command.get('request_id')
            allow = bool(command.get('allow'))
            always = bool(command.get('always'))
            if isinstance(request_id, str):
                tool_name = self._pending_permission_tools.pop(request_id, None)
                if allow and always and isinstance(tool_name, str) and tool_name:
                    self._auto_allow_tools.add(tool_name)
                self.session.respond_permission(request_id, allow)
            return
        if command_type == 'mode.set':
            mode = command.get('mode')
            if isinstance(mode, str):
                self._set_permission_mode(mode)
            return
        if command_type == 'connection.set':
            target = command.get('target')
            if isinstance(target, str):
                self._set_connection_target(target)
            return
        if command_type == 'history.refresh':
            self._send_history_items()
            return
        if command_type == 'history.delete':
            session_id = command.get('session_id')
            if isinstance(session_id, str):
                self._delete_session(session_id)
            return
        if command_type == 'session.resume':
            session_id = command.get('session_id')
            if isinstance(session_id, str):
                self._resume_session(session_id)
            return
        if command_type == 'session.new':
            self._new_session('已创建新会话。')
            return

    def _ensure_session_started(self, *, async_start: bool = False):
        if self._started:
            return
        if self._starting_session:
            return
        self._started = True
        self._starting_session = True
        self._send_status('正在唤醒奥黛丽的助手...')

        def _start_session():
            try:
                self._log(f'start session target={self._connection_target} resume={self._resume_session_id or "new"}')
                self.session.start()
            except Exception as exc:
                self._started = False
                self._send_error(f'呼唤助手失败：{exc}')
                self._send_message('system', f'[状态] 呼唤失败：{exc}', kind='status', author='状态')
                self._log(f'start failed: {exc}')
            finally:
                self._starting_session = False

        if async_start:
            threading.Thread(target=_start_session, daemon=True).start()
        else:
            _start_session()

    def _send_user_message(self, text: str, image_paths: list):
        normalized = text.strip()
        image_items = self._build_image_items(image_paths)
        if not normalized and not image_items:
            return
        if not self._started and not self._starting_session:
            self._send_status('请先选择思维链并点击连接，再发送消息。')
            self._append_stream_message('status', '请先选择思维链并点击连接，再发送消息。', stream_key='send-before-connect')
            return
        if self._busy:
            self._send_status('当前正在对话中，请稍后。')
            return
        self._busy = True
        display_text = self._build_display_text(normalized, image_items)
        message_content = self._build_message_content(normalized, image_items)
        self._send_message('user', display_text)
        self._send_status('奥黛丽 正在思考...')
        self._update_bubble_state('thinking', {'prompt': display_text})
        try:
            self.session.send_user_message(message_content)
        except Exception as exc:
            self._busy = False
            self._clear_bubble_state()
            self._send_error(f'发送失败：{exc}')

    def _build_image_items(self, image_paths: list) -> list[dict]:
        items = []
        for raw_path in image_paths:
            if not isinstance(raw_path, str):
                continue
            path = Path(raw_path)
            try:
                if not path.exists() or not path.is_file():
                    continue
                data = base64.b64encode(path.read_bytes()).decode('ascii')
            except Exception:
                continue
            media_type = mimetypes.guess_type(str(path))[0] or 'image/png'
            if not media_type.startswith('image/'):
                media_type = 'image/png'
            items.append({'filename': path.name, 'media_type': media_type, 'data': data})
        return items

    def _build_message_content(self, text: str, image_items: list[dict]):
        if not image_items:
            return text
        content = []
        if text:
            content.append({'type': 'text', 'text': text})
        for item in image_items:
            content.append(
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': item['media_type'],
                        'data': item['data'],
                    },
                }
            )
        return content

    def _build_display_text(self, text: str, image_items: list[dict]) -> str:
        image_lines = [f"[图片] {item.get('filename') or '未命名图片'}" for item in image_items]
        if text and image_lines:
            return text + '\n\n' + '\n'.join(image_lines)
        if image_lines:
            return '\n'.join(image_lines)
        return text

    def _handle_session_event(self, event: dict):
        kind = event.get('kind')
        if kind in {'terminal_line', 'stdout_raw_line', 'stderr_raw_line'}:
            return

        session_id = event.get('session_id')
        if isinstance(session_id, str) and session_id.strip():
            self._active_session_id = session_id.strip()
            self.process_manager.send(
                {
                    'type': 'session.state',
                    'session_id': self._active_session_id,
                    'label': f'当前会话：{self._active_session_id[:8]}',
                }
            )

        if kind == 'status':
            status = event.get('status')
            text = event.get('text') or ''
            connection_target = event.get('connection_target')
            permission_mode = event.get('permission_mode')
            if isinstance(connection_target, str):
                self._connection_target = normalize_connection_target(connection_target)
            if isinstance(permission_mode, str) and permission_mode:
                self._active_permission_mode = permission_mode
            if status == 'ready':
                self._log(f'session ready id={self._active_session_id}')
                self._started = True
                self._starting_session = False
                self._send_status(f'已连接：{self._connection_label(self._connection_target)}')
                self._append_stream_message('status', f'深红星辰已经建立连接：思维链-{self._connection_label(self._connection_target)}', stream_key='ready')
                self._send_history_items()
            elif isinstance(text, str) and text:
                self._send_status(text)
            return

        if kind == 'sdk_status':
            permission_mode = event.get('permission_mode')
            if isinstance(permission_mode, str) and permission_mode:
                self._active_permission_mode = permission_mode
            status = event.get('status') or ''
            if status == 'compacting':
                self._send_status('正在压缩上下文...')
                self._append_stream_message('status', '正在压缩上下文...', stream_key='compacting')
            return

        if kind == 'session_state':
            state = str(event.get('state') or '').strip().lower()
            if state == 'running':
                self._send_status('会话运行中...')
            elif state == 'idle':
                self._send_status('当前轮次已空闲')
                self._append_stream_message('status', '当前轮次已空闲', stream_key='session_state')
            elif state:
                self._send_status(f'会话状态：{state}')
                self._append_stream_message('status', f'会话状态：{state}', stream_key='session_state')
            return

        if kind == 'assistant':
            text = event.get('text') or ''
            if isinstance(text, str) and text.strip():
                reminder = self._translate_system_reminder(text.strip())
                if reminder:
                    self._send_status(reminder)
                    self._append_stream_message('status', reminder, stream_key='system_reminder')
                    return
                self._send_message('assistant', text.strip())
                self._send_status('奥黛丽 正在回复...')
            return

        if kind == 'thinking':
            thinking_text = self._with_token_suffix('奥黛丽 正在思考...', event)
            self._send_status(thinking_text)
            self._append_stream_message('status', thinking_text, stream_key='thinking')
            return

        if kind == 'working':
            tool_name = event.get('tool_name') or '工具'
            summary = event.get('summary') or ''
            tool_text = self._format_tool_line(tool_name, summary, event)
            self._send_status(f'正在使用工具：{tool_name}')
            self._append_stream_message('tool', tool_text, stream_key=f'tool:{str(tool_name).strip().lower()}')
            self._update_bubble_state(
                'working',
                {
                    'tool_name': tool_name,
                    'input': event.get('input') or {},
                },
            )
            return

        if kind == 'permission':
            tool_name = event.get('tool_name') or '未知工具'
            request_id = event.get('request_id') or ''
            if tool_name in self._auto_allow_tools and isinstance(request_id, str) and request_id:
                self.session.respond_permission(request_id, True)
                self._append_stream_message('tool', f'🪝 已自动允许：{tool_name}', stream_key='permission')
                return
            if isinstance(request_id, str) and request_id:
                self._pending_permission_tools[request_id] = str(tool_name)
            self.process_manager.send(
                {
                    'type': 'permission.request',
                    'request_id': request_id,
                    'tool_name': tool_name,
                    'input': event.get('input') or {},
                }
            )
            self._update_bubble_state(
                'permission',
                {
                    'tool_name': event.get('tool_name'),
                    'input': event.get('input') or {},
                },
            )
            self._append_stream_message('tool', f'🪝 权限请求：{tool_name}', stream_key='permission')
            return

        if kind == 'done':
            self._busy = False
            ok = bool(event.get('ok'))
            if ok:
                self._send_status('本轮对话完成')
                self._update_bubble_state('done', {'result': event.get('text') or ''})
                self._send_history_items()
            else:
                self._send_error(event.get('text') or 'Claude Code 返回错误')
                self._clear_bubble_state()
            return

        if kind == 'error':
            self._busy = False
            self._send_error(event.get('text') or 'Claude Code 发生错误')
            self._clear_bubble_state()

    def _send_state(self):
        self.process_manager.send(
            {
                'type': 'app.state',
                'version': self.version,
                'status': 'ready',
                'status_text': '请选择思维链后点击连接，或直接发送消息。',
                'mode': self._active_permission_mode,
                'connection_target': self._connection_target,
            }
        )
        self._send_history_items()

    def _set_permission_mode(self, mode: str):
        try:
            self._active_permission_mode = mode
            self.session.set_permission_mode(mode)
            self._send_status(f'正在切换模式：{self._mode_label(mode)}')
            self._send_state()
        except Exception as exc:
            self._send_error(f'切换模式失败：{exc}')

    def _set_connection_target(self, target: str):
        normalized = normalize_connection_target(target)
        if normalized == self._connection_target and self._connection_target:
            self._send_status(f'当前思维链：{self._connection_label(normalized)}')
            return
        was_started = self._started or self._starting_session
        self._connection_target = normalized
        self._send_state()
        if was_started:
            self._reconnect(
                resume_session_id=self._resume_session_id,
                announce=f'正在切换思维链：{self._connection_label(normalized)}',
                autostart=True,
            )
        else:
            self._send_status(f'思维链已切换：{self._connection_label(normalized)}，点击连接后生效')
            self._append_stream_message(
                'status',
                f'思维链已切换：{self._connection_label(normalized)}，点击连接后生效',
                stream_key='connection-target',
            )

    def _new_session(self, announce: str):
        self._resume_session_id = ''
        self._active_session_id = ''
        self.process_manager.send({'type': 'message.clear'})
        self._reconnect(resume_session_id='', announce=announce, autostart=False)

    def _resume_session(self, session_id: str):
        target = session_id.strip()
        if not target:
            return
        if self._busy:
            self._send_status('Claude 正在处理当前请求，稍后再恢复历史会话。')
            return
        self._resume_session_id = target
        self._active_session_id = target
        self.process_manager.send({'type': 'message.clear'})
        self._load_session_transcript_preview(target)
        self._reconnect(resume_session_id=target, announce=f'正在恢复历史会话：{target[:8]}', autostart=False)

    def _reconnect(self, *, resume_session_id: str = '', announce: str = '', autostart: bool = False):
        try:
            self.session.close()
        except Exception:
            pass
        self._busy = False
        self._started = False
        self.session = ClaudeCodeSession(
            self._handle_session_event,
            connection_target=self._connection_target,
            resume_session_id=resume_session_id or None,
        )
        self._starting_session = False
        self._send_state()
        if announce:
            self._send_status(announce)
        if autostart:
            self._ensure_session_started(async_start=True)

    def _history_project_dir(self) -> Path:
        return CLAUDE_PROJECTS_DIR / _sanitize_project_path(str(Path(self.session.working_dir)))

    def _read_recent_sessions(self) -> list[dict]:
        project_dir = self._history_project_dir()
        if not project_dir.exists() or not project_dir.is_dir():
            return []
        session_files = sorted(
            project_dir.glob('*.jsonl'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        items = []
        for path in session_files[:MAX_HISTORY_SESSIONS]:
            item = self._read_session_preview(path)
            if item:
                items.append(item)
        return items

    def _read_session_preview(self, path: Path) -> dict | None:
        session_id = path.stem
        title = ''
        summary = ''
        first_prompt = ''
        last_timestamp = ''
        try:
            with path.open('r', encoding='utf-8', errors='replace') as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    timestamp = entry.get('timestamp')
                    if isinstance(timestamp, str) and timestamp.strip():
                        last_timestamp = timestamp.strip()
                    entry_type = entry.get('type')
                    if not title and entry_type in {'custom-title', 'summary'}:
                        candidate = entry.get('customTitle') or entry.get('summary')
                        if isinstance(candidate, str) and candidate.strip():
                            title = candidate.strip()
                    if entry_type == 'last-prompt':
                        candidate = entry.get('lastPrompt')
                        if isinstance(candidate, str) and candidate.strip():
                            first_prompt = candidate.strip()
                    if entry_type == 'user' and not first_prompt:
                        role, text = self._extract_transcript_entry(entry)
                        if role == 'user' and text:
                            first_prompt = text
                    candidate_summary = entry.get('summary')
                    if isinstance(candidate_summary, str) and candidate_summary.strip():
                        summary = candidate_summary.strip()
        except Exception:
            return None
        display_title = self._compact_history_label(title or first_prompt or session_id)
        display_summary = self._compact_history_label(summary or first_prompt)
        return {
            'session_id': session_id,
            'title': display_title or session_id,
            'summary': display_summary,
            'timestamp': self._format_history_timestamp(last_timestamp),
            'is_active': session_id == self._active_session_id,
        }

    def _send_history_items(self):
        self.process_manager.send({'type': 'history.items', 'items': self._read_recent_sessions()})

    def _delete_session(self, session_id: str):
        sid = session_id.strip()
        if not sid:
            return
        try:
            path = self._history_project_dir() / f'{sid}.jsonl'
            if path.exists():
                path.unlink()
        except Exception:
            pass
        if sid == self._active_session_id:
            self._new_session('已删除当前会话，准备开启新会话。')
        self._send_history_items()

    def _load_session_transcript_preview(self, session_id: str):
        path = self._history_project_dir() / f'{session_id}.jsonl'
        if not path.exists():
            return
        loaded = 0
        try:
            with path.open('r', encoding='utf-8', errors='replace') as handle:
                for raw_line in handle:
                    if loaded >= 24:
                        break
                    try:
                        entry = json.loads(raw_line.strip())
                    except Exception:
                        continue
                    role, text = self._extract_transcript_entry(entry)
                    if role and text:
                        self._send_message(role, text)
                        loaded += 1
        except Exception:
            pass

    def _extract_transcript_entry(self, entry: dict) -> tuple[str, str]:
        entry_type = entry.get('type')
        if entry_type not in {'user', 'assistant'}:
            return '', ''
        role = 'assistant' if entry_type == 'assistant' else 'user'
        message = entry.get('message') or {}
        content = message.get('content') if isinstance(message, dict) else None
        if isinstance(content, str):
            return role, content.strip()
        if not isinstance(content, list):
            return '', ''
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get('type')
            if block_type == 'text':
                value = block.get('text')
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            elif block_type == 'image':
                parts.append('[图片]')
        return role, '\n\n'.join(parts).strip()

    def _compact_history_label(self, value) -> str:
        if not isinstance(value, str):
            return ''
        first_line = value.splitlines()[0].strip() if value.splitlines() else ''
        compact = ' '.join(first_line.split())
        if len(compact) <= MAX_HISTORY_LABEL_CHARS:
            return compact
        return compact[:MAX_HISTORY_LABEL_CHARS] + '...'

    def _format_history_timestamp(self, value: str) -> str:
        if not value:
            return '未知时间'
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).strftime('%m-%d %H:%M')
        except Exception:
            return value[:16]

    def _mode_label(self, mode: str) -> str:
        return {
            'default': '默认陪伴',
            'acceptEdits': '更改权限',
            'bypassPermissions': '全部权限',
        }.get(mode, mode)

    def _connection_label(self, target: str) -> str:
        return {
            'project': '本项目 Claude',
            'system': '本地 Claude',
            'auto': '自动选择',
            '': '请选择思维链',
        }.get(target, target)
        self.process_manager.send(
            {
                'type': 'session.state',
                'session_id': self._active_session_id,
                'label': f'当前会话：{self._active_session_id[:8]}' if self._active_session_id else '当前会话：新对话',
            }
        )

    def _send_message(self, role: str, text: str, *, kind: str = 'message', author: str | None = None):
        stream_key = ''
        if kind == 'status' and role in {'system', 'tool'}:
            stream_key = 'status'
        self.process_manager.send(
            {
                'type': 'message.append',
                'id': uuid4().hex,
                'role': role,
                'author': author or ('你' if role == 'user' else '奥黛丽' if role == 'assistant' else role),
                'kind': kind,
                'stream_key': stream_key,
                'text': text,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
            }
        )

    def _send_status(self, text: str):
        if text == self._last_status_bar_text:
            return
        self._last_status_bar_text = text
        self.process_manager.send(
            {
                'type': 'status.update',
                'text': text,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
            }
        )

    def _send_error(self, text: str):
        self.process_manager.send({'type': 'error', 'text': text})
        self._send_status('发生错误')

    def _append_stream_message(self, stream_type: str, text: str, *, stream_key: str | None = None):
        compact = ' '.join(str(text or '').split())
        if not compact:
            return
        key = stream_key or stream_type
        if self._last_stream_texts.get(key) == compact:
            return
        self._last_stream_texts[key] = compact
        role = 'tool' if stream_type == 'tool' else 'system'
        author = '工具' if stream_type == 'tool' else '状态'
        self.process_manager.send(
            {
                'type': 'message.append',
                'id': uuid4().hex,
                'role': role,
                'author': author,
                'kind': 'status',
                'stream_key': key,
                'text': compact,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
            }
        )

    def _format_tool_line(self, tool_name: str, summary: str, event: dict) -> str:
        name = str(tool_name or '工具').strip()
        icon = self._pick_tool_icon(name)
        detail = str(summary or '').strip()
        if not detail:
            detail = self._summarize_tool_input(name, event.get('input') or {})
        detail = self._truncate_tool_detail(detail)
        base = f'{icon} {name}'
        if detail:
            base = f'{base} | {detail}'
        return self._with_token_suffix(base, event)

    def _truncate_tool_detail(self, text: str) -> str:
        compact = ' '.join(str(text or '').strip().split())
        if not compact:
            return ''
        if len(compact) <= MAX_TOOL_DETAIL_CHARS:
            return compact
        return compact[:MAX_TOOL_DETAIL_CHARS - 3].rstrip() + '...'

    def _pick_tool_icon(self, tool_header: str) -> str:
        lowered = str(tool_header or '').split('|', 1)[0].strip().lower()
        for key, icon in TOOL_ICONS.items():
            if lowered.startswith(key):
                return icon
        return '🔧'

    def _with_token_suffix(self, text: str, event: dict) -> str:
        input_tokens = event.get('input_tokens')
        output_tokens = event.get('output_tokens')
        total_tokens = event.get('total_tokens')
        if (isinstance(input_tokens, int) and input_tokens > 0) or (isinstance(output_tokens, int) and output_tokens > 0):
            parts = []
            if isinstance(input_tokens, int) and input_tokens > 0:
                parts.append(f'↓ {self._format_token_count(input_tokens)}')
            if isinstance(output_tokens, int) and output_tokens > 0:
                parts.append(f'↑ {self._format_token_count(output_tokens)}')
            return f'{text} <{", ".join(parts)}>'
        if isinstance(total_tokens, int) and total_tokens > 0:
            return f'{text} <total {self._format_token_count(total_tokens)}>'
        return text

    def _format_token_count(self, value: int) -> str:
        if value >= 1_000_000:
            return f'{value / 1_000_000:.1f}M tok'
        if value >= 1_000:
            return f'{value / 1_000:.1f}k tok'
        return f'{value} tok'

    def _translate_system_reminder(self, text: str) -> str:
        if not isinstance(text, str):
            return ''
        match = re.fullmatch(r'\s*<system-reminder>\s*([\s\S]*?)\s*</system-reminder>\s*', text)
        if match:
            reminder = ' '.join(match.group(1).strip().split())
        else:
            partial = re.search(r'<system-reminder>\s*([\s\S]*?)\s*</system-reminder>', text)
            if not partial:
                return ''
            reminder = ' '.join(partial.group(1).strip().split())
        mode_change = re.search(r'operational mode has changed from\s+(\w+)\s+to\s+(\w+)', reminder, re.IGNORECASE)
        if mode_change:
            old_mode = {
                'plan': '计划',
                'build': '构建',
                'default': '默认陪伴',
                'acceptedits': '更改权限',
                'bypasspermissions': '全部权限',
            }.get(mode_change.group(1).lower(), mode_change.group(1))
            new_mode = {
                'plan': '计划',
                'build': '构建',
                'default': '默认陪伴',
                'acceptedits': '更改权限',
                'bypasspermissions': '全部权限',
            }.get(mode_change.group(2).lower(), mode_change.group(2))
            detail = f'模式切换：{old_mode} -> {new_mode}'
            if 'no longer in read-only mode' in reminder.lower():
                detail += '，已解除只读'
            if 'permitted to make file changes' in reminder.lower():
                detail += '，可改文件/跑命令/用工具'
            return detail
        return reminder

    def _update_bubble_state(self, hook_type: str, payload: dict | None = None):
        hook_state = getattr(self.app, 'claude_hook_state', None)
        if hook_state is None:
            return
        try:
            hook_state.handle_hook(hook_type, payload or {})
        except Exception:
            pass

    def _clear_bubble_state(self):
        self._update_bubble_state(
            'state',
            {
                'status': 'idle',
                'bubble': '',
                'detail': '',
            },
        )
