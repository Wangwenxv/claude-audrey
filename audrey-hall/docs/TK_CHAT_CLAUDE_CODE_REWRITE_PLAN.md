# Tk 聊天主界面对齐 Claude Code 的完全重构方案

本文面向后续 AI/开发者接手实现。目标不是继续修补当前半成品聊天页，而是把 Audrey Hall 的 Tk 聊天主界面重构为一套与根目录文档 `docs/08-claude-code-terminal-rendering.md` 对齐的结构化交互系统。

## 背景判断

当前 `audrey_hall/chat_window.py` 已有聊天窗口、气泡、权限卡片、状态栏、过程视图、Agent 工作台等实现，但整体仍是半成品：

- 事件处理不完整，很多 Claude Code 事件没有对应 UI 语义。
- 大量逻辑是在拦截 CLI 文本或做近似状态映射，不是基于 Claude Code 的结构化消息模型。
- `Agent 工作台` 把工作状态从主对话流中分裂出去，和 Claude Code 的“消息流即交互界面”不一致。
- `/model`、`/mode`、`/btw`、`/raw` 等本地命令是临时文本命令，不符合桌面聊天 UI 的成熟交互方式。
- 部分视觉只是模仿终端样式，没有和 Audrey Hall 的聊天气泡、卡片、桌宠气质形成稳定设计系统。

正确方向是：把 Claude Code 的核心逻辑抽象搬到 Tk 聊天页，而不是搬终端外观。

## 总目标

重构后，Tk 聊天页应符合以下模型：

```text
Claude Code stream-json / control messages
  -> ClaudeEventNormalizer
  -> ConversationEvent
  -> ChatTimelineStore
  -> Tk Timeline Renderer
  -> 用户气泡 / 奥黛丽气泡 / 状态卡 / 工具卡 / 权限卡 / 问题卡 / 结果卡
```

主界面最终效果：

- 用户和奥黛丽的主要对话仍然用聊天气泡。
- Claude Code 的思考、工具调用、权限请求、任务进度、结果摘要，作为结构化卡片插入气泡之间。
- 所有需要用户交互的节点都在主对话流内以可点击卡片完成，不弹模态、不抢焦点。
- `Agent 工作台` 被移除，主对话流本身就是 agent 状态界面。
- `TerminalViewWindow` 只保留为调试/原始流查看，不再承担日常主体验。
- 输入区能识别用户意图并给出结构化操作控件，例如模型选择下拉、模式选择下拉、旁路提问按钮，而不是要求用户记 `/model`、`/btw`。

## 对齐 Claude Code 的核心原则

参考 `docs/08-claude-code-terminal-rendering.md`，Claude Code 的体验不是 `console.log`，而是：

- API raw stream event 作为实时 UI 旁路。
- 稳定 `Message` 作为会话历史。
- thinking、text、tool_use、tool_result 按 content block 分开处理。
- 工具和权限是结构化 UI 组件，不是普通文本。
- 长过程通过 upsert 更新同一块 UI，而不是不断追加状态垃圾。

Tk 版本必须保留这个逻辑：

- 实时事件更新临时 TimelineItem。
- 完整消息替换或完成临时 TimelineItem。
- 工具卡片用 `tool_use_id` 或稳定 key 原地更新。
- 权限卡片响应后变为完成态，而不是直接消失。
- 正式聊天文本和工具过程视觉上区分。

## 目标架构

建议把当前 `chat_window.py` 中互相缠绕的逻辑拆成以下层级。可以先在同文件内实现，稳定后再拆文件。

### 1. ClaudeEventNormalizer

职责：把 `claude_agent.py` 发来的事件归一化成统一 `ConversationEvent`。

输入来源：

- Claude Code `stream-json` 输出。
- control request / response。
- session state。
- permission request。
- local UI command。

输出形态示例：

```python
{
    'type': 'assistant_text_delta',
    'turn_id': '...',
    'block_index': 0,
    'text': '增量文本',
}
```

或者：

```python
{
    'type': 'tool_use_started',
    'turn_id': '...',
    'tool_use_id': 'toolu_...',
    'tool_name': 'Read',
    'input': {'file_path': 'src/main.tsx'},
}
```

注意：不要在 normalizer 里直接创建 Tk widget。

### 2. ChatTimelineStore

职责：维护当前对话流里的可渲染 item。

核心能力：

- `append(item)`：追加稳定消息。
- `upsert(key, item)`：插入或更新临时/持续状态。
- `complete(key, patch)`：把临时项标记为完成。
- `remove(key)`：移除 tombstone 或被取消的临时项。
- `snapshot()`：返回 renderer 可消费的 item 列表。

它对应 Claude Code 里的 `messages + streamingText + streamingToolUses + streamingThinking`。

### 3. Tk Timeline Renderer

职责：根据 `TimelineItem` 创建或更新 Tk widget。

不要让事件分发函数直接到处 `tk.Label(...)`。所有 UI 创建应集中在 renderer：

- `render_user_message(item)`
- `render_assistant_message(item)`
- `render_status_card(item)`
- `render_thinking_card(item)`
- `render_tool_card(item)`
- `render_permission_card(item)`
- `render_question_card(item)`
- `render_result_card(item)`
- `render_summary_card(item)`
- `render_error_card(item)`

### 4. Command Intent Controller

职责：替代不成熟的 slash command 文本输入。

它需要检测用户输入和 UI 下拉选择，把 `/model`、`/mode`、`/btw` 等能力改成桌面控件。

## ConversationEvent 类型定义

以下是建议的最小事件集。

### Turn 事件

```python
turn_started
turn_completed
turn_failed
turn_interrupted
```

用途：开始/结束一次用户输入对应的 agent turn。

### 用户消息

```python
user_message_committed
```

字段：

- `text`
- `attachments`
- `timestamp`

渲染：右侧用户气泡。

### 助手文本

```python
assistant_text_started
assistant_text_delta
assistant_text_completed
```

渲染逻辑：

- `assistant_text_started` 创建临时 streaming bubble。
- `assistant_text_delta` 更新同一个 streaming bubble。
- `assistant_text_completed` 把临时 bubble 变成正式奥黛丽气泡。

如果当前 Claude Code 只提供完整 assistant text，没有 delta，也必须走 `assistant_text_completed`，不要追加状态行。

### Thinking

```python
thinking_started
thinking_delta
thinking_tokens
thinking_completed
```

渲染：thinking card。

规则：

- 默认显示“奥黛丽正在整理思路”。
- 只展示 token 数、阶段、简短摘要。
- 完整 thinking 内容默认折叠，点击展开。
- 如果未来涉及不可展示 reasoning，UI 应显示“已折叠思考”，不要展示原文。

### 工具调用

```python
tool_input_started
tool_input_delta
tool_use_started
tool_progress
tool_result
tool_completed
tool_failed
```

渲染：tool card + result card。

规则：

- `tool_input_started/input_delta` 对应 Claude Code 生成工具 JSON 的阶段。
- `tool_use_started` 表示工具调用已经结构化完成。
- `tool_progress` 更新同一张工具卡。
- `tool_result` 更新工具卡并可追加结果详情卡。
- 同一工具必须用同一 key 原地更新，不刷屏。

### 任务/子代理

```python
task_started
task_progress
task_completed
task_failed
```

渲染：task card。

字段：

- `task_id`
- `description`
- `summary`
- `last_tool_name`
- `workflow_progress`
- `usage`

### 权限请求

```python
permission_requested
permission_resolved
```

渲染：permission card。

字段：

- `request_id`
- `tool_use_id`
- `tool_name`
- `input`
- `mode`
- `risk_level`

交互：

- `允许`
- `总是允许`
- `拒绝`

点击后调用 `session.respond_permission(...)`，卡片变成完成态。

### 模型向用户提问

```python
question_requested
question_answered
question_declined
```

渲染：question card。

字段：

- `request_id`
- `questions`
- `multi_select`
- `options`

交互：

- 单选：整行选项卡可点击。
- 多选：整行选项卡 + checkbox。
- 提交后卡片变成“已回答”态，显示选择摘要。

### 系统状态

```python
status_update
session_ready
session_disconnected
context_compacting
post_turn_summary
error
```

渲染：status card / summary card / error card。

规则：

- 低价值状态只更新底栏，不插入 Timeline。
- 高价值状态才插入卡片：连接成功、压缩上下文、错误、需要用户动作、turn summary。

## TimelineItem 类型定义

最小可渲染 item：

```python
{
    'id': 'stable-id',
    'key': 'optional-upsert-key',
    'kind': 'assistant_message',
    'state': 'streaming|running|waiting|done|error',
    'title': '...',
    'text': '...',
    'detail': '...',
    'meta': {...},
    'actions': [...],
    'timestamp': 'HH:MM:SS',
}
```

建议 `kind` 枚举：

- `user_message`
- `assistant_message`
- `streaming_assistant_message`
- `status_card`
- `thinking_card`
- `tool_card`
- `tool_result_card`
- `task_card`
- `permission_card`
- `question_card`
- `summary_card`
- `error_card`

## 当前文件改造边界

### `audrey_hall/claude_agent.py`

当前它已经解析 `stream-json`，但仍偏向提取文本摘要。需要升级为结构化事件源。

必须做：

- 保留原始 `stdout_raw_line` 给 `TerminalViewWindow`。
- 对 `stream_event` 原样转发重要字段，而不是只在最终 assistant 消息时提取文本。
- 对 assistant content block 保留 block 类型：`text`、`thinking`、`redacted_thinking`、`tool_use`、`tool_result`。
- 对 `message_delta` 保留 usage、stop_reason。
- 对 `control_request:can_use_tool` 保留 `tool_use_id`、`tool_name`、`input`。
- 给每个事件补 `session_id`、`turn_id`、`request_id` 或可推导 key。

建议新增：

```python
def _emit_conversation_event(self, event_type: str, **payload):
    self._emit({'kind': 'conversation_event', 'event_type': event_type, **payload})
```

然后 `chat_window.py` 主要消费 `kind == 'conversation_event'`。

### `audrey_hall/chat_window.py`

当前文件职责太多，但可以分阶段迁移。

必须废弃或降级：

- `_create_agent_activity_panel()`：不再调用。
- `_set_agent_activity()`：先改为兼容空函数或仅更新底栏，最终删除。
- `_render_main_status()`：不应直接决定 UI 形态，应转成 `status_update` 事件。
- `_render_task_progress()`：改为 timeline upsert。
- `_render_tool_status_widget()`：改为 tool card upsert。

必须保留并重用：

- `_create_message_widget()`：用户/奥黛丽气泡基础。
- `_insert_markdown_text()` 和 Markdown tag 逻辑。
- `_show_permission_card()` 的业务响应逻辑，但视觉和插入机制要改。
- `_show_ask_user_question_card()` 的业务响应逻辑，但选项交互要改。
- `TerminalViewWindow` 的调试入口。

建议新增内部类或模块：

```python
class ChatTimelineStore:
    ...

class TimelineRenderer:
    ...

class CommandIntentController:
    ...
```

如果暂时不拆文件，也要用清晰区块放在 `chat_window.py`。

### `audrey_hall/ui/theme.py`

需要增加语义 token，避免卡片里继续写大量硬编码色值。

建议新增：

```python
'timeline': {
    'status_bg': '...',
    'status_border': '...',
    'thinking_bg': '...',
    'thinking_border': '...',
    'tool_bg': '...',
    'tool_border': '...',
    'permission_bg': '...',
    'permission_border': '...',
    'question_bg': '...',
    'question_border': '...',
    'result_bg': '...',
    'result_border': '...',
    'error_bg': '...',
    'error_border': '...',
}
```

## Tk 渲染方案

现有 transcript 用 `tk.Text.window_create` 嵌入 widget。可以继续使用，但要做到“稳定 key + 原地更新”。

### Renderer 状态

维护：

```python
self._timeline_widgets = {}  # item_id -> widget bundle
self._timeline_order = []    # item_id order
```

每个 widget bundle：

```python
{
    'container': frame,
    'kind': 'tool_card',
    'labels': {...},
    'buttons': {...},
    'item': item,
}
```

### 更新策略

- 新 item：`window_create` 插入。
- 已存在 item：只更新 label/button 状态，不 destroy 重建。
- 完成 item：更新 badge、颜色、按钮禁用。
- 删除 item：只用于 tombstone 或取消的临时 streaming 项。

### 防刷屏规则

- `thinking_tokens` 只更新同一 thinking card。
- 同一工具的 `tool_progress` 只更新同一 tool card。
- `session_state:running` 只更新底栏，不插卡。
- `session_state:idle` 如果 turn 已完成，不插卡。
- `context_compacting` 只插一张卡并更新为 done。
- `post_turn_summary` 每 turn 最多一张。

## 视觉系统

### 主对话气泡

继续保持：

- 用户右侧气泡。
- 奥黛丽左侧气泡。
- 头像、时间、Markdown 支持。

但注意：正式 assistant text 才能成为奥黛丽气泡。工具、状态、thinking 不要伪装成奥黛丽说话。

### 状态卡

用途：连接、压缩上下文、系统提醒、turn 摘要。

结构：

```text
小状态点  标题                BADGE
          详情文字
          可选 meta
```

### Thinking 卡

默认：

```text
◌ 奥黛丽正在整理思路       THINKING
  已思考 3.2k tok
```

展开后：

```text
已折叠/可查看的思考摘要...
```

如果内容属于不可展示 reasoning，只显示 `已折叠的思考`。

### 工具卡

结构：

```text
● Read                         RUNNING
  src/screens/REPL.tsx
  ↓ 12.4k tok · 14:32:08
```

按工具类型生成标题：

- `Read`：读取文件
- `Grep`：搜索内容
- `Glob`：匹配文件
- `Bash` / `PowerShell`：执行命令
- `Edit` / `Write`：修改文件
- `WebFetch` / `WebSearch`：访问网络
- `Task` / `Agent`：子代理任务

### 工具结果卡

默认折叠：

```text
工具结果 · 已返回 18 行      DONE
首行预览...
展开详情
```

展开后：

- stdout/stderr 用 monospace 样式。
- diff 使用 `diff_add`、`diff_del`、`diff_hunk` 标签。
- 超长结果只展示前 N 行，并提供“打开过程视图”。

### 权限卡

结构：

```text
需要你确认                    ACTION
Claude 想执行 Bash
命令：bun run version

[允许] [总是允许 Bash] [拒绝]
```

点击后变完成态：

```text
已允许 Bash                   DONE
命令：bun run version
```

### 问题卡

结构：

```text
奥黛丽想确认                  ACTION
你希望我怎么处理这个文件？

[  ] 只修复错误
[  ] 顺手整理格式
[  ] 暂停，先解释方案

[提交答案] [拒绝回答]
```

单选时点击选项卡即选中；多选时点击选项卡切换选中态。

## 输入区与命令改造

当前 `/model`、`/mode`、`/btw`、`/raw` 是不成熟的文本命令。目标是让用户可以自然输入，同时 UI 检测意图并提供结构化控件。

### 输入意图检测

新增 `CommandIntentController.detect(text)`，返回：

```python
{
    'intent': 'normal|model_select|mode_select|side_question|raw_toggle|local_help',
    'confidence': 0.0,
    'args': {...},
}
```

检测规则：

- 以 `/model` 开头 -> `model_select`。
- 以 `/mode` 开头 -> `mode_select`。
- 以 `/btw` 开头 -> `side_question`。
- 以 `/raw` 开头 -> `raw_toggle`。
- 输入中出现 `切换模型`、`换成 opus`、`用 sonnet` -> `model_select` 提示。
- 输入中出现 `计划模式`、`自动模式`、`允许改文件`、`全权限` -> `mode_select` 提示。
- 忙碌时普通输入 -> 默认识别为 `side_question`，显示“作为旁路提问发送？”

### 模型选择 UI

替代 `/model`：

- 输入 `/model` 或点击输入区旁的 `模型` 按钮，弹出 inline dropdown/popover。
- 选项：`默认`、`Sonnet`、`Opus`、`Haiku`、`Best`、`Sonnet 1M`、`Opus 1M`、`Opus Plan`。
- 选择后调用 `session.set_model(model)`。
- 对话流插入一张轻量状态卡：`模型已切换：Opus`。

### 模式选择 UI

替代 `/mode`：

- 输入 `/mode` 或点击 `模式` 按钮，显示 dropdown。
- 选项：
  - `默认陪伴`
  - `允许改动`
  - `自动判断`
  - `计划模式`
  - `全部权限`，若当前配置不支持则 disabled 并说明原因。
- 选择后调用 `session.set_permission_mode(mode)`。
- 成功后插入状态卡；失败插入 error card。

### 旁路提问 UI

替代 `/btw`：

- 当主 turn 忙碌时，发送按钮文案可以是 `旁路提问`。
- 普通输入不再直接塞 `/btw`，而是弹出 inline confirmation card：

```text
当前奥黛丽还在工作。要把这句话作为旁路问题发送吗？
[发送旁路问题] [排队到下一轮] [取消]
```

- 如果用户主动输入 `/btw xxx`，直接创建旁路问题卡并调用 `session.send_side_question(question)`。

### Raw / 过程视图

替代 `/raw`：

- `打开过程视图` 按钮旁提供 `原始 JSON` 开关。
- `/raw` 仍可兼容，但只作为快捷方式，不再是主路径。

### Slash 命令兼容策略

短期保留文本命令，但转为 UI 行为：

- `/model`：打开模型下拉，不向 Claude 发送。
- `/mode`：打开模式下拉，不向 Claude 发送。
- `/btw text`：发送旁路问题。
- `/raw`：切换过程视图 raw 模式。
- 未知 slash：显示 command help card，而不是 warn 气泡。

## `chat_window.py` 迁移步骤

### 阶段 1：建立新模型，不破坏旧 UI

1. 新增 `ChatTimelineStore`。
2. 新增 `TimelineRenderer`，先支持：
   - user message
   - assistant message
   - status card
   - permission card
3. `_handle_event()` 中先把少量事件转成 timeline item，旧路径保留。

验收：正常发送、接收、权限请求仍可用。

### 阶段 2：接管核心事件

1. `assistant` 走 `assistant_message`。
2. `thinking` / `thinking_tokens` 走 `thinking_card` upsert。
3. `working` 走 `tool_card` upsert。
4. `tool_use_summary` 走 `tool_result_card`。
5. `task_progress` 走 `task_card` upsert。

验收：不打开过程视图也能看懂 Claude 正在做什么。

### 阶段 3：废弃 Agent 工作台

1. 移除 `_create_agent_activity_panel(content_frame)` 调用。
2. `_set_agent_activity()` 改为兼容 no-op 或只更新底栏。
3. 删除 `_agent_activity_*` 的视觉依赖。

验收：窗口中没有 `Agent 工作台`，但状态不丢失。

### 阶段 4：重做用户交互卡

1. 重做 `_show_permission_card()` 为 renderer 的 `permission_card`。
2. 重做 `_show_ask_user_question_card()` 为 renderer 的 `question_card`。
3. 点击后卡片变完成态。

验收：权限/问题都在主流中点击完成。

### 阶段 5：命令输入改造

1. 新增输入区小工具栏：`模型`、`模式`、`过程`。
2. 输入 `/model` 不发送文本，打开模型选择。
3. 输入 `/mode` 不发送文本，打开模式选择。
4. 忙碌时发送普通文本，提示旁路/排队/取消。
5. 未知 slash 显示帮助卡。

验收：用户无需记 slash 命令也能完成模型/模式/旁路操作。

### 阶段 6：清理旧路径

1. 删除旧 `_render_tool_status_widget()` 或只保留兼容转发。
2. 删除旧 `_render_task_widget()` 的工作台逻辑。
3. 清理未使用的 `_tool_status_widget`、`_task_widgets`、`_agent_activity_*`。
4. 保留 `TerminalViewWindow` 原始输出调试。

验收：事件来源清晰，UI 路径统一。

## `claude_agent.py` 迁移步骤

### 当前问题

当前 `claude_agent.py` 主要在 `msg_type == 'assistant'` 时提取：

- text -> `kind: assistant`
- thinking -> `kind: thinking`
- tool_use -> `kind: working`
- tool_result -> `kind: tool_use_summary`

这会丢失 Claude Code 的 stream_event 细节，导致 UI 无法完全模拟 Claude Code 的实时状态。

### 改造要求

1. 识别并转发 `msg_type == 'stream_event'`。
2. 对 `event.type` 做细分：
   - `message_start`
   - `content_block_start`
   - `content_block_delta`
   - `content_block_stop`
   - `message_delta`
   - `message_stop`
3. 在 normalizer 里将其转为 `ConversationEvent`。
4. 完整 assistant message 仍然保留，作为稳定历史消息。

### 事件映射表

| Claude Code message | ConversationEvent | Timeline 行为 |
|---|---|---|
| `stream_event/message_start` | `turn_request_started` | 底栏/状态卡进入 requesting |
| `content_block_start:text` | `assistant_text_started` | 创建 streaming bubble |
| `content_block_delta:text_delta` | `assistant_text_delta` | 更新 streaming bubble |
| `content_block_stop:text` | `assistant_text_completed` | 转正式奥黛丽气泡 |
| `content_block_start:thinking` | `thinking_started` | 创建 thinking card |
| `content_block_delta:thinking_delta` | `thinking_delta` | 更新 thinking card |
| `content_block_start:tool_use` | `tool_input_started` | 创建 tool card |
| `content_block_delta:input_json_delta` | `tool_input_delta` | 更新工具输入摘要 |
| `assistant/tool_use` | `tool_use_started` | 工具卡进入 waiting/running |
| `control_request/can_use_tool` | `permission_requested` | 插入 permission card |
| `tool_progress` | `tool_progress` | 更新 tool card |
| `tool_use_summary` | `tool_result` | 插入/更新 result card |
| `message_delta` | `turn_usage_updated` | 写 usage/stop_reason |
| `result:success` | `turn_completed` | 完成当前 turn |
| `result:error` | `turn_failed` | error card |

## 降噪规则

不要显示这些低价值事件为卡片：

- `system:init`
- `system:running`
- 高频重复 `session_state:running`
- 重复的 `thinking_tokens`，只更新已有 card。
- 重复状态文本。

必须显示这些事件：

- 用户输入。
- assistant text。
- 权限请求。
- 模型向用户提问。
- 工具开始、关键进度、完成/失败。
- 子任务开始、完成/失败。
- 压缩上下文。
- 模式/模型切换成功或失败。
- turn 失败。

## 验收标准

### 功能验收

- 用户可以正常发送文本和图片。
- 模型回复显示为奥黛丽气泡。
- thinking 显示为可折叠卡，不刷屏。
- Read/Grep/Bash/Edit/Write/Task 等工具显示为结构化工具卡。
- 权限请求以内嵌卡片完成，按钮可点击。
- AskUserQuestion 以内嵌问题卡完成，选项可点击。
- `/model` 打开模型下拉，不作为文本发送给 Claude。
- `/mode` 打开模式下拉，不作为文本发送给 Claude。
- 忙碌时普通输入触发旁路/排队确认，而不是直接失败。
- 过程视图仍可查看原始流。

### 视觉验收

- 主对话只有用户/奥黛丽气泡和结构化卡片，不出现 `Agent 工作台`。
- 卡片不会像日志一样连续刷屏。
- 权限卡、问题卡、工具卡的按钮状态清晰。
- 长工具结果默认折叠。
- 小窗口和高 DPI 下输入区不被挤掉。
- 卡片颜色与现有 Audrey Hall 主题一致，不使用随机硬编码色。

### 架构验收

- `chat_window.py` 的 `_handle_event()` 不再直接塞大量 UI widget，而是转事件到 timeline。
- 主 UI 不依赖 `terminal_line` 或 raw stdout 文本理解状态。
- `claude_agent.py` 保留 Claude Code 结构化事件，不只提取摘要。
- Slash command 兼容层和 UI 控件层分离。

## 推荐实现顺序给 AI

如果后续由 AI 接手实现，按这个顺序执行：

1. 先读 `docs/08-claude-code-terminal-rendering.md`。
2. 再读本文。
3. 读 `audrey_hall/claude_agent.py` 的 `_handle_stdout_message()`。
4. 读 `audrey_hall/chat_window.py` 的 `_handle_event()`、`_create_message_widget()`、`_show_permission_card()`。
5. 先实现 `ConversationEvent` normalizer，不动视觉。
6. 再实现 `ChatTimelineStore`。
7. 再把 `thinking/working/task_progress` 接入 timeline card。
8. 再移除 `Agent 工作台`。
9. 最后重做输入命令 UI。

不要一开始就改颜色和动画。先让事件模型正确，再做视觉打磨。

## 非目标

本次重构不要求：

- 把 Tk 改成 Web/WPF。
- 做真正 PTY 终端。
- 完全复制 Claude Code 的终端外观。
- 展示不可展示的模型 thinking 原文。
- 删除过程视图。

本次重构要求的是逻辑效果对齐：结构化事件、实时更新、稳定历史、工具卡片、权限卡片、主对话流统一。
