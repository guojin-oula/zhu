# SS-Screen GUI V5.2 — 布局压缩修复版

你截图里的问题不是数据问题，而是 Qt 布局在有限高度下把多个 GroupBox 和
QTableWidget 压到了最小尺寸，尤其是“匹配输入”的结构描述归档表格，所以出现
文字重叠、表头挤成一条线、控件看起来全部被压扁的现象。

V5.2 做了以下修复：

1. **专用页面改为可滚动工程表单**
   - 结构描述归档的 3 个 Tab
   - 结构匹配的 2 个 Tab
   - 屏幕高度不足时出现滚动条，不再强行压缩控件。

2. **关键表格增加最小高度**
   - 结构描述归档文件列表
   - 结构描述库
   - 结构匹配描述归档列表
   - Structure Groups
   - Group members

3. **中央工作区优先获得垂直空间**
   - 底部“任务输出 / 工程文件 / 消息”默认高度由约 210 调整为约 145。
   - 主文档区设最小高度。
   - 垂直 QSplitter 禁止把文档区压成不可读高度。

4. **窗口默认高度提高到 1000**
   - 在 1080p、125% / 150% Windows 缩放下更稳。

5. **增加标准滚动条与表格行高**
   - 保持 CAE 工程软件的紧凑风格，但不再重叠。

## 运行

最简单：

```text
run_gui.bat
```

或者：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe run_gui_preview.py
```

如果屏幕高度较小，可以直接拖动“任务输出”上方的分割线缩小底部区域；
专用参数页内部会自动出现垂直滚动条。
