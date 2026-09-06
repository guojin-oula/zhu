"""GUI-only presentation metadata for the existing ``ss-screen`` CLI.

Scientific defaults and validation continue to come from Click.  This module
only supplies display order, Chinese stage names, and convenient project-local
path presets for blank path options.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandPresentation:
    """Human-facing placement and title for a CLI command."""

    stage: str
    title: str
    command_path: tuple[str, ...]


STAGES: tuple[tuple[str, str, str], ...] = (
    ("00", "工作台", ""),
    ("01", "数据源", "01_dataset"),
    ("02", "组成模板筛选", "02_composition"),
    ("03", "结构描述归档", "03_condensed"),
    ("04", "结构匹配与材料分组", "04_groups"),
    ("05", "带隙交接", "05_gap"),
    ("06", "端元配对", "06_pairs"),
    ("07", "SQS 合金", "07_sqs"),
    ("08", "MACE 驰豫", "08_relaxation"),
    ("09", "混合焓", "09_thermodynamics"),
    ("10", "声子谱", "10_phonons"),
    ("11", "竞争相 / 凸包", "11_phase_diagram"),
    ("12", "综合推荐", "12_recommendation"),
)


COMMANDS: tuple[CommandPresentation, ...] = (
    CommandPresentation("01", "Materials Project 数据获取", ("dataset", "mp")),
    CommandPresentation("01", "WBM 数据获取", ("dataset", "wbm")),
    CommandPresentation("02", "价态过滤", ("valence-filter",)),
    CommandPresentation("02", "组成模板筛选", ("composition-screen",)),
    CommandPresentation("03", "生成结构描述", ("condense",)),
    CommandPresentation("03", "建立归档索引", ("condense-index",)),
    CommandPresentation("03", "校验结构描述归档", ("condense-validate",)),
    CommandPresentation("04", "执行结构匹配", ("structure-match",)),
    CommandPresentation("04", "兼容一步式分组", ("group",)),
    CommandPresentation("05", "导出高精度带隙任务", ("gap-export",)),
    CommandPresentation("05", "收集 VASP 带隙结果", ("gap-collect-vasp",)),
    CommandPresentation("05", "校验外部带隙结果", ("gap-validate",)),
    CommandPresentation("06", "生成端元对", ("pair",)),
    CommandPresentation("06", "比较带隙方法", ("gap-compare",)),
    CommandPresentation("07", "生成 SQS", ("stability", "sqs-generate")),
    CommandPresentation("08", "MACE 结构驰豫", ("stability", "relax")),
    CommandPresentation("09", "混合焓计算", ("stability", "mixing-enthalpy")),
    CommandPresentation("10", "声子任务导出", ("stability", "phonon-export")),
    CommandPresentation("10", "声子位移力计算", ("stability", "phonon-forces")),
    CommandPresentation("10", "声子结果收集", ("stability", "phonon-collect")),
    CommandPresentation("10", "声子谱一步式运行", ("stability", "phonon-run")),
    CommandPresentation("11", "竞争相导出", ("stability", "competing-export")),
    CommandPresentation("11", "竞争相驰豫", ("stability", "competing-relax")),
    CommandPresentation("11", "统一基准凸包", ("stability", "convex-hull")),
    CommandPresentation("11", "竞争相与凸包一步式运行", ("stability", "phase-diagram")),
    CommandPresentation("12", "综合推荐", ("recommend",)),
)


# Project-local conveniences only.  They fill otherwise-empty widgets; Click's
# own defaults remain authoritative for scientific/numerical parameters.
PATH_PRESETS: dict[tuple[str, ...], dict[str, Any]] = {
    ("dataset", "mp"): {
        "--output": "01_dataset/mp.df",
        "--provenance": "01_dataset/mp.df.provenance.json",
    },
    ("dataset", "wbm"): {"--output": "01_dataset/wbm.df"},
    ("valence-filter",): {
        "--df-mp": "01_dataset/mp.df",
        "--output": "02_composition/valid_ids.json",
    },
    ("composition-screen",): {
        "--df": ("01_dataset/mp.df",),
        "--output": "02_composition/composition_candidates.csv",
        "--summary": "02_composition/composition_summary.json",
    },
    ("condense",): {
        "--df": "01_dataset/mp.df",
        "--output-dir": "03_condensed/mp",
        "--manifest": "03_condensed/mp_manifest.jsonl",
        "--index": "03_condensed/mp_index.csv",
    },
    ("condense-index",): {
        "--condensed-dir": "03_condensed/mp",
        "--output": "03_condensed/mp_index.csv",
    },
    ("condense-validate",): {
        "--condensed-dir": "03_condensed/mp",
        "--output": "03_condensed/validation.csv",
    },
    ("structure-match",): {
        "--candidates": "02_composition/composition_candidates.csv",
        "--condensed-dir": ("03_condensed/mp",),
        "--output": "04_groups/groups.json",
        "--summary": "04_groups/structure_match_summary.json",
    },
    ("group",): {
        "--df-mp": "01_dataset/mp.df",
        "--condensed-dirs": ("03_condensed/mp",),
        "--output": "04_groups/groups_legacy.json",
    },
    ("gap-export",): {
        "--groups": "04_groups/groups.json",
        "--dataset": "01_dataset/mp.df",
        "--structure-dir": "05_gap/structures",
        "--results-template": "05_gap/results_template.csv",
        "--method-metadata-template": "05_gap/method_metadata.json",
        "--output": "05_gap/tasks.csv",
    },
    ("gap-collect-vasp",): {
        "--tasks": "05_gap/tasks.csv",
        "--results-dir": "05_gap/vasp-results",
        "--method-metadata": "05_gap/method_metadata.json",
        "--output": "05_gap/results_returned.csv",
        "--report": "05_gap/collection-report.json",
    },
    ("gap-validate",): {
        "--gaps": "05_gap/results_returned.csv",
        "--tasks": "05_gap/tasks.csv",
        "--method-metadata": "05_gap/method_metadata.json",
        "--output": "05_gap/results_normalized.csv",
        "--rejected": "05_gap/results_rejected.csv",
        "--report": "05_gap/validation.json",
    },
    ("pair",): {
        "--groups": "04_groups/groups.json",
        "--gap-results": ("05_gap/results_normalized.csv",),
        "--summary": "06_pairs/gap_feedback_summary.json",
        "--output": "06_pairs/final_pairs.csv",
    },
    ("gap-compare",): {
        "--groups": "04_groups/groups.json",
        "--gap-results": ("05_gap/results_normalized.csv",),
        "--output-dir": "06_pairs/gap_compare",
        "--summary": "06_pairs/gap_compare_summary.json",
    },
    ("stability", "sqs-generate"): {
        "--pairs": "06_pairs/final_pairs.csv",
        "--dataset": "01_dataset/mp.df",
        "--output-dir": "07_sqs/structures",
        "--manifest": "07_sqs/manifest.jsonl",
    },
    ("stability", "relax"): {
        "--manifest": "07_sqs/manifest.jsonl",
        "--model-path": "models/mace-mpa-0-medium.model",
        "--output-dir": "08_relaxation",
        "--results": "08_relaxation/relaxation_results.jsonl",
    },
    ("stability", "mixing-enthalpy"): {
        "--pairs": "06_pairs/final_pairs.csv",
        "--relax-results": "08_relaxation/relaxation_results.jsonl",
        "--output": "09_thermodynamics/mixing_enthalpy.csv",
        "--summary": "09_thermodynamics/mixing_summary.json",
    },
    ("stability", "phonon-export"): {
        "--relax-results": "08_relaxation/relaxation_results.jsonl",
        "--output-dir": "10_phonons/tasks",
        "--manifest": "10_phonons/manifest.jsonl",
    },
    ("stability", "phonon-forces"): {
        "--manifest": "10_phonons/manifest.jsonl",
        "--model-path": "models/mace-mpa-0-medium.model",
        "--output-dir": "10_phonons/forces",
        "--results": "10_phonons/force_results.jsonl",
    },
    ("stability", "phonon-collect"): {
        "--manifest": "10_phonons/manifest.jsonl",
        "--force-results": "10_phonons/force_results.jsonl",
        "--output-dir": "10_phonons",
        "--summary": "10_phonons/phonon_summary.csv",
        "--report": "10_phonons/phonon_report.json",
    },
    ("stability", "phonon-run"): {
        "--relax-results": "08_relaxation/relaxation_results.jsonl",
        "--model-path": "models/mace-mpa-0-medium.model",
        "--output-dir": "10_phonons",
    },
    ("stability", "competing-export"): {
        "--relax-results": "08_relaxation/relaxation_results.jsonl",
        "--output-dir": "11_phase_diagram/competing",
        "--manifest": "11_phase_diagram/competing_manifest.jsonl",
        "--report": "11_phase_diagram/competing_export_report.json",
    },
    ("stability", "competing-relax"): {
        "--manifest": "11_phase_diagram/competing_manifest.jsonl",
        "--model-path": "models/mace-mpa-0-medium.model",
        "--output-dir": "11_phase_diagram/competing_relaxed",
        "--results": "11_phase_diagram/competing_relaxation_results.jsonl",
    },
    ("stability", "convex-hull"): {
        "--relax-results": "08_relaxation/relaxation_results.jsonl",
        "--competing-manifest": "11_phase_diagram/competing_manifest.jsonl",
        "--competing-results": "11_phase_diagram/competing_relaxation_results.jsonl",
        "--output": "11_phase_diagram/phase_stability.csv",
        "--entries-output": "11_phase_diagram/hull_entries.csv",
        "--summary": "11_phase_diagram/summary.json",
    },
    ("stability", "phase-diagram"): {
        "--relax-results": "08_relaxation/relaxation_results.jsonl",
        "--model-path": "models/mace-mpa-0-medium.model",
        "--output-dir": "11_phase_diagram",
    },
    ("recommend",): {
        "--pairs": "06_pairs/final_pairs.csv",
        "--gap-results": "05_gap/results_normalized.csv",
        "--mixing-enthalpy": "09_thermodynamics/mixing_enthalpy.csv",
        "--phonons": "10_phonons/phonon_summary.csv",
        "--phase-stability": "11_phase_diagram/phase_stability.csv",
        "--output": "12_recommendation/recommendations.csv",
        "--report": "12_recommendation/report.md",
        "--summary": "12_recommendation/summary.json",
    },
}


def stage_title(stage_id: str) -> str:
    """Return a stable display name for a stage identifier."""
    for sid, name, _directory in STAGES:
        if sid == stage_id:
            return name
    return stage_id


def stage_directory(stage_id: str) -> str:
    """Return the conventional project directory for a stage."""
    for sid, _name, directory in STAGES:
        if sid == stage_id:
            return directory
    return ""
