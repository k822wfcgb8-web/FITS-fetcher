"""System folder dialog for the settings panel (REQ-65).

A web page can't read real paths from the browser's picker, so the local server opens the operating
system's own dialog: AppleScript `choose folder` on macOS, a WinForms FolderBrowserDialog on Windows,
zenity or kdialog on Linux. Returns None when the user cancels.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class NoFolderDialog(Exception):
    """No folder dialog is available on this system; the user types the path instead."""


def _applescript_text(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def command(prompt: str, initial: str) -> list[str]:
    start = Path(initial).expanduser()
    while not start.is_dir() and start != start.parent:
        start = start.parent
    if sys.platform == "darwin":
        # `activate` brings osascript's dialog in front of the browser without asking for automation permission.
        return ["osascript", "-e", "activate", "-e",
                f"POSIX path of (choose folder with prompt {_applescript_text(prompt)} "
                f"default location (POSIX file {_applescript_text(str(start))}))"]
    if sys.platform == "win32":
        ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
              f"$d.Description = '{prompt.replace(chr(39), chr(39) * 2)}'; "
              f"$d.SelectedPath = '{str(start).replace(chr(39), chr(39) * 2)}'; "
              "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath } else { exit 1 }")
        return ["powershell", "-NoProfile", "-STA", "-Command", ps]
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", "--directory", f"--title={prompt}", f"--filename={start}/"]
    if shutil.which("kdialog"):
        return ["kdialog", "--getexistingdirectory", str(start), "--title", prompt]
    raise NoFolderDialog("No folder dialog is available here; type the path instead.")


def choose_folder(prompt: str, initial: str) -> str | None:
    r = subprocess.run(command(prompt, initial), capture_output=True, text=True)
    if r.returncode != 0:
        return None  # cancelled (macOS returns error -128, the others exit 1)
    path = r.stdout.strip()
    return path.rstrip("/") or "/" if path else None
