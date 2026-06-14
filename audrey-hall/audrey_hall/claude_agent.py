import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable, Literal, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_CODE_ROOT = PROJECT_ROOT.parent

# AI 对话启动时 Claude 的默认工作目录。
FALLBACK_WORKING_DIR = Path(__file__).parent.parent
DEFAULT_WORKING_DIR = (
    CLAUDE_CODE_ROOT if CLAUDE_CODE_ROOT.exists() else FALLBACK_WORKING_DIR
)
PRESERVE_AUTH_ENV_VAR = 'AMEATH_PRESERVE_CLAUDE_AUTH_ENV'
ConnectionTarget = Literal['auto', 'project', 'system']
CONNECTION_TARGET_LABELS = {
    'auto': '思维链-默认',
    'project': '思维链-本项目',
    'system': '思维链-官Claude',
}


def normalize_connection_target(value: str | None) -> ConnectionTarget:
    normalized = (value or 'auto').strip().lower()
    if normalized in CONNECTION_TARGET_LABELS:
        return normalized
    return 'auto'


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _safe_get_text_block(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ''

    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text':
            text = block.get('text')
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return '\n\n'.join(parts).strip()


def _safe_get_thinking_block(content) -> str:
    if not isinstance(content, list):
        return ''

    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get('type')
        if block_type == 'thinking':
            text = block.get('thinking')
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        elif block_type == 'redacted_thinking':
            data = block.get('data')
            if isinstance(data, str) and data.strip():
                parts.append('[已折叠的思考]')
    return '\n\n'.join(parts).strip()


def _extract_tool_use_blocks(content) -> list[dict]:
    if not isinstance(content, list):
        return []

    tool_uses = []
    for block in content:
        if isinstance(block, dict) and block.get('type') == 'tool_use':
            tool_uses.append(block)
    return tool_uses


def _summarize_tool_input(tool_name: str, input_payload) -> str:
    if not isinstance(input_payload, dict):
        return ''
    preferred_keys = {
        'Read': ('file_path', 'path'),
        'Grep': ('pattern', 'query'),
        'Glob': ('pattern',),
        'Bash': ('command',),
        'PowerShell': ('command',),
        'WebSearch': ('query',),
        'WebFetch': ('url',),
        'Task': ('description', 'prompt'),
        'TaskCreate': ('description', 'prompt'),
        'Agent': ('description', 'prompt'),
        'Write': ('file_path', 'path'),
        'Edit': ('file_path', 'path'),
    }
    for key in preferred_keys.get(tool_name, ('file_path', 'path', 'pattern', 'query', 'command', 'url', 'description')):
        value = input_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _task_progress_event(message: dict) -> dict:
    status = message.get('status') or 'running'
    return {
        'kind': 'task_progress',
        'status': status if isinstance(status, str) else 'running',
        'task_id': message.get('task_id'),
        'tool_use_id': message.get('tool_use_id'),
        'description': message.get('description') or '',
        'summary': message.get('summary') or '',
        'last_tool_name': message.get('last_tool_name') or '',
        'workflow_progress': message.get('workflow_progress') or [],
        'usage': message.get('usage') or {},
    }


def _usage_total_tokens(usage) -> int | None:
    if not isinstance(usage, dict):
        return None
    total = usage.get('total_tokens')
    if isinstance(total, int):
        return total

    fields = (
        'input_tokens',
        'output_tokens',
        'cache_creation_input_tokens',
        'cache_read_input_tokens',
        'cache_deleted_input_tokens',
    )
    values = []
    for field in fields:
        value = usage.get(field)
        if isinstance(value, int):
            values.append(value)
    if values:
        return sum(values)
    return None


def _usage_input_output_tokens(usage) -> tuple[int | None, int | None]:
    if not isinstance(usage, dict):
        return None, None
    input_tokens = usage.get('input_tokens')
    output_tokens = usage.get('output_tokens')
    return (
        input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else None,
        output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else None,
    )


def _extract_string(value) -> str:
    return value.strip() if isinstance(value, str) else ''


class ClaudeCodeSession:
    def __init__(
        self,
        on_event: Callable[[dict], None],
        working_dir: Optional[str] = None,
        connection_target: str = 'auto',
        resume_session_id: Optional[str] = None,
    ):
        self.on_event = on_event
        if working_dir:
            self.working_dir = working_dir
        elif DEFAULT_WORKING_DIR.exists():
            self.working_dir = str(DEFAULT_WORKING_DIR)
        else:
            self.working_dir = str(PROJECT_ROOT)
        self.process = None
        self._writer_lock = threading.Lock()
        self._closed = False
        self._initialized = False
        self._pending_permissions = {}
        self._pending_control_requests = {}
        self._last_assistant_text = ''
        self._total_tokens = 0
        self.connection_target = normalize_connection_target(connection_target)
        self._connection_source = '未连接'
        self._session_id = ''
        self.resume_session_id = (resume_session_id or '').strip()

    def _send_control_request(self, request: dict):
        self._ensure_started()
        request_id = str(uuid.uuid4())
        payload = {
            'type': 'control_request',
            'request_id': request_id,
            'request': request,
        }
        if self._session_id:
            payload['session_id'] = self._session_id
        subtype = request.get('subtype')
        if isinstance(subtype, str) and subtype:
            self._pending_control_requests[request_id] = subtype
        self._write_json(payload)

    def start(self):
        if self.process is not None:
            return

        command = self._build_command()
        env = self._build_child_env()

        self.process = subprocess.Popen(
            command,
            cwd=self.working_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._send_initialize()

    def _build_child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if _is_truthy_env(env.get(PRESERVE_AUTH_ENV_VAR)):
            return env

        # 检查是否存在 OAuth 认证（Claude.ai 订阅用户）
        has_oauth = bool(
            env.get('CLAUDE_CODE_OAUTH_TOKEN') or
            env.get('CLAUDE_CODE_OAUTH_ACCESS_TOKEN')
        )

        if has_oauth:
            # OAuth 存在时，剥离 API key env vars，防止 --print 模式下
            # env API key 错误覆盖 OAuth 认证
            for key in (
                'ANTHROPIC_API_KEY',
                'ANTHROPIC_AUTH_TOKEN',
                'CLAUDE_CODE_USE_BEDROCK',
                'CLAUDE_CODE_USE_VERTEX',
                'CLAUDE_CODE_USE_FOUNDRY',
            ):
                env.pop(key, None)
        else:
            # 没有 OAuth 时，保留 API key env vars
            # 用户依赖环境变量中的 API key，剥离会导致认证失败（402）
            # 只剥离第三方 provider 的切换开关（这些不是认证信息）
            for key in (
                'CLAUDE_CODE_USE_BEDROCK',
                'CLAUDE_CODE_USE_VERTEX',
                'CLAUDE_CODE_USE_FOUNDRY',
            ):
                env.pop(key, None)

        return env

    # stream-json 协议下的统一命令参数。
    # 注意：不要加 --bare —— 它会把工具集裁剪到只剩 Bash/Edit/Read，
    # 导致 Write、Glob、Grep、WebSearch 等都不可用（助手会说“Write 工具不可用”
    # 而退化成用 Bash）。去掉后可拿到完整工具集。
    _CLI_ARGS = [
        '--print',
        '--verbose',
        '--input-format',
        'stream-json',
        '--output-format',
        'stream-json',
        '--permission-prompt-tool',
        'stdio',
    ]

    def _build_cli_args(self) -> list[str]:
        args = list(self._CLI_ARGS)
        if self.resume_session_id:
            args.extend(['--resume', self.resume_session_id])
        return args

    def _get_project_command(self) -> list[str] | None:
        bun_path = shutil.which('bun.cmd') or shutil.which('bun')
        dev_entry = CLAUDE_CODE_ROOT / 'src' / 'dev-entry.ts'
        if bun_path and (CLAUDE_CODE_ROOT / 'node_modules').exists() and dev_entry.exists():
            return [
                bun_path,
                'run',
                str(dev_entry),
                *self._build_cli_args(),
            ]
        return None

    def _get_system_command(self) -> list[str]:
        claude_path = (
            shutil.which('claude')
            or shutil.which('claude.cmd')
            or shutil.which('claude.exe')
        )
        if claude_path:
            return [claude_path, *self._build_cli_args()]
        return ['claude', *self._build_cli_args()]

    def _build_command(self):
        # 本项目：用 bun 跑本地 claude-code 项目（src/dev-entry.ts）。
        # 这样对本地源码的修改（如人格/system prompt）才会在桌宠对话里生效。
        # Windows 下 CreateProcess 不会解析 .cmd/.ps1，必须用 shutil.which
        # 取到带扩展名的完整路径（如 bun.CMD），否则 subprocess 起不来。
        if self.connection_target == 'project':
            project_command = self._get_project_command()
            if project_command is None:
                raise RuntimeError(
                    '本项目 Claude Code 不可用，请确认 bun、node_modules 和 src/dev-entry.ts 存在'
                )
            self._connection_source = CONNECTION_TARGET_LABELS['project']
            return project_command

        if self.connection_target == 'system':
            self._connection_source = CONNECTION_TARGET_LABELS['system']
            return self._get_system_command()

        project_command = self._get_project_command()
        if project_command is not None:
            self._connection_source = CONNECTION_TARGET_LABELS['project']
            return project_command

        self._connection_source = CONNECTION_TARGET_LABELS['system']
        return self._get_system_command()

    def send_user_message(self, text: str):
        if not text.strip():
            return
        self._ensure_started()
        self._write_json(
            {
                'type': 'user',
                'message': {
                    'role': 'user',
                    'content': text,
                },
                'parent_tool_use_id': None,
                'session_id': self._session_id,
                'uuid': str(uuid.uuid4()),
            }
        )

    def respond_permission(self, request_id: str, allow: bool):
        request = self._pending_permissions.pop(request_id, None)
        if request is None:
            return

        # 响应必须严格匹配 Claude Code 的权限结果 schema
        # （PermissionPromptToolResultSchema）：
        #   allow -> { behavior:'allow', updatedInput:<object> }
        #   deny  -> { behavior:'deny',  message:<string> }
        # 之前发的 updatedInput:None 会让 zod 校验失败，导致权限请求被当作
        # 错误 reject，工具实际并未放行（弹窗点了也没用）。
        # updatedInput 传 {} 表示“沿用工具原始参数”。
        tool_use_id = request.get('tool_use_id')
        if allow:
            decision = {
                'behavior': 'allow',
                'updatedInput': {},
            }
        else:
            decision = {
                'behavior': 'deny',
                'message': '用户拒绝了该操作',
            }
        if tool_use_id:
            decision['toolUseID'] = tool_use_id

        self._write_json(
            {
                'type': 'control_response',
                'session_id': self._session_id,
                'response': {
                    'subtype': 'success',
                    'request_id': request_id,
                    'response': {
                        **decision,
                        'updated_input': decision.get('updatedInput', {}),
                    },
                },
            }
        )

    def interrupt(self):
        if self.process is None:
            return
        self._send_control_request({'subtype': 'interrupt'})

    def set_model(self, model: str | None):
        request = {'subtype': 'set_model'}
        if model is not None:
            request['model'] = model
        self._send_control_request(request)

    def set_max_thinking_tokens(self, max_tokens: int | None):
        self._send_control_request(
            {
                'subtype': 'set_max_thinking_tokens',
                'max_thinking_tokens': max_tokens,
            }
        )

    def set_permission_mode(self, mode: str):
        self._send_control_request(
            {
                'subtype': 'set_permission_mode',
                'mode': mode,
            }
        )

    def close(self):
        self._closed = True
        if self.process is None:
            return

        try:
            self._send_control_request(
                {
                    'subtype': 'end_session',
                    'reason': 'ameath_window_closed',
                }
            )
        except Exception:
            pass

        try:
            self.process.terminate()
        except Exception:
            pass
        self.process = None

    def _ensure_started(self):
        if self.process is None:
            self.start()

    def _send_initialize(self):
        request_id = str(uuid.uuid4())
        self._pending_control_requests[request_id] = 'initialize'
        self._write_json(
            {
                'type': 'control_request',
                'request_id': request_id,
                'request': {
                    'subtype': 'initialize',
                    'cwd': self.working_dir,
                    'permissionMode': 'default',
                },
            }
        )

    def _write_json(self, payload: dict):
        if self.process is None or self.process.stdin is None:
            raise RuntimeError('Claude Code 进程未启动')

        line = json.dumps(payload, ensure_ascii=False)
        with self._writer_lock:
            self.process.stdin.write(line + '\n')
            self.process.stdin.flush()

    def _read_stdout(self):
        if self.process is None or self.process.stdout is None:
            return

        try:
            for raw_line in self.process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._emit(
                        {
                            'kind': 'log',
                            'level': 'warn',
                            'text': f'无法解析 Claude Code 输出: {line[:200]}',
                        }
                    )
                    continue
                self._handle_stdout_message(message)
        finally:
            if not self._closed:
                self._emit(
                    {
                        'kind': 'status',
                        'status': 'disconnected',
                        'text': 'Claude Code 会话已结束',
                    }
                )

    def _read_stderr(self):
        if self.process is None or self.process.stderr is None:
            return

        for raw_line in self.process.stderr:
            line = raw_line.rstrip()
            if not line:
                continue
            self._emit(
                {
                    'kind': 'stderr',
                    'text': line,
                }
            )

    def _handle_stdout_message(self, message: dict):
        self._update_session_id(message)
        msg_type = message.get('type')

        if msg_type == 'control_response':
            response = message.get('response') or {}
            request_id = response.get('request_id')
            request_subtype = self._pending_control_requests.pop(request_id, None)
            if response.get('subtype') == 'success' and request_subtype == 'initialize' and not self._initialized:
                self._initialized = True
                self._emit(
                    {
                        'kind': 'status',
                        'status': 'ready',
                        'text': f'深红星辰已经建立连接： {self._connection_source}',
                        'connection_source': self._connection_source,
                        'connection_target': self.connection_target,
                        'session_id': self._session_id,
                    }
                )
            elif response.get('subtype') == 'success' and request_subtype == 'set_permission_mode':
                payload = response.get('response') or {}
                self._emit(
                    {
                        'kind': 'permission_mode',
                        'mode': payload.get('mode'),
                        'request_id': request_id,
                        'session_id': self._session_id,
                    }
                )
            elif response.get('subtype') == 'error':
                self._emit(
                    {
                        'kind': 'error',
                        'text': response.get('error') or 'Claude Code 控制请求失败',
                        'request_id': request_id,
                        'request_subtype': request_subtype,
                    }
                )
            return

        if msg_type == 'control_request':
            request = message.get('request') or {}
            if request.get('subtype') == 'can_use_tool':
                request_id = message.get('request_id')
                if request_id:
                    self._pending_permissions[request_id] = request
                    self._emit(
                        {
                            'kind': 'permission',
                            'request_id': request_id,
                            'tool_name': request.get('tool_name') or '未知工具',
                            'input': request.get('input') or {},
                            'tool_use_id': request.get('tool_use_id'),
                        }
                    )
            return

        if msg_type == 'system':
            subtype = message.get('subtype')
            if subtype == 'init':
                # SDK/print mode may emit system:init more than once across turns.
                # The initialize control_response already covers the user-visible
                # "connected" moment, so keep this internal to avoid repeated
                # "苏醒" status spam every time a new turn starts.
                return

            if subtype == 'task_started':
                payload = _task_progress_event(message)
                payload['status'] = 'started'
                payload['summary'] = message.get('prompt') or payload['summary']
                payload['task_type'] = message.get('task_type') or ''
                payload['workflow_name'] = message.get('workflow_name') or ''
                self._emit(payload)
                return

            if subtype == 'task_progress':
                self._emit(_task_progress_event(message))
                return

            if subtype == 'task_notification':
                self._emit(_task_progress_event(message))
                return

            if subtype == 'session_state_changed':
                self._emit(
                    {
                        'kind': 'session_state',
                        'state': message.get('state') or '',
                        'session_id': self._session_id,
                    }
                )
                return

            if subtype == 'status':
                self._emit(
                    {
                        'kind': 'sdk_status',
                        'status': message.get('status'),
                        'permission_mode': message.get('permissionMode'),
                        'session_id': self._session_id,
                    }
                )
                return

            if subtype == 'post_turn_summary':
                self._emit(
                    {
                        'kind': 'post_turn_summary',
                        'title': _extract_string(message.get('title')),
                        'description': _extract_string(message.get('description')),
                        'recent_action': _extract_string(message.get('recent_action')),
                        'needs_action': _extract_string(message.get('needs_action')),
                        'status_category': _extract_string(message.get('status_category')),
                        'status_detail': _extract_string(message.get('status_detail')),
                        'session_id': self._session_id,
                    }
                )
                return

            if subtype == 'local_command_output':
                self._emit(
                    {
                        'kind': 'assistant',
                        'text': _extract_string(message.get('content')),
                        'total_tokens': self._total_tokens,
                        'session_id': self._session_id,
                    }
                )
                return

            if subtype == 'hook_started':
                self._emit(
                    {
                        'kind': 'hook_status',
                        'hook_name': _extract_string(message.get('hook_name')),
                        'hook_event': _extract_string(message.get('hook_event')),
                        'phase': 'started',
                        'session_id': self._session_id,
                    }
                )
                return

            if subtype == 'hook_progress':
                self._emit(
                    {
                        'kind': 'hook_status',
                        'hook_name': _extract_string(message.get('hook_name')),
                        'hook_event': _extract_string(message.get('hook_event')),
                        'phase': 'progress',
                        'output': _extract_string(message.get('output')),
                        'stdout': _extract_string(message.get('stdout')),
                        'stderr': _extract_string(message.get('stderr')),
                        'session_id': self._session_id,
                    }
                )
                return

            if subtype == 'hook_response':
                self._emit(
                    {
                        'kind': 'hook_status',
                        'hook_name': _extract_string(message.get('hook_name')),
                        'hook_event': _extract_string(message.get('hook_event')),
                        'phase': 'response',
                        'outcome': _extract_string(message.get('outcome')),
                        'output': _extract_string(message.get('output')),
                        'stdout': _extract_string(message.get('stdout')),
                        'stderr': _extract_string(message.get('stderr')),
                        'session_id': self._session_id,
                    }
                )
                return

            self._emit(
                {
                    'kind': 'status',
                    'status': 'working',
                    'text': subtype or 'system',
                    'source': 'system',
                    'session_id': self._session_id,
                }
            )
            return

        if msg_type == 'assistant':
            message_payload = message.get('message') or {}
            content = message_payload.get('content')
            total_tokens = _usage_total_tokens(message_payload.get('usage'))
            input_tokens, output_tokens = _usage_input_output_tokens(
                message_payload.get('usage')
            )
            if isinstance(total_tokens, int):
                self._total_tokens = total_tokens
            for tool_use in _extract_tool_use_blocks(content):
                tool_name = tool_use.get('name') or tool_use.get('tool_name') or '未知工具'
                self._emit(
                    {
                        'kind': 'working',
                        'tool_name': tool_name,
                        'input': tool_use.get('input') or {},
                        'summary': _summarize_tool_input(
                            str(tool_name),
                            tool_use.get('input') or {},
                        ),
                        'total_tokens': self._total_tokens,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'session_id': self._session_id,
                    }
                )

            thinking_text = _safe_get_thinking_block(content)
            if thinking_text:
                self._emit(
                    {
                        'kind': 'thinking',
                        'text': thinking_text,
                        'total_tokens': self._total_tokens,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'session_id': self._session_id,
                    }
                )

            text = _safe_get_text_block(content)
            if text:
                self._last_assistant_text = text
                self._emit(
                    {
                        'kind': 'assistant',
                        'text': text,
                        'total_tokens': self._total_tokens,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'session_id': self._session_id,
                    }
                )
            return

        if msg_type == 'tool_progress':
            self._emit(
                {
                    'kind': 'tool_progress',
                    'tool_name': _extract_string(message.get('tool_name')),
                    'elapsed_time_seconds': message.get('elapsed_time_seconds'),
                    'task_id': _extract_string(message.get('task_id')),
                    'session_id': self._session_id,
                }
            )
            return

        if msg_type == 'tool_use_summary':
            self._emit(
                {
                    'kind': 'tool_use_summary',
                    'summary': _extract_string(message.get('summary')),
                    'session_id': self._session_id,
                }
            )
            return

        if msg_type == 'streamlined_text':
            text = _extract_string(message.get('text'))
            if text:
                self._last_assistant_text = text
                self._emit(
                    {
                        'kind': 'assistant',
                        'text': text,
                        'total_tokens': self._total_tokens,
                        'session_id': self._session_id,
                    }
                )
            return

        if msg_type == 'streamlined_tool_use_summary':
            self._emit(
                {
                    'kind': 'tool_use_summary',
                    'summary': _extract_string(message.get('tool_summary')),
                    'session_id': self._session_id,
                }
            )
            return

        if msg_type == 'result':
            subtype = message.get('subtype')
            total_tokens = _usage_total_tokens(message.get('usage'))
            input_tokens, output_tokens = _usage_input_output_tokens(message.get('usage'))
            if isinstance(total_tokens, int):
                self._total_tokens = total_tokens
            if subtype == 'success':
                result_text = message.get('result') or self._last_assistant_text or ''
                self._emit(
                    {
                        'kind': 'done',
                        'ok': True,
                        'text': result_text,
                        'total_tokens': self._total_tokens,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'session_id': self._session_id,
                    }
                )
            else:
                errors = message.get('errors') or []
                error_text = '\n'.join(str(item) for item in errors if item)
                if not error_text:
                    error_text = subtype or 'Claude Code 执行失败'
                self._emit(
                    {
                        'kind': 'done',
                        'ok': False,
                        'text': error_text,
                        'total_tokens': self._total_tokens,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'session_id': self._session_id,
                    }
                )

    def _update_session_id(self, message: dict):
        session_id = message.get('session_id')
        if isinstance(session_id, str) and session_id.strip():
            self._session_id = session_id.strip()

    def _emit(self, event: dict):
        try:
            self.on_event(event)
        except Exception:
            pass
