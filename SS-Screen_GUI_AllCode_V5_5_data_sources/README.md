# SS-Screen GUI V5.1 — 修正版（GUI 全部代码）

这版修复你遇到的：

```text
ImportError: cannot import name '__version__' from 'src.ssscreen'
```

## 报错原因

上一包把真正的 GUI 放在：

```text
desktop/src/ssscreen/gui/
```

但把 GUI 单独运行所需的：

```text
ssscreen/__init__.py
ssscreen/cli/app.py
```

放到了另一个 `preview_support/` 目录。

因此运行时 `gui/app.py` 执行：

```python
from .. import __version__
```

时，当前 `ssscreen` 包中没有 `__version__`。

另外，启动入口必须使用：

```python
from ssscreen.gui.app import run_gui
```

而不是：

```python
from src.ssscreen.gui.app import run_gui
```

因为加入 `sys.path` 的已经是项目中的 `src/` 目录。

## V5.1 目录

```text
SS-Screen_GUI_AllCode_V5_1_fixed/
├─ run_gui_preview.py
├─ run_gui.bat
├─ requirements-gui.txt
├─ README.md
│
├─ src/
│  └─ ssscreen/
│     ├─ __init__.py          # 定义 __version__
│     ├─ cli/
│     │  ├─ __init__.py
│     │  └─ app.py            # 仅用于 GUI 独立预览的 CLI stub
│     └─ gui/
│        ├─ __init__.py
│        ├─ app.py            # 完整 GUI 主代码
│        ├─ metadata.py       # GUI 阶段/命令/默认路径
│        └─ launcher.py
│
└─ web/
   └─ *.html
```

## Windows 最简单运行

直接双击：

```text
run_gui.bat
```

或者 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe run_gui_preview.py
```

## 注意

这里的 `src/ssscreen/cli/app.py` 只是为了让 GUI 脱离真实科学计算源码也能运行和演示。
它不会做真正的材料计算。

真正需要继续修改 GUI 时，主要看：

```text
src/ssscreen/gui/app.py
src/ssscreen/gui/metadata.py
```
