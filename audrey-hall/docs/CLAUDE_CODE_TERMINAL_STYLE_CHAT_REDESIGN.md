# Audrey Hall 主对话框 Claude Code 终端风格改造

## 目标

把 `与奥黛丽聊聊` 的主对话框从“聊天气泡 + 装饰卡片状态”改成更接近 Claude Code 的终端式 transcript。

保留：

- 普通用户/奥黛丽聊天气泡、头像、时间。
- 现有 Claude Code 进程桥接、权限响应、图片发送、历史会话。
- 旁路 `过程视图` 作为原始 stdout/stderr/JSON 流调试窗口。

舍弃：

- 主对话框内状态卡片的贵族装饰感、圆点徽章和大面积彩色卡片。
- 模糊的“正在处理”式文案。
- 工具、思考、结果之间不清晰的视觉层级。

## Claude Code 参考模型

参考 `docs/08-claude-code-terminal-rendering.md` 后，迁移的重点不是黑底终端，而是 Claude Code 的交互模型：

```text
stream_event
  -> conversation_event
  -> 主窗口状态机
  -> 结构化 transcript block
  -> Tk Text/window_create 增量更新
```

Claude Code 的关键设计是“双轨流”：

- 实时轨：`stream_event` 立刻更新 requesting、thinking、responding、tool-input、tool-use。
- 稳定轨：完整 content block 结束后成为 assistant/tool/result 的稳定历史。

Audrey Hall 目前已经在 `audrey_hall/claude_agent.py` 中把 Claude Code 的 `stream_event` 转换为 `conversation_event`，因此本次改造不重写通信层，只改主窗口渲染层。

## 已改造范围

### 1. TimelineRenderer 终端化

`audrey_hall/chat_window.py` 中的 `TimelineRenderer` 仍负责主对话框状态块渲染，但视觉变为：

- 左侧固定终端前缀：`•`、`*`、`>`、`⎿`、`?`、`✓`、`!`。
- 标题使用 `Consolas` 粗体，模拟 Claude Code 中结构化行标题。
- 详情使用 `Consolas` 常规体，强调可 inspect 的过程信息。
- 背景统一为接近 transcript 面板的浅色，只用细边框表达状态类型。
- 徽标弱化为右侧小写状态文本，不再作为主视觉。

状态前缀规则：

| kind/state | prefix | 含义 |
|---|---:|---|
| `status_card` | `•` | 普通系统状态 |
| `thinking_card` | `*` | thinking 阶段 |
| `tool_card` / `task_card` | `>` | 工具或子代理步骤 |
| `tool_result_card` | `⎿` | 工具结果输出 |
| `permission_card` / `question_card` | `?` | 需要用户参与 |
| `summary_card` / done | `✓` | 阶段完成 |
| error | `!` | 错误或中断 |

### 2. conversation_event 文案终端化

`_handle_conversation_event()` 现在按 Claude Code 阶段显示：

- `turn_request_started` -> `requesting`
- `assistant_text_started` -> `responding`
- `thinking_*` -> `thinking`
- `tool_input_*` -> `tool-input: <tool>`
- `tool_use_started/tool_progress` -> `tool-use: <tool>`
- `tool_result` -> `tool-result: <n> lines`
- `turn_completed` -> `turn-complete`
- `turn_failed` -> `turn-failed`

这样用户看到的是“模型现在处在哪个协议阶段”，而不是装饰性的等待提示。

### 3. 工具输入流式累积

新增 `_terminal_tool_input_texts`，用于按工具 block key 累积 `tool_input_delta.partial_json`。

效果：

- tool input 还没完整生成时，也能看到正在拼接的 JSON 片段摘要。
- `tool_input_started` 与 `tool_input_delta` 统一更新同一个终端块。
- 新一轮对话开始时由 `_reset_turn_state()` 清空，避免跨轮污染。

### 4. 权限请求终端化

权限请求仍保留按钮，因为这是必须交互项，但外观从“对话卡片”改为终端权限块：

- 标题：`permission-request: <tool>`
- 正文：工具输入 JSON 摘要
- meta：说明选择会回写给 Claude Code
- 完成后标题：`permission-resolved`

### 5. 防刷屏更新机制

Claude Code 在终端中不是不断 `console.log`，而是用 Ink 维护上一帧和下一帧，计算 diff 后只把变化补丁写入 stdout。

Tk 主窗口采用等价策略：

- 每个流式 block 使用稳定 key，后续事件只更新已有 widget。
- assistant text delta 不逐 token 立即重绘，而是以 `STREAM_RENDER_INTERVAL_MS = 33ms` 合并成小帧更新。
- 完成态到达时取消未执行的延迟帧，立即写入最终文本，避免旧 pending 文本覆盖最终状态。
- tool input delta 按 `turn_id + block_index` 绑定到同一个工具块，即使 delta 事件不携带 `tool_use_id` 也不会生成新行。
- card/status 更新会比较上一轮 title、badge、detail、meta，内容未变时不重新 config widget。

这使主对话区接近 Claude Code 的“局部补丁”体验：流式输出在原地增长，工具输入在原行变化，滚动只在用户本来贴底时跟随。

### 6. Thought 摘要行

Claude Code 会把 thinking 和工具活动折叠成类似下面的单行摘要：

```text
Thought for 3s, read 1 file (ctrl+o to expand)
Thought for 6s, searched for 1 pattern, read 1 file (ctrl+o to expand)
```

Audrey Hall 主对话框采用同类机制：

- 每轮 `turn_request_started` 创建一个 `thought:<turn_id>` 摘要块。
- `thinking_*` 事件只更新这条摘要行，不再额外生成单独 thinking 卡片。
- `tool_use_started` 按工具名累计类别计数：search、read、write、command、agent task、other。
- `task_progress` 使用 task id / tool use id 去重，避免进度事件重复累计。
- `turn_completed` / `turn_failed` 把摘要从 `Thinking for Ns` 定格为 `Thought for Ns`。
- Audrey Hall 没有 Claude Code 的 `ctrl+o` transcript 快捷键，因此提示使用 `过程视图展开`。

这一层负责“用户可读的活动概览”；完整 stdout、stderr、JSON、长工具输出仍在 `过程视图` 中查看。

### 7. Ink 组件复用边界

Claude Code 的主屏组件不能直接嵌入 Audrey Hall 主窗口：

- Claude Code 是 TypeScript + React/Ink + Yoga layout，最终输出 ANSI diff 到 stdout。
- Audrey Hall 是 Python + Tkinter，主对话框是 `Text.window_create()` 嵌入 Tk widget。
- Ink 的 `<Messages />`、`AssistantToolUseMessage`、`CollapsedReadSearchContent` 等组件依赖 React reconciler、Ink context、terminal frame diff、主题和快捷键系统，不能作为 Tk widget 直接挂载。

因此实际复用方式是“复用组件语义，而不是复用组件实例”：

- 主屏只保留一条 `thought:<turn_id>` 摘要行，显示 `Thought for Ns, read/searched...`。
- 主屏只保留一条 `activity:<turn_id>` 当前活动行，工具输入、工具执行、工具结果、子任务进度都原地更新它。
- 详细工具 JSON、长结果、原始 stdout/stderr 留在 `过程视图`，等价于 Claude Code 的 transcript / `ctrl+o` 展开层。
- 这样主屏与 Claude Code 一样避免工具调用刷屏，同时用户仍能在需要时查看完整过程。

### 8. 终端指令选择器

底部按钮台不再放 `模型`、`模式` 两个按钮。入口改为终端指令：

- 输入 `/model`：主 transcript 出现 `/model` 终端选项块，可选择 `default`、`sonnet`、`opus`、`haiku` 等模型。
- 输入 `/mode`：主 transcript 出现 `/mode` 终端选项块，可选择 `default`、`acceptEdits`、`bypassPermissions`、`plan` 对应模式。
- 输入 `/model <name>` 或 `/mode <name>`：仍直接执行切换，不展示选项块。

这样控制入口更接近 Claude Code 的命令式交互，同时减少按钮台噪声。

## 当前保留项

普通聊天气泡继续保留，因为用户明确允许“聊天气泡可以延续”。这也符合产品目标：

- 普通对话仍有奥黛丽角色感。
- 工作状态改成可信、可检查的 agent console。
- 头像和时间继续帮助用户辨认聊天节奏。

## 后续建议

如果继续深化，可以按以下顺序做：

1. 把普通 assistant 流式气泡改成 `● + StreamingMarkdown` 风格，但最终文本仍可保留头像时间。
2. 把 model/mode/side-question/quick-choice 的内联卡片也统一成终端块。
3. 给 `Text` 标签增加更完整的 Markdown/代码块/diff 高亮。
4. 为长工具结果增加主界面折叠/展开，而不是只提示打开过程视图。
5. 把 `TerminalViewWindow` 的样式与主 transcript 合并成同一套 token，避免两个终端视图视觉不一致。

## 验证建议

最低验证：

```bash
python -m compileall main.py audrey_hall
```

手动验证：

1. 打开 `与奥黛丽聊聊`。
2. 连接 `奥黛丽agent` 或 `claude agent`。
3. 发送普通问题，确认 `requesting`、`responding` 出现。
4. 发送需要读文件/搜索/执行命令的问题，确认 `tool-input`、`tool-use`、`tool-result` 出现。
5. 触发权限请求，确认终端权限块和按钮可用。
6. 打开 `过程视图`，确认原始输出仍保留。
