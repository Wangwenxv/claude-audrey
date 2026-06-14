import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any


DEFAULT_PORT = 9527
ACTIVE_MIN_DURATION_MS = 1200
DONE_DURATION_MS = 900
IDLE_DELAY_MS = 300


@dataclass(slots=True)
class BubbleState:
    status: str = 'idle'
    bubble: str = ''
    tool_name: str | None = None
    detail: str = ''
    updated_at: float = field(default_factory=time.monotonic)
    source: str = 'startup'

    def to_dict(self) -> dict[str, Any]:
        return {
            'status': self.status,
            'bubble': self.bubble,
            'tool_name': self.tool_name,
            'detail': self.detail,
            'updated_at': self.updated_at,
            'source': self.source,
        }


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get('text')
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return '\n'.join(parts).strip()
    if isinstance(value, dict):
        for key in ('text', 'message', 'content', 'output'):
            extracted = _extract_text(value.get(key))
            if extracted:
                return extracted
    return ''


def _map_tool_state(tool_name: str | None) -> tuple[str, str]:
    name = (tool_name or '').strip()
    if name in {'Read', 'Glob', 'Grep', 'LS', 'TaskGet', 'TaskList', 'ListMcpResourcesTool'}:
        return 'fetching', '让我先查查看...'
    if name in {'Write', 'Edit', 'NotebookEdit'}:
        return 'building', '嗯嗯...开始书写...'
    if name in {'Bash', 'PowerShell'}:
        return 'working', '正在执行命令...'
    if name in {'Agent', 'TaskCreate', 'TaskUpdate', 'Task', 'TodoWrite', 'TaskOutput'}:
        return 'analyzing', '嗯...我在思考...'
    if name == 'WebFetch':
        return 'fetching', '让我先查查看...'
    if name == 'WebSearch':
        return 'searching', '让我找找资料...'
    if name:
        return 'working', '工作中...'
    return 'working', '稍等下，我正在处理...'


class ClaudeHookState:
    def __init__(self):
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._listeners: list[Any] = []
        self._state = BubbleState()

    def add_listener(self, listener):
        with self._lock:
            self._listeners.append(listener)

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def handle_hook(self, hook_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        hook_type = hook_type.strip().lower()
        if hook_type == 'thinking':
            text = _extract_text(payload.get('prompt')) or _extract_text(payload.get('message'))
            return self._set_state(
                status='chatting',
                bubble='嗯...我在思考...',
                tool_name=None,
                detail=text,
                source='thinking',
            )
        if hook_type == 'working':
            tool_name = payload.get('tool_name')
            status, bubble = _map_tool_state(tool_name if isinstance(tool_name, str) else None)
            detail = _extract_text(payload.get('input')) or _extract_text(payload.get('message'))
            return self._set_state(
                status=status,
                bubble=bubble,
                tool_name=tool_name if isinstance(tool_name, str) else None,
                detail=detail,
                source='working',
            )
        if hook_type == 'done':
            detail = _extract_text(payload.get('result')) or _extract_text(payload.get('message'))
            return self._set_state(
                status='celebrating',
                bubble='搞定了！',
                tool_name=None,
                detail=detail,
                source='done',
                schedule_idle_after_ms=DONE_DURATION_MS,
            )
        if hook_type == 'permission':
            tool_name = payload.get('tool_name')
            detail = _extract_text(payload.get('input')) or _extract_text(payload.get('message'))
            return self._set_state(
                status='permission',
                bubble='先生，我需要您的权限...',
                tool_name=tool_name if isinstance(tool_name, str) else None,
                detail=detail,
                source='permission',
            )
        if hook_type == 'idle':
            return self._schedule_idle('idle')
        if hook_type == 'state':
            return self._set_state(
                status=str(payload.get('status') or 'idle'),
                bubble=_extract_text(payload.get('bubble')),
                tool_name=payload.get('tool_name') if isinstance(payload.get('tool_name'), str) else None,
                detail=_extract_text(payload.get('detail')),
                source='state',
            )
        return self.get_state()

    def _notify(self, state: BubbleState):
        listeners = []
        with self._lock:
            listeners = list(self._listeners)
        snapshot = state.to_dict()
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                pass

    def _cancel_timer_locked(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _set_state(
        self,
        *,
        status: str,
        bubble: str,
        tool_name: str | None,
        detail: str,
        source: str,
        schedule_idle_after_ms: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._cancel_timer_locked()
            self._state = BubbleState(
                status=status,
                bubble=bubble,
                tool_name=tool_name,
                detail=detail,
                updated_at=time.monotonic(),
                source=source,
            )
            state = self._state
            if schedule_idle_after_ms is not None:
                self._timer = threading.Timer(
                    schedule_idle_after_ms / 1000,
                    self._set_idle_now,
                    kwargs={'source': 'done_timeout'},
                )
                self._timer.daemon = True
                self._timer.start()
        self._notify(state)
        return state.to_dict()

    def _schedule_idle(self, source: str) -> dict[str, Any]:
        with self._lock:
            elapsed_ms = (time.monotonic() - self._state.updated_at) * 1000
            delay_ms = max(IDLE_DELAY_MS, ACTIVE_MIN_DURATION_MS - int(elapsed_ms))
            self._cancel_timer_locked()
            self._timer = threading.Timer(
                max(0, delay_ms) / 1000,
                self._set_idle_now,
                kwargs={'source': source},
            )
            self._timer.daemon = True
            self._timer.start()
            return self._state.to_dict()

    def _set_idle_now(self, source: str = 'idle'):
        with self._lock:
            self._timer = None
            self._state = BubbleState(
                status='idle',
                bubble='',
                tool_name=None,
                detail='',
                updated_at=time.monotonic(),
                source=source,
            )
            state = self._state
        self._notify(state)


def decode_json_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode('utf-8'))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}
