# SS-Screen GUI V5.5 — Materials Project / 数据源界面完善

本版基于 V5.4 继续完善 Stage 01。

关键变化：**Materials Project 不再只是一个普通 CLI 命令，而是明确作为外部材料数据源展示。**

## 工程树

```text
01 数据源
├─ Materials Project
│  ├─ 数据获取 / Acquisition
│  ├─ Local Dataset / mp.df
│  └─ Provenance / 来源记录
└─ WBM Dataset
   ├─ 数据获取 / Acquisition
   └─ Local Dataset / wbm.df
```

这和后面的工程对象逻辑保持一致：

```text
01 外部数据源
   ↓
本地规范化 DataFrame
   ↓
02 Composition Candidates
   ↓
03 Structure Description Archive
   ↓
04 Structure Groups
```

## Materials Project 页面

专用页面明确显示：

- 类型：External materials database / 外部材料数据库
- 在 SS-Screen 中的作用
- 数据流
- API / Offline 两种数据模式
- Offline 数据库文件
- 最大凸包距离
- `01_dataset/mp.df`
- `01_dataset/mp.df.provenance.json`
- API Key 使用说明
- Command Preview
- 本地结果状态

### API Key

API Key 仍然放在右侧：

```text
Properties
└─ Connection
   └─ MP API Key
```

GUI 只把它注入当前任务进程，不写入命令和项目结果。

## WBM

WBM 也作为外部数据源单独显示，并输出：

```text
01_dataset/wbm.df
```

## Local Datasets

新增统一的本地数据页：

```text
Data Source         Local DataFrame       Status
Materials Project   01_dataset/mp.df      Ready
WBM Dataset         01_dataset/wbm.df     Ready
```

同时可以浏览 Materials Project 的 provenance JSON。

这样用户会很清楚：

> Materials Project / WBM 是数据来源；
> mp.df / wbm.df 才是 SS-Screen 工程内部后续筛选真正使用的数据对象。

## 运行

```powershell
python run_gui_preview.py
```

或直接：

```text
run_gui.bat
```
