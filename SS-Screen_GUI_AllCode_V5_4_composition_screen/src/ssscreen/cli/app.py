"""Preview-only Click command surface for the standalone GUI.

This module exists only so the GUI can be opened and reviewed without the
scientific SS-Screen source tree.  Every command prints a PREVIEW message;
it does not perform materials calculations.
"""

from __future__ import annotations

from pathlib import Path

import click

from .. import __version__
from ..gui.metadata import COMMANDS, PATH_PRESETS


@click.group(help="SS-Screen GUI preview command surface (no scientific calculations).")
@click.version_option(version=__version__)
def cli() -> None:
    pass


dataset = click.Group("dataset", help="Preview dataset commands.")
stability = click.Group("stability", help="Preview stability commands.")
cli.add_command(dataset)
cli.add_command(stability)


def _path_option(flag: str, default=None) -> click.Option:
    name = flag.lstrip("-").replace("-", "_")
    is_dir = name.endswith(("dir", "dirs")) or "directory" in name
    multiple = isinstance(default, (tuple, list))
    if is_dir:
        ptype = click.Path(path_type=Path, file_okay=False, dir_okay=True, exists=False)
    else:
        ptype = click.Path(path_type=Path, file_okay=True, dir_okay=False, exists=False)
    return click.Option(
        [flag],
        default=None,
        multiple=multiple,
        type=ptype,
        help="界面预览参数；正式版本由真实 SS-Screen CLI 定义。",
    )


EXTRA_OPTIONS: dict[tuple[str, ...], list[click.Option]] = {
    ("dataset", "mp"): [
        click.Option(["--backend"], type=click.Choice(["api", "offline"]), default="api", show_default=True),
        click.Option(["--offline-db"], type=click.Path(path_type=Path), default=None),
        click.Option(["--max-e-hull"], type=float, default=0.01, show_default=True),
    ],
    ("composition-screen",): [
        click.Option(
            ["--valence-ids"],
            type=click.Path(path_type=Path, file_okay=True, dir_okay=False, exists=False),
            default=None,
        ),
        click.Option(["--nelems"], type=int, default=2, show_default=True),
        click.Option(["--max-bandgap"], type=float, default=1.0, show_default=True),
        click.Option(["--max-e-hull"], type=float, default=0.01, show_default=True),
        click.Option(["--min-group-size"], type=int, default=2, show_default=True),
        click.Option(["--min-x-elements"], type=int, default=2, show_default=True),
    ],
    ("condense",): [
        click.Option(["--input"], multiple=True, type=click.Path(path_type=Path), default=()),
        click.Option(["--structure-column"], default="structure", show_default=True),
        click.Option(["--material-id-column"], default=None),
        click.Option(["--limit"], type=int, default=None),
        click.Option(["--stop-on-error/--continue-on-error"], default=False),
    ],
    ("structure-match",): [
        click.Option(["--min-x-elements"], type=int, default=2, show_default=True),
    ],
    ("gap-export",): [
        click.Option(["--method"], default="external-gap-method-v1", show_default=True),
    ],
    ("pair",): [
        click.Option(["--method"], default="external-gap-method-v1", show_default=True),
        click.Option(["--low-gap"], type=float, default=0.15, show_default=True),
        click.Option(["--direct-min"], type=float, default=0.15, show_default=True),
        click.Option(["--direct-max"], type=float, default=1.5, show_default=True),
    ],
    ("stability", "sqs-generate"): [
        click.Option(["--target-fraction"], type=float, default=0.5, show_default=True),
        click.Option(["--supercell"], default="2,2,2", show_default=True),
        click.Option(["--backend"], type=click.Choice(["random", "icet"]), default="icet", show_default=True),
        click.Option(["--cutoff"], type=float, default=4.0, show_default=True),
        click.Option(["--sqs-steps"], type=int, default=10000, show_default=True),
        click.Option(["--seed"], type=int, default=7, show_default=True),
    ],
    ("stability", "relax"): [
        click.Option(["--backend"], type=click.Choice(["mace"]), default="mace", show_default=True),
        click.Option(["--model-name"], default="MACE-MPA-0-medium", show_default=True),
        click.Option(["--device"], default="cuda:0", show_default=True),
        click.Option(["--dtype"], type=click.Choice(["float32", "float64"]), default="float32", show_default=True),
        click.Option(["--fmax"], type=float, default=0.03, show_default=True),
        click.Option(["--max-steps"], type=int, default=500, show_default=True),
        click.Option(["--include-endmembers/--no-include-endmembers"], default=True),
        click.Option(["--relax-cell/--no-relax-cell"], default=True),
    ],
    ("stability", "phonon-run"): [
        click.Option(["--device"], default="cuda:0", show_default=True),
        click.Option(["--dtype"], type=click.Choice(["float32", "float64"]), default="float64", show_default=True),
        click.Option(["--displacement"], type=float, default=0.01, show_default=True),
        click.Option(["--mesh"], default="20,20,20", show_default=True),
        click.Option(["--imaginary-tolerance"], type=float, default=0.1, show_default=True),
    ],
    ("stability", "phase-diagram"): [
        click.Option(["--mp-backend"], type=click.Choice(["api", "offline"]), default="api", show_default=True),
        click.Option(["--mp-max-e-hull"], type=float, default=0.1, show_default=True),
        click.Option(["--device"], default="cuda:0", show_default=True),
        click.Option(["--dtype"], type=click.Choice(["float32", "float64"]), default="float32", show_default=True),
        click.Option(["--fmax"], type=float, default=0.03, show_default=True),
    ],
    ("recommend",): [
        click.Option(["--promising-max-mixing"], type=float, default=25.0, show_default=True),
        click.Option(["--low-priority-mixing"], type=float, default=50.0, show_default=True),
        click.Option(["--promising-max-hull"], type=float, default=0.025, show_default=True),
        click.Option(["--low-priority-hull"], type=float, default=0.1, show_default=True),
    ],
}


def _callback_factory(command_path: tuple[str, ...]):
    def callback(**kwargs):
        click.echo("[DEMO] 当前独立界面包仅演示命令与日志，不执行科学计算。")
        click.echo("Command: ss-screen " + " ".join(command_path))
        nonempty = {k: str(v) for k, v in kwargs.items() if v not in (None, (), [])}
        if nonempty:
            click.echo("Parameters:")
            for key, value in sorted(nonempty.items()):
                click.echo(f"  {key} = {value}")
    return callback


def _make_command(path: tuple[str, ...], title: str) -> click.Command:
    params: list[click.Parameter] = []
    seen: set[str] = set()

    # Use project-local path presets to render realistic file/directory fields.
    for flag, default in PATH_PRESETS.get(path, {}).items():
        params.append(_path_option(flag, default))
        seen.add(flag)

    # Add representative scientific controls for the important pages.
    for option in EXTRA_OPTIONS.get(path, []):
        flags = set(option.opts + option.secondary_opts)
        if flags & seen:
            continue
        params.append(option)
        seen.update(flags)

    return click.Command(
        name=path[-1],
        callback=_callback_factory(path),
        params=params,
        help=f"{title}（GUI 独立预览模式；正式科学参数以真实 SS-Screen CLI 为准。）",
    )


for presentation in COMMANDS:
    path = presentation.command_path
    command = _make_command(path, presentation.title)

    if len(path) == 1:
        cli.add_command(command, name=path[0])
    elif path[0] == "dataset":
        dataset.add_command(command, name=path[1])
    elif path[0] == "stability":
        stability.add_command(command, name=path[1])


if __name__ == "__main__":
    cli()
