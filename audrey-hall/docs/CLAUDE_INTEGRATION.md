# Audrey Hall Claude Hooks

`Audrey Hall` 现已内置 Claude Code hook 联动服务。

## 本地接口

- `GET http://127.0.0.1:9527/api/heartbeat`
- `GET http://127.0.0.1:9527/api/current`
- `POST http://127.0.0.1:9527/api/hook/thinking`
- `POST http://127.0.0.1:9527/api/hook/working`
- `POST http://127.0.0.1:9527/api/hook/done`
- `POST http://127.0.0.1:9527/api/hook/permission`
- `POST http://127.0.0.1:9527/api/hook/idle`

## 当前映射

- `UserPromptSubmit` -> `正在组织回复...`
- `Read` / `Glob` / `Grep` -> `正在读取文件...`
- `Write` / `Edit` / `NotebookEdit` -> `正在构建...`
- `Bash` / `PowerShell` -> `正在执行命令...`
- `Agent` / `TaskCreate` / `TaskUpdate` / `TodoWrite` -> `正在分析...`
- `WebFetch` -> `正在获取网络内容...`
- `WebSearch` -> `正在搜索网络...`
- 其他工具 -> `工作中...`
- `PostToolUse` -> `太棒了!`
- `PermissionRequest` -> `等待指示...`
- `Stop` -> 清空气泡

## Claude Code 配置

把 `docs/claude-hooks.json` 里的 `hooks` 合并到 Claude Code 的用户设置中。

如果你的 Python 路径或工程路径不同，先修改 `SessionStart.command`。

## 说明

- 服务启动端口固定为 `127.0.0.1:9527`
- 内置了最小停留时间，避免工具切换时气泡闪烁
- 当前版本先实现气泡联动，未单独切换桌宠 GIF 动画素材
