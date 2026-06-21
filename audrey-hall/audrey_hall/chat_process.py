import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import gettempdir
from typing import Callable


PROCESS_LOG_PATH = Path(gettempdir()) / 'audrey-chat-process.log'


class ChatProcessManager:
    """Manage the WPF chat child process over stdio JSON Lines."""

    def __init__(self, root, on_command: Callable[[dict], None]):
        self.root = root
        self.on_command = on_command
        self.process = None
        self._writer_lock = threading.Lock()
        self._closed = False

    def _log(self, message: str):
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            PROCESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with PROCESS_LOG_PATH.open('a', encoding='utf-8') as handle:
                handle.write(f'[{timestamp}] {message}\n')
        except Exception:
            pass

    def show(self) -> bool:
        self._log('show requested')
        if not self._ensure_started():
            self._log('show failed: process not started')
            return False
        self.send({'type': 'chat.show'})
        self._log('chat.show sent')
        return True

    def preheat(self) -> bool:
        self._log('preheat requested')
        return self._ensure_started(hidden=True)

    def close(self):
        self._closed = True
        self._log('close requested')
        self.send({'type': 'chat.close'})
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.process = None

    def send(self, payload: dict):
        if self.process is None or self.process.stdin is None:
            self._log(f'send skipped: process unavailable type={payload.get("type")}')
            return
        try:
            line = json.dumps(payload, ensure_ascii=False)
            with self._writer_lock:
                self.process.stdin.write(line + '\n')
                self.process.stdin.flush()
            self._log(f'sent type={payload.get("type")}')
        except Exception:
            self._log(f'send failed type={payload.get("type")}')
            pass

    def _ensure_started(self, *, hidden: bool = False) -> bool:
        if self.process is not None and self.process.poll() is None:
            self._log('process already running')
            return True
        if self.process is not None and self.process.poll() is not None:
            self._log(f'clearing exited process code={self.process.poll()}')
            self.process = None

        exe_path = self._find_chat_exe()
        if exe_path is None:
            self._log('chat exe not found')
            return False
        self._log(f'chat exe found: {exe_path}')

        try:
            command = [str(exe_path)]
            if hidden:
                command.append('--hidden')
            self._log(f'starting process: {command}')
            self.process = subprocess.Popen(
                command,
                cwd=str(exe_path.parent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception:
            self.process = None
            self._log('process start failed')
            return False

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._log('process started')
        return True

    def _find_chat_exe(self) -> Path | None:
        candidates = []
        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).resolve().parent
            candidates.extend(
                [
                    base / 'Audrey.Chat.exe',
                    base / 'audrey-chat' / 'Audrey.Chat.exe',
                ]
            )

        repo_root = Path(__file__).resolve().parents[2]
        chat_root = repo_root / 'audrey-chat' / 'src' / 'Audrey.Chat' / 'bin'
        candidates.extend(
            [
                chat_root / 'Release' / 'net8.0-windows' / 'Audrey.Chat.exe',
                chat_root / 'Debug' / 'net8.0-windows' / 'Audrey.Chat.exe',
            ]
        )

        env_path = os.environ.get('AUDREY_CHAT_EXE')
        if env_path:
            candidates.insert(0, Path(env_path))

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except Exception:
                pass
        return None

    def _read_stdout(self):
        process = self.process
        if process is None or process.stdout is None:
            self._log('stdout reader aborted: stdout unavailable')
            return
        try:
            for line in process.stdout:
                if self._closed:
                    break
                self._log(f'stdout: {line.strip()}')
                try:
                    command = json.loads(line)
                except json.JSONDecodeError:
                    self._log('stdout json decode failed')
                    continue
                if not isinstance(command, dict):
                    continue
                self._schedule_command(command)
        except Exception:
            self._log('stdout reader failed')
            pass

    def _read_stderr(self):
        process = self.process
        if process is None or process.stderr is None:
            self._log('stderr reader aborted: stderr unavailable')
            return
        try:
            for line in process.stderr:
                if self._closed:
                    break
                self._log(f'stderr: {line.strip()}')
        except Exception:
            self._log('stderr reader failed')
            pass

    def _schedule_command(self, command: dict):
        try:
            self._log(f'schedule command type={command.get("type")}')
            self.root.after(0, lambda: self.on_command(command))
        except Exception:
            self._log('schedule command failed')
            pass
