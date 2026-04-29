## 新增
- 无

## 修复
- 修复概览页点击图片进入裁剪窗口后，裁剪框可能持续跟随鼠标移动、无法取消的问题。
- 修复主窗口拖动过程中释放事件丢失时，窗口仍可能继续跟随鼠标移动的问题。
- 修复部分环境下旧配置未启用 Qt 对话框时，启动阶段因 QFileDialog 空选项枚举构造失败而崩溃的问题。

<details>
<summary>Full Changelog</summary>

483bbe6 fix: 修复旧配置启动崩溃
28dbb63 fix: 修复前端鼠标拖动状态残留
035e21e ci: 使用 changelog 填充发布说明
02ed17b ci: 移除 macOS x86 打包

</details>
