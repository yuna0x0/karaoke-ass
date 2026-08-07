"""Platform bits shared by the Python tools: where the probe binary lives,
where to scratch, and how to turn a font name into a font file.

Font lookup prefers fontconfig (fc-match) when present, because that is what
most Linux setups and Homebrew installs have. Where fontconfig is absent
(a plain Windows install, a bare macOS box) it falls back to walking the
system font directories and reading each file's `name` table.
"""
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

WINDOWS = platform.system() == "Windows"

# repo root when running from a checkout; falls back gracefully once installed
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def probe_path():
    """Path to the assprobe binary, with a useful error if it isn't built."""
    exe = "assprobe.exe" if WINDOWS else "assprobe"
    cand = [os.environ.get("KARA_ASSPROBE"),
            os.path.join(ROOT, "bin", exe),
            shutil.which(exe)]
    for p in cand:
        if p and os.path.exists(p):
            return p
    sys.exit("assprobe is not built. Run `make` in the repository root "
             "(see docs/advanced.md), or set KARA_ASSPROBE to its path.")


def workdir(name="karaoke-ass"):
    d = os.path.join(tempfile.gettempdir(), name)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- font lookup

def _fc_match(name):
    try:
        r = subprocess.run(
            ["fc-match", "-f", "%{file}\t%{index}\t%{family}", ":family=" + name],
            capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    parts = r.stdout.split("\t")
    if len(parts) < 2 or not parts[0]:
        return None
    return parts[0], int(parts[1] or 0), (parts[2] if len(parts) > 2 else "")


def _font_dirs():
    home = os.path.expanduser("~")
    if WINDOWS:
        return [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""),
                             "Microsoft", "Windows", "Fonts")]
    if platform.system() == "Darwin":
        return ["/System/Library/Fonts", "/Library/Fonts",
                os.path.join(home, "Library/Fonts")]
    return ["/usr/share/fonts", "/usr/local/share/fonts",
            os.path.join(home, ".local/share/fonts"),
            os.path.join(home, ".fonts")]


def _names_in(path, index=0):
    """Family names declared by a font file (name IDs 1 and 16)."""
    from .font_metrics import tables
    try:
        t = tables(path, index)
        nm = t.get("name")
        if not nm:
            return []
    except Exception:
        return []
    count, str_off = struct.unpack(">HH", nm[2:6])
    out = []
    for i in range(count):
        rec = 6 + 12 * i
        if rec + 12 > len(nm):
            break
        pid, eid, lid, nid, ln, off = struct.unpack(">HHHHHH", nm[rec:rec + 12])
        if nid not in (1, 16):
            continue
        raw = nm[str_off + off:str_off + off + ln]
        try:
            out.append(raw.decode("utf-16-be" if pid in (0, 3) else "latin-1"))
        except Exception:
            pass
    return out


def _scan_match(name):
    want = "".join(c for c in name.lower() if c.isalnum())
    for d in _font_dirs():
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if not f.lower().endswith((".otf", ".ttf", ".ttc", ".otc")):
                    continue
                p = os.path.join(root, f)
                for idx in range(4):
                    names = _names_in(p, idx)
                    if not names:
                        break
                    for n in names:
                        if "".join(c for c in n.lower() if c.isalnum()) == want:
                            return p, idx, ",".join(names)
    return None


def find_font(name):
    """Font family name -> (path, face index, declared families).

    Returns (None, 0, "") when nothing matches.
    """
    hit = _fc_match(name)
    if hit:
        return hit
    hit = _scan_match(name)
    if hit:
        return hit
    return None, 0, ""
