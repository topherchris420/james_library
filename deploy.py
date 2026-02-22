"""Cross-platform service installer for james_library OpenClaw supervisor."""

from __future__ import annotations

import argparse
import getpass
import platform
import subprocess
import sys
from pathlib import Path

from openclaw_service import pick_headless_python


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install james_library as a persistent service")
    parser.add_argument("--service-name", default="james-library")
    parser.add_argument("--target", default="rain_lab.py", help="Python script managed by OpenClaw")
    parser.add_argument("--target-args", nargs=argparse.REMAINDER, default=[])
    parser.add_argument("--dry-run", action="store_true", help="Only print generated files/commands")
    return parser.parse_args(argv)


def _run(cmd: list[str], dry_run: bool, *, allow_failure: bool = False) -> None:
    print("$", " ".join(cmd))
    if not dry_run:
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            if allow_failure:
                print(f"Ignoring non-zero exit status for optional command: {' '.join(cmd)}")
                return
            raise


def _windows_install(repo_root: Path, args: argparse.Namespace, dry_run: bool) -> None:
    wrapper = repo_root / "openclaw_service.py"
    headless_python = pick_headless_python()
    clean_target_args = args.target_args[1:] if args.target_args[:1] == ["--"] else args.target_args
    target_args = ["--", *clean_target_args] if clean_target_args else []
    nssm_install_cmd = [
        "nssm",
        "install",
        args.service_name,
        headless_python,
        str(wrapper),
        "--service-name",
        args.service_name,
        "--target",
        args.target,
        *target_args,
    ]
    nssm_dir_cmd = ["nssm", "set", args.service_name, "AppDirectory", str(repo_root)]
    nssm_start_cmd = ["nssm", "start", args.service_name]

    _run(nssm_install_cmd, dry_run)
    _run(nssm_dir_cmd, dry_run)
    _run(nssm_start_cmd, dry_run)


def _macos_install(repo_root: Path, args: argparse.Namespace, dry_run: bool) -> None:
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    label = f"com.james_library.{args.service_name}"
    plist_path = launch_agents / f"{label}.plist"
    wrapper = repo_root / "openclaw_service.py"

    program_args = [
        pick_headless_python(),
        str(wrapper),
        "--service-name",
        args.service_name,
        "--target",
        args.target,
    ]
    clean_target_args = args.target_args[1:] if args.target_args[:1] == ["--"] else args.target_args
    if clean_target_args:
        program_args.extend(["--", *clean_target_args])

    args_xml = "\n".join(f"      <string>{arg}</string>" for arg in program_args)
    plist = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{repo_root}</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{repo_root / 'logs' / 'openclaw.out.log'}</string>
    <key>StandardErrorPath</key>
    <string>{repo_root / 'logs' / 'openclaw.err.log'}</string>
  </dict>
</plist>
"""

    print(f"Writing plist: {plist_path}")
    if not dry_run:
        (repo_root / "logs").mkdir(exist_ok=True)
        plist_path.write_text(plist, encoding="utf-8")

    # First install has nothing loaded yet; unload may fail and is safe to ignore.
    _run(["launchctl", "unload", str(plist_path)], dry_run, allow_failure=True)
    _run(["launchctl", "load", str(plist_path)], dry_run)


def _linux_install(repo_root: Path, args: argparse.Namespace, dry_run: bool) -> None:
    unit_path = Path("/etc/systemd/system") / f"{args.service_name}.service"
    wrapper = repo_root / "openclaw_service.py"
    clean_target_args = args.target_args[1:] if args.target_args[:1] == ["--"] else args.target_args
    target_tail = " -- " + " ".join(clean_target_args) if clean_target_args else ""
    service_text = f"""[Unit]
Description=james_library OpenClaw background service
After=network.target

[Service]
Type=simple
User={getpass.getuser()}
WorkingDirectory={repo_root}
ExecStart={pick_headless_python()} {wrapper} --service-name {args.service_name} --target {args.target}{target_tail}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

    print(f"Writing systemd unit: {unit_path}")
    if not dry_run:
        (repo_root / "logs").mkdir(exist_ok=True)
        unit_path.write_text(service_text, encoding="utf-8")

    _run(["systemctl", "daemon-reload"], dry_run)
    _run(["systemctl", "enable", "--now", args.service_name], dry_run)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    os_name = platform.system().lower()

    print(f"Detected platform: {os_name}")
    if os_name == "windows":
        _windows_install(repo_root, args, args.dry_run)
    elif os_name == "darwin":
        _macos_install(repo_root, args, args.dry_run)
    elif os_name == "linux":
        _linux_install(repo_root, args, args.dry_run)
    else:
        raise RuntimeError(f"Unsupported operating system: {platform.system()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
