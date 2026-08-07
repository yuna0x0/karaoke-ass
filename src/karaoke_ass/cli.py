"""Command line entry point: `karaoke-ass <subcommand>`.

Each subcommand is a thin wrapper around the module that does the work, so the
modules stay independently importable and testable.
"""
import argparse
import os
import shutil
import subprocess
import sys

from . import _platform


def _lua_dir():
    return os.path.join(_platform.ROOT, "lua")


def cmd_apply(args, rest):
    """Run the karaoke templater without opening the editor."""
    lua = os.environ.get("KARA_LUA")
    if not lua:
        for c in ("luajit", "lua5.1", "lua"):
            if shutil.which(c):
                lua = c
                break
    if not lua:
        sys.exit("No Lua interpreter found. Install luajit, or set KARA_LUA.")

    script = os.path.join(_lua_dir(), "apply_template.lua")
    if not os.path.exists(script):
        sys.exit("Cannot find %s. Run from a checkout, or set KARA_LUA_DIR." % script)

    env = dict(os.environ)
    # Let the driver call back into this package without an install step.
    src = os.path.join(_platform.ROOT, "src")
    if os.path.isdir(src):
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    if args.renderer_metrics:
        env["KARA_MEASURE"] = "libass"

    cmd = [lua, script, args.source, args.output] + list(rest)
    return subprocess.call(cmd, env=env)


def cmd_check(args, rest):
    """Run both checkers over an applied file."""
    from . import check_frame, check_layout
    rc = 0
    argv = ["check-layout", args.source, args.applied]
    if args.verbose:
        argv.append("-v")
    sys.argv = argv
    rc |= check_layout.main() or 0
    print()
    sys.argv = ["check-frame", args.applied]
    check_frame.main()
    return rc


def _forward(module_main, argv0, rest):
    sys.argv = [argv0] + list(rest)
    return module_main() or 0


def main():
    p = argparse.ArgumentParser(
        prog="karaoke-ass",
        description="Apply and verify the two-row karaoke subtitle template.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("import", help="merge karaoke-timed lyrics into a template")
    sp.set_defaults(fn=lambda a, rest: _forward(
        __import__("karaoke_ass.import_lyrics", fromlist=["main"]).main,
        "import", rest))

    sp = sub.add_parser("emfix", help="set the font correction factor in a template")
    sp.set_defaults(fn=lambda a, rest: _forward(
        __import__("karaoke_ass.set_emfix", fromlist=["main"]).main, "emfix", rest))

    sp = sub.add_parser("font-metrics", help="show how each engine sizes a font")
    sp.set_defaults(fn=lambda a, rest: _forward(
        __import__("karaoke_ass.font_metrics", fromlist=["main"]).main,
        "font-metrics", rest))

    sp = sub.add_parser("apply", help="apply the template headlessly")
    sp.add_argument("source")
    sp.add_argument("output")
    sp.add_argument("--renderer-metrics", action="store_true",
                    help="measure in the renderer's convention instead of the "
                         "editor's (diagnostics only)")
    sp.set_defaults(fn=cmd_apply)

    sp = sub.add_parser("check", help="run both checkers over an applied file")
    sp.add_argument("source")
    sp.add_argument("applied")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(fn=cmd_check)

    sp = sub.add_parser("check-layout", help="wipe-edge drift and ruby centring")
    sp.set_defaults(fn=lambda a, rest: _forward(
        __import__("karaoke_ass.check_layout", fromlist=["main"]).main,
        "check-layout", rest))

    sp = sub.add_parser("check-frame", help="report ink that leaves the frame")
    sp.set_defaults(fn=lambda a, rest: _forward(
        __import__("karaoke_ass.check_frame", fromlist=["main"]).main,
        "check-frame", rest))

    sp = sub.add_parser("measure", help="text measurement backend (internal)")
    sp.set_defaults(fn=lambda a, rest: _forward(
        __import__("karaoke_ass.measure", fromlist=["main"]).main, "measure", rest))

    args, rest = p.parse_known_args()
    return args.fn(args, rest)


if __name__ == "__main__":
    sys.exit(main())
