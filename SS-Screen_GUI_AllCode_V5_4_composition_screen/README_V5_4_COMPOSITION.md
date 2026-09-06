# SS-Screen GUI V5.4 — “组成模板筛选”专用界面

本版是在你上传的 `SS-Screen_GUI_AllCode_V5_2_layout_fixed.zip` 基础上完善。

同时修复了 V5.2 的 `QSizePolicy` 漏导入问题。

## 02 工程树

现在 `02 组成模板筛选` 不再只显示一个 `composition-screen` 命令，而是：

```text
02 组成模板筛选
├─ 价态过滤（可选）
├─ 筛选输入
├─ 筛选规则
├─ Composition Candidates / 候选材料表
└─ Screening Summary / 筛选统计
```

### 候选材料表
对应：
```text
02_composition/composition_candidates.csv
```

工程树会尽量显示实际候选记录数量。

### 筛选统计
对应：
```text
02_composition/composition_summary.json
```

工程树会显示是否生成；若 JSON 中存在 `template_count`，还会显示模板数量。

## 专用中央界面

包含两个 Tab：

### 1. 筛选设置与执行
完整体现：

- 可重复 `--df`
- 可选 `--valence-ids`
- `--nelems`
- `--max-bandgap`
- `--max-e-hull`
- `--min-group-size`
- `--min-x-elements`
- `--output`
- `--summary`

默认数据源按你提供的示例显示：

```text
01_dataset/mp.df
01_dataset/wbm.df
```

### 2. 筛选结果

自动读取：

```text
02_composition/composition_candidates.csv
02_composition/composition_summary.json
```

并显示：

- `input_rows`
- `selected_rows`
- `template_count`
- `candidate_rows`
- 实际筛选参数
- 完整 Summary JSON 字段
- 完整候选 CSV 表

候选表支持：
- 文本搜索
- Template 下拉筛选
- 表格排序
- 直接打开 CSV
- 直接打开 summary JSON

GUI 不强制假设候选 CSV 的完整字段结构；它会读取 CSV 实际表头。
常见字段如 `template / material_id / formula / x_element / band_gap / e_hull / source`
会显示更友好的标题，其余字段原样保留。

## 运行

```powershell
python run_gui_preview.py
```

或直接双击：

```text
run_gui.bat
```
