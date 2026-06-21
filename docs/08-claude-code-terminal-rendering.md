# Claude Code 模型流与终端交互渲染解构

本文只分析本仓库 `src/` 内的 Claude Code 主体源码，不分析 `audrey-chat/` 和 `audrey-hall/`。

核心结论：Claude Code 的终端效果不是把模型输出简单 `console.log` 到屏幕，而是一条“API 流式事件 -> 内部消息模型 -> React/Ink 组件树 -> 终端差分补丁”的管线。模型的 token、thinking、tool_use、tool_result、进度、权限弹窗、输入框、滚动区域都被建模成 React 组件，由自带的 Ink 渲染器计算终端帧差异后写入 stdout。

## 入口路径

交互模式的主链路：

```text
package.json scripts
  -> src/dev-entry.ts
  -> src/entrypoints/cli.tsx
  -> src/main.tsx
  -> launchRepl(...)
  -> <App><REPL /></App>
```

关键文件：

- `package.json`：`bun run dev` 和 `bun run start` 都进入 `src/dev-entry.ts`。
- `src/dev-entry.ts`：恢复版开发入口，缺失导入为 0 时转入 `src/entrypoints/cli.tsx`。
- `src/entrypoints/cli.tsx`：轻量 CLI bootstrap，处理 `--version` 等快路径，普通交互路径动态导入 `src/main.tsx`。
- `src/main.tsx`：做配置、鉴权、工具、MCP、恢复会话、初始化状态，最终创建 Ink root 并调用 `launchRepl()`。
- `src/replLauncher.tsx`：把 `<REPL />` 包进 `<App />`，再交给 `renderAndRun()`。
- `src/interactiveHelpers.tsx`：`renderAndRun()` 调用 `root.render(element)`，然后等待 Ink app 退出。

## 总体数据流

一次用户提交到模型响应显示出来，大致是：

```text
用户在 PromptInput 输入
  -> REPL.onSubmit / handlePromptSubmit
  -> REPL.onQuery(...)
  -> REPL.onQueryImpl(...)
  -> query({ messages, systemPrompt, toolUseContext, ... })
  -> deps.callModel = queryModelWithStreaming(...)
  -> Anthropic SDK beta.messages.create({ stream: true }).withResponse()
  -> for await 原始 SSE 事件
  -> 一边 yield stream_event 给 UI 做实时状态
  -> 一边在 content_block_stop 时 yield AssistantMessage
  -> REPL.onQueryEvent(event)
  -> handleMessageFromStream(event, ...)
  -> setMessages / setStreamingText / setStreamingToolUses / setStreamMode
  -> <Messages /> 根据状态重新渲染
  -> <Message /> 分发到 AssistantTextMessage / AssistantToolUseMessage / ...
  -> Ink reconciler 生成终端 frame
  -> log-update 计算 frame diff
  -> writeDiffToTerminal(stdout)
```

这条链路里最重要的设计是“双轨流”：

- `stream_event` 轨：保留 API 原始流式事件，主要用于即时反馈，比如 spinner 状态、正在输出的文本、正在拼 JSON 的工具输入、thinking 状态、TTFT 指标。
- `Message` 轨：等一个 content block 完成后，把它包装成内部 `AssistantMessage`、`UserMessage`、`SystemMessage` 等稳定消息，进入会话历史、转录日志和正式 UI 列表。

因此用户看到的是实时的，但历史里保存的是结构化、稳定的消息。

## 交互层：REPL 如何启动查询

`src/screens/REPL.tsx` 是交互模式的中心组件。它同时负责：

- 保存消息列表 `messages`。
- 保存流式 UI 状态，比如 `streamingText`、`streamingToolUses`、`streamingThinking`、`streamMode`。
- 构建 `toolUseContext`，里面包含工具列表、MCP 客户端、权限状态、读取文件缓存、通知、`setMessages`、`setAppState` 等。
- 在用户提交后调用 `query()`。
- 把 `query()` 产出的每个事件交给 `handleMessageFromStream()`。

关键片段位于 `src/screens/REPL.tsx`：

```text
for await (const event of query({
  messages: messagesIncludingNewMessages,
  systemPrompt,
  userContext,
  systemContext,
  canUseTool,
  toolUseContext,
  querySource: getQuerySourceForREPL()
})) {
  onQueryEvent(event)
}
```

这里的 `query()` 不是单次 API 请求包装，而是完整 agent turn loop：它会处理上下文压缩、模型 fallback、工具调用、工具结果、stop hooks、继续请求等。也就是说用户的一次输入可能触发多轮“模型 -> 工具 -> 模型”的内部循环，但 UI 侧只看到一个持续更新的事件流。

## query 层：agent turn 的状态机

`src/query.ts` 暴露 `query()`，实际工作在 `queryLoop()`。它接收：

- `messages`：当前会话历史和本次用户新消息。
- `systemPrompt`、`userContext`、`systemContext`：最终发给模型的上下文。
- `canUseTool`：权限检查函数。
- `toolUseContext`：工具运行、UI 更新、文件缓存、AppState 等上下文。
- `querySource`：区分 REPL、SDK、compact、subagent 等请求来源。

`query()` 的生产依赖来自 `src/query/deps.ts`：

```text
productionDeps().callModel = queryModelWithStreaming
```

核心流式调用位于 `src/query.ts`：

```text
for await (const message of deps.callModel({
  messages: prependUserContext(messagesForQuery, userContext),
  systemPrompt: fullSystemPrompt,
  thinkingConfig: toolUseContext.options.thinkingConfig,
  tools: toolUseContext.options.tools,
  signal: toolUseContext.abortController.signal,
  options: { model, fallbackModel, querySource, ... }
})) {
  yield message
  if (message.type === 'assistant') {
    assistantMessages.push(message)
    if (message contains tool_use) needsFollowUp = true
  }
}
```

这里 `query()` 做了几件很关键的事情：

- 把历史消息整理成 API 可接受格式，必要时插入用户上下文。
- 根据权限模式、模型、上下文长度决定实际模型和输出 token 限制。
- 监听模型返回的 `tool_use` block，如果出现工具调用就进入工具执行路径。
- 如果启用 streaming tool execution，工具可以在模型流还没完全结束时开始执行。
- 当工具结果产生后，作为 `UserMessage` / `tool_result` 注入下一轮模型请求。
- 遇到 fallback、prompt too long、max output tokens、abort 等情况时产出系统消息或错误消息，UI 一样按消息渲染。

## API 层：如何接收模型信息

真正和 Anthropic SDK 交互的是 `src/services/api/claude.ts`。

外部入口：

```text
queryModelWithStreaming(...)
  -> withStreamingVCR(...)
  -> queryModel(...)
```

`queryModel()` 会构造 `BetaMessageStreamParams`：

- `model`：规范化后的模型名。
- `messages`：经过 `normalizeMessagesForAPI()`、cache breakpoint、media 限制等处理后的消息。
- `system`：系统提示词。
- `tools`：从 Claude Code 工具定义转换出的 API tool schema。
- `tool_choice`：工具选择策略。
- `max_tokens`、`thinking`、`temperature`、`betas`、`metadata`、`output_config` 等。

发送请求的位置：

```text
const result = await anthropic.beta.messages
  .create({ ...params, stream: true }, { signal, headers })
  .withResponse()

stream = result.data
```

这里使用的是 Anthropic SDK 的 raw stream：`Stream<BetaRawMessageStreamEvent>`。源码注释说明它刻意不用 `BetaMessageStream`，因为后者会对 `input_json_delta` 做 O(n²) 的 partial JSON 解析，而 Claude Code 自己累积工具输入 JSON。

### API 原始事件

`queryModel()` 主要处理这些流式事件：

- `message_start`：拿到 message 元数据、初始 usage、计算 TTFT。
- `content_block_start`：根据 block 类型初始化 `contentBlocks[index]`。
- `content_block_delta`：把 token 增量追加到对应 block。
- `content_block_stop`：一个 block 完成，生成并 yield 一个内部 `AssistantMessage`。
- `message_delta`：拿到最终 usage、stop_reason、成本统计；把最终 usage/stop_reason 写回最近的 assistant message。
- `message_stop`：请求结束。

### content block 如何被累积

`content_block_start` 时会创建空 block：

- `text` block 初始化为 `{ text: '' }`。
- `tool_use` block 初始化为 `{ input: '' }`，后续拼接 `input_json_delta.partial_json`。
- `thinking` block 初始化为 `{ thinking: '', signature: '' }`。

`content_block_delta` 时按 delta 类型追加：

- `text_delta`：追加到 `contentBlock.text`。
- `input_json_delta`：追加到 `contentBlock.input`。
- `thinking_delta`：追加到 `contentBlock.thinking`。
- `signature_delta`：写入 thinking signature，不计入 UI 的 token 输出长度。

当 `content_block_stop` 到来时，源码构造：

```text
const m: AssistantMessage = {
  message: {
    ...partialMessage,
    content: normalizeContentFromAPI([contentBlock], tools, options.agentId),
  },
  requestId,
  type: 'assistant',
  uuid: randomUUID(),
  timestamp: new Date().toISOString(),
}

yield m
```

注意：这里是“每个 content block 一个 `AssistantMessage`”，不是每次 API 响应一个完整 assistant message。这样 UI 可以把文本、thinking、tool_use 分块、分行、分组件显示，也能让工具调用尽早出现在界面里。

### stream_event 旁路

在处理每个 raw event 后，`queryModel()` 还会 yield：

```text
yield {
  type: 'stream_event',
  event: part,
  ...(part.type === 'message_start' ? { ttftMs } : undefined),
}
```

这就是 UI 实时感的来源。即使一个完整 `AssistantMessage` 要等 `content_block_stop`，UI 仍然可以通过 `content_block_delta` 立即更新正在流动的文本和 spinner 状态。

## 事件到 UI 状态：handleMessageFromStream

`src/utils/messages.ts` 的 `handleMessageFromStream()` 是模型事件和 REPL UI 状态之间的适配器。

它对非 `stream_event` 的处理很直接：

- `tombstone`：删除已经显示的孤儿消息。
- `tool_use_summary`：SDK-only，交互 UI 忽略。
- 完整 `assistant` / `user` / `system` / `attachment`：调用 `onMessage(message)`，也就是 REPL 里的 `setMessages(old => [...old, message])`。
- 完整 assistant thinking block：更新 `streamingThinking`，方便 transcript 模式显示完整 thinking。
- 收到完整消息前会清空 `streamingText`，避免“流式预览”和“最终消息”重复显示。

它对 `stream_event` 的处理是即时 UI 状态更新：

- `stream_request_start`：`streamMode = 'requesting'`。
- `message_start`：记录 TTFT。
- `message_stop`：清空 `streamingToolUses`，`streamMode = 'tool-use'`。
- `content_block_start`：按 block 类型设置 spinner 模式。
- `content_block_start:text`：`streamMode = 'responding'`。
- `content_block_start:thinking`：`streamMode = 'thinking'`。
- `content_block_start:tool_use`：`streamMode = 'tool-input'`，并创建一个 `StreamingToolUse`。
- `content_block_delta:text_delta`：追加到 `streamingText`。
- `content_block_delta:input_json_delta`：追加到对应 `StreamingToolUse.unparsedToolInput`。
- `content_block_delta:thinking_delta`：只更新输出长度，不默认在主屏显示 thinking。
- `signature_delta`：忽略，不计入输出长度。

这解释了为什么 Claude Code 能做到：

- 模型正文像打字一样出现。
- 工具调用在 JSON 输入还没完整时就能显示“正在准备工具输入”。
- spinner 文案能从 requesting、thinking、responding、tool-input、tool-use 之间切换。
- 最终完成后不会留下重复的半成品文本。

## 消息模型：终端显示的中间表示

`src/types/message.js` 中定义的消息类型被大量使用，核心可以理解为：

- `UserMessage`：用户输入、工具结果、bash 输出、命令输出等。
- `AssistantMessage`：模型输出的一个 content block。
- `SystemMessage`：系统提示、错误、compact boundary、API metrics 等。
- `AttachmentMessage`：排队命令、hook 附件、任务通知等。
- `ProgressMessage`：工具或 hook 运行过程中的进度。
- `TombstoneMessage`：撤销已显示消息。
- `StreamEvent`：API raw streaming event 的 UI 旁路。

这个中间层让 Claude Code 不依赖“字符串输出”，而是依赖“结构化事件”。终端 UI 能根据结构化信息决定：

- 哪些消息要折叠。
- 哪些工具结果要合并。
- 哪些 read/search 输出要压缩成一组。
- 哪些 thinking 只在 transcript / verbose 模式展示。
- 哪些错误要用红色、提示、快捷操作渲染。
- 哪些工具调用需要显示 loader、等待权限、执行进度或结果摘要。

## Messages：列表层如何组织视觉结构

`src/components/Messages.tsx` 是消息列表渲染器。它接收 REPL 状态：

- `messages`：稳定消息历史。
- `streamingText`：正在流式输出但还没成为最终 `AssistantMessage` 的文本。
- `streamingToolUses`：正在拼接输入 JSON 的工具调用。
- `inProgressToolUseIDs`：已经开始执行但未完成的工具调用。
- `toolUseConfirmQueue`：权限确认队列。
- `screen`：主屏或 transcript。
- `isLoading`、`verbose`、`isBriefOnly` 等显示开关。

它先做一系列消息变换：

- `normalizeMessages()`：标准化消息结构。
- `reorderMessagesInUI()`：调整 UI 顺序，尤其是流式和工具结果的相对位置。
- `applyGrouping()`：把可合并工具调用归组。
- `collapseReadSearchGroups()`：折叠 Read/Search 类消息。
- `collapseHookSummaries()`、`collapseBackgroundBashNotifications()`、`collapseTeammateShutdowns()`：减少噪声。
- `buildMessageLookups()`：建立 tool_use_id 到 tool_result、错误、完成状态等索引。

然后它决定如何渲染：

- fullscreen 模式下使用 `VirtualMessageList`，避免长会话把所有消息 Fiber 都挂载。
- 非 virtual 模式下有 `MAX_MESSAGES_WITHOUT_VIRTUALIZATION` 安全上限，避免 Ink/Yoga 布局和 terminal frame 过大。
- `streamingText` 作为消息列表末尾的特殊预览节点渲染，不进入正式历史。
- `streamingToolUses` 会被临时转换成 synthetic assistant message，使“正在准备工具调用”的状态能像普通工具消息一样渲染。

关键视觉点：`streamingText` 的渲染不是普通文本，而是：

```text
黑点 bullet + StreamingMarkdown(streamingText)
```

`StreamingMarkdown` 会把稳定前缀和正在变化的后缀分开，避免每个 token 都重新解析整段 Markdown。

## Message：按内容块分发组件

`src/components/Message.tsx` 负责把单条 renderable message 分发到具体组件。

对于 `assistant` 消息，它遍历 `message.message.content`，每个 block 交给 `AssistantMessageBlock`：

- `text` -> `AssistantTextMessage`
- `tool_use` -> `AssistantToolUseMessage`
- `thinking` -> `AssistantThinkingMessage`
- `redacted_thinking` -> `AssistantRedactedThinkingMessage`
- `server_tool_use` / advisor 结果 -> `AdvisorMessage`

这就是“每个 content block 一个 AssistantMessage”带来的 UI 好处：不同 block 不需要在一个大字符串里做脆弱解析，而是直接按 API 结构选组件。

## 文本输出：Markdown 与消息气泡

`src/components/messages/AssistantTextMessage.tsx` 处理普通模型文本。

它先识别特殊错误文本：

- prompt too long。
- credit balance too low。
- invalid API key。
- org disabled。
- timeout。
- user abort。
- rate limit。

普通文本会进入：

```text
<MessageResponse>
  <Markdown>{text}</Markdown>
</MessageResponse>
```

`MessageResponse` 提供 Claude Code 典型的左侧 `⎿` 响应前缀，并通过 `Ratchet` 稳定 offscreen 布局，减少流式渲染时的跳动。

`src/components/Markdown.tsx` 负责 Markdown 渲染：

- 使用 `marked.lexer()` 把文本转 token。
- 普通 Markdown token 被 `formatToken()` 转成 ANSI 字符串。
- 表格用 `MarkdownTable` 以 React 组件方式渲染，保证终端对齐。
- 代码高亮通过 `getCliHighlightPromise()` 获取 highlighter。
- 对没有 Markdown 语法的普通文本走快速路径，避免 lexer 成本。
- `StreamingMarkdown` 在流式期间只重解析不稳定后缀，性能更稳。

## 工具调用：为什么看起来像“步骤”

`src/components/messages/AssistantToolUseMessage.tsx` 渲染 `tool_use` block。

它会：

- 根据 `param.name` 找到工具定义。
- 用工具的 `inputSchema` 解析 `param.input`。
- 调用工具自己的 `userFacingName(input)` 得到显示名。
- 调用工具自己的 `renderToolUseMessage(input)` 得到括号里的摘要。
- 根据 `lookups.resolvedToolUseIDs`、`lookups.erroredToolUseIDs`、`inProgressToolUseIDs` 判断状态。
- 显示 loader、黑点、等待权限、执行中进度或队列状态。
- 调用 `renderToolUseProgressMessage()` 展示工具实时进度。

这也是终端体验直观的重要来源：模型不是输出“我要调用 Bash”，而是 API 返回结构化 `tool_use`，UI 根据工具定义渲染成一行人类可读的动作，例如读文件、搜索、编辑、运行命令，并附带 loader 和结果。

工具结果一般以 `UserMessage` 的 `tool_result` 形式回到消息列表，再由 `UserToolResultMessage` 和具体工具结果组件渲染。对模型来说它是下一轮上下文；对用户来说它是工具执行结果。

## thinking 的显示策略

Claude Code 接收 `thinking_delta` 并累积 thinking block，但默认主屏不直接展示 thinking。

`Message.tsx` 中的逻辑是：

- `thinking` 和 `redacted_thinking` 在非 transcript 且非 verbose 时返回 `null`。
- transcript 模式或 verbose 模式才渲染 `AssistantThinkingMessage`。
- transcript 模式还可以只保留最后一个 thinking block，避免历史 thinking 噪声过多。

因此用户通常看到的是响应、工具和结果，而不是完整 hidden reasoning。源码里仍然保留 thinking block，因为 API 签名、后续请求和 transcript 规则可能需要它。

## Spinner 与实时状态

流式事件通过 `handleMessageFromStream()` 把 `streamMode` 设为不同阶段：

- `requesting`：请求已开始。
- `thinking`：模型进入 thinking block。
- `responding`：模型输出文本。
- `tool-input`：模型正在生成工具输入。
- `tool-use`：模型消息结束，进入工具使用阶段。

REPL 底部根据 `streamMode` 渲染 `SpinnerWithVerb`。同时 `responseLengthRef` 会随着 `text_delta`、`input_json_delta`、`thinking_delta` 增长，用于动画和吞吐指标。`signature_delta` 被排除，因为它是签名，不是用户可见输出。

## 终端渲染层：React/Ink 不是 console.log

本仓库有自带 Ink 实现，入口是 `src/ink.ts` 和 `src/ink/root.ts`。

`src/ink.ts` 对外导出：

- `render()`
- `createRoot()`
- `Box`
- `Text`
- `Ansi`
- 各种 hooks 和基础组件

并且所有 render 都被 `ThemeProvider` 包起来，所以颜色、主题、design-system 组件能在终端里统一工作。

`src/ink/root.ts` 创建 `Ink` 实例，并暴露类似 React DOM 的 root API：

```text
const root = await createRoot(renderOptions)
root.render(<App><REPL /></App>)
await root.waitUntilExit()
```

`src/ink/ink.tsx` 是真正的渲染器。它大致做：

- React reconciler 把 `<Box>`、`<Text>` 等组件树变成内部 DOM。
- Yoga/layout 计算每个元素在终端里的行列位置、宽高、换行和 flex 布局。
- render 阶段生成当前 frame，也就是一张终端字符网格。
- `this.log.render(prevFrame, frame, ...)` 对比上一帧和下一帧，生成补丁。
- `optimize(diff)` 合并、优化补丁。
- `writeDiffToTerminal(this.terminal, optimized, ...)` 写入 stdout。

这解释了为什么 UI 可以做到：

- 局部刷新，而不是整屏滚动刷日志。
- spinner、输入框、消息列表同时存在。
- alt-screen/fullscreen 模式下有类似应用的交互体验。
- 主屏模式下仍然利用终端 scrollback。
- 支持光标定位、鼠标、滚动、选择、terminal title、OSC 进度等。

## Fullscreen 与 main-screen 两种体验

REPL 最后根据 `isFullscreenEnvEnabled()` 决定是否包 `<AlternateScreen>`：

- fullscreen / alt-screen：进入终端备用屏幕，UI 更像全屏 TUI，滚动由 `ScrollBox` / `VirtualMessageList` 管理。
- main-screen：不进入备用屏幕，历史内容留在终端原生 scrollback 中。

源码对这两种模式有大量差异处理：

- alt-screen 渲染前会把物理光标锚定到 `(0,0)`，避免 tmux 或终端状态栏干扰导致内容漂移。
- alt-screen 下 diff 会加 cursor home、erase、park cursor 等补丁，保证画面稳定。
- main-screen 不能随意 `CSI H` 回到屏幕左上，因为 scrollback 行不可控，所以用不同的 cursor move 策略。
- fullscreen 下保留更多历史给虚拟滚动；main-screen 下旧内容已经在原生 scrollback 中，组件树可以截断以保护性能。

## 为什么效果直观

Claude Code 的交互效果来自几个设计叠加：

- 模型输出是结构化 blocks，不是纯文本。
- raw stream event 和最终 message 分离，兼顾实时性与稳定历史。
- REPL 把“正在生成文本”“正在生成工具输入”“工具执行中”“等待权限”“用户输入框”“任务列表”等都变成 React state。
- `Messages` 层做归组、折叠、过滤、虚拟列表，降低长会话噪声。
- `Message` 层按 block 类型渲染专门组件，让 text、tool_use、thinking、tool_result 拥有完全不同的视觉表达。
- 工具自身提供 `userFacingName()`、`renderToolUseMessage()`、进度和结果渲染，UI 能显示具体动作而不是 JSON。
- Markdown、表格、代码高亮、ANSI 颜色让模型正文更像文档。
- Ink 渲染器做 frame diff 和 cursor 控制，使终端像一个动态应用，而不是日志流。

## 最小心理模型

如果只记一条主线，可以这样理解：

```text
Anthropic SSE event
  -> claude.ts 累积 content block
  -> query.ts 管理 agent loop 和工具循环
  -> REPL.handleMessageFromStream 更新 React state
  -> Messages/Message 按消息结构选择 UI 组件
  -> Ink 把 React 组件树 layout 成终端 frame
  -> diff 后写 stdout
```

这里最关键的不是某一个组件，而是“结构化消息 + 流式旁路 + React/Ink 差分渲染”的组合。Claude Code 之所以看起来直观，是因为它没有把模型当作字符串生成器，而是把模型响应、工具调用、权限、进度和用户输入都放进同一个可重绘的终端 UI 状态机里。

## 进一步阅读顺序

建议按以下顺序继续读源码：

1. `src/screens/REPL.tsx`：理解交互状态、`onQuery`、最终 JSX 布局。
2. `src/query.ts`：理解 agent turn loop、工具调用、fallback、compact。
3. `src/services/api/claude.ts`：理解 Anthropic SDK 流式事件如何变成内部消息。
4. `src/utils/messages.ts`：重点读 `handleMessageFromStream()`、`normalizeMessages()`、`buildMessageLookups()`。
5. `src/components/Messages.tsx`：理解消息归组、折叠、虚拟列表、streaming preview。
6. `src/components/Message.tsx`：理解消息类型到组件的分发。
7. `src/components/messages/AssistantTextMessage.tsx` 和 `AssistantToolUseMessage.tsx`：理解正文和工具调用的视觉呈现。
8. `src/components/Markdown.tsx`：理解 Markdown、表格、代码高亮和 streaming markdown 优化。
9. `src/ink/root.ts`、`src/ink/ink.tsx`：理解 React/Ink 如何最终写到终端。
