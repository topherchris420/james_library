"""R.A.I.N. Rig settings shared with the Rust runtime.

Reads the optional ``[rig]`` table from the same ``config.toml`` the ``rain``
runtime uses, so the Python meeting honours ``[rig] privacy = "local"`` and
the persisted ``[rig.meeting]`` endpoint/model.

Precedence for the meeting endpoint and model:
explicit environment variables > ``[rig.meeting]`` > the caller's default.

Without a ``[rig]`` table nothing changes: privacy is ``hybrid`` and no check
is enforced. Locality mirrors ``src/providers/locality.rs``: IP literals and
``localhost`` are classified directly; any other hostname is resolved and is
local only when every address is loopback or private; lookup failure is
remote (fail closed).
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

PRIVACY_MODES = ("local", "hybrid", "hosted")
PROFILES = ("local", "node", "field")
REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO_ROOT / "src" / "config" / "schema" / "rig_profiles"

Resolver = Callable[[str], Optional[list]]


class RigPrivacyError(RuntimeError):
    """Raised when local-only privacy refuses a hosted meeting endpoint or model."""


@dataclass(frozen=True)
class RigSettings:
    privacy: Optional[str] = None
    profile: Optional[str] = None
    meeting_base_url: Optional[str] = None
    meeting_model: Optional[str] = None
    config_path: Optional[Path] = None

    def effective_privacy(self) -> tuple[str, str]:
        """Return ``(mode, source)`` exactly as the Rust runtime resolves it."""
        if self.privacy:
            return self.privacy, "explicit"
        if self.profile:
            return _profile_privacy(self.profile), "profile"
        return "hybrid", "default"


# ── Config discovery (mirrors resolve_runtime_config_dirs in Rust) ──────────


def _home(env: Mapping[str, str]) -> Path:
    home = env.get("HOME") or env.get("USERPROFILE")
    return Path(home) if home else Path.home()


def resolve_config_path(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Locate ``config.toml``: rain_CONFIG_DIR > rain_WORKSPACE > active marker > default."""
    env = os.environ if env is None else env
    default_dir = _home(env) / ".R.A.I.N."
    config_dir = (env.get("rain_CONFIG_DIR") or "").strip()
    if config_dir:
        candidate = Path(config_dir).expanduser() / "config.toml"
        return candidate if candidate.is_file() else None
    workspace = (env.get("rain_WORKSPACE") or "").strip()
    if workspace:
        ws = Path(workspace).expanduser()
        for candidate in (ws / "config.toml", ws.parent / ".R.A.I.N." / "config.toml"):
            if candidate.is_file():
                return candidate
        return None
    marker = default_dir / "active_workspace.toml"
    if marker.is_file():
        match = re.search(r'^\s*config_dir\s*=\s*"([^"]*)"', marker.read_text(encoding="utf-8"), re.M)
        if match:
            candidate = Path(match.group(1)).expanduser() / "config.toml"
            if candidate.is_file():
                return candidate
    candidate = default_dir / "config.toml"
    return candidate if candidate.is_file() else None


# ── Parsing ─────────────────────────────────────────────────────────────────

_TABLE_RE = re.compile(r"^\s*\[\s*([A-Za-z0-9_.\-]+)\s*\]\s*(#.*)?$")
_ARRAY_TABLE_RE = re.compile(r"^\s*\[\[\s*[A-Za-z0-9_.\-]+\s*\]\]\s*(#.*)?$")
_KV_RE = re.compile(r"""^\s*([A-Za-z0-9_\-]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(#.*)?$""")
# ``rig = {...}`` or ``rig.privacy = ...`` at the top level.
_TOP_LEVEL_RIG_RE = re.compile(r"^\s*rig\s*[.=]")
_RIG_HEADER_LIKE_RE = re.compile(r"^\s*\[+\s*[\"']?rig\b")
_BLANK_OR_COMMENT_RE = re.compile(r"^\s*(#.*)?$")


def _parse_rig_tables_minimal(text: str) -> dict:
    """Extract string keys of ``[rig]`` / ``[rig.meeting]`` (Python < 3.11 fallback).

    Strict so that anything it cannot read fails closed instead of silently
    dropping privacy settings: malformed table headers, top-level ``rig``
    keys (inline or dotted), and non-string values inside ``[rig]`` or
    ``[rig.meeting]`` raise ``ValueError``.
    """
    tables: dict = {"rig": {}, "rig.meeting": {}}
    current = None
    for number, line in enumerate(text.splitlines(), start=1):
        header = _TABLE_RE.match(line)
        if header:
            current = header.group(1)
            continue
        if _ARRAY_TABLE_RE.match(line):
            current = None
            continue
        if _RIG_HEADER_LIKE_RE.match(line):
            raise ValueError(f"line {number}: malformed or unsupported [rig] table header")
        if line.lstrip().startswith("["):
            # Some other construct (quoted header, nested array line): stop
            # attributing keys to [rig] rather than guess.
            current = None
            continue
        if current is None and _TOP_LEVEL_RIG_RE.match(line):
            raise ValueError(f"line {number}: write [rig] as a table (inline/dotted rig keys need Python 3.11+)")
        if current not in tables or _BLANK_OR_COMMENT_RE.match(line):
            continue
        pair = _KV_RE.match(line)
        if not pair:
            raise ValueError(f"line {number}: [{current}] values must be quoted strings")
        value = pair.group(2) if pair.group(2) is not None else pair.group(3)
        tables[current][pair.group(1)] = value.replace('\\"', '"').replace("\\\\", "\\")
    rig = dict(tables["rig"])
    if tables["rig.meeting"]:
        rig["meeting"] = dict(tables["rig.meeting"])
    return rig


def parse_rig_table(text: str) -> dict:
    """Return the ``[rig]`` table (with nested ``meeting``) from config text."""
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10
        return _parse_rig_tables_minimal(text)
    rig = tomllib.loads(text).get("rig", {})
    return rig if isinstance(rig, dict) else {}


def _clean(value: object, allowed: Optional[tuple] = None) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if allowed is not None and value.lower() not in allowed:
        raise RigPrivacyError(f"invalid [rig] value {value!r}; expected one of {', '.join(allowed)}")
    return value.lower() if allowed is not None else value


def load_rig_settings(env: Optional[Mapping[str, str]] = None, path: Optional[Path] = None) -> RigSettings:
    """Load ``[rig]`` settings. Missing config or table means pre-Rig defaults.

    A config that declares a ``[rig`` table but cannot be parsed fails closed
    (``RigPrivacyError``); configs without Rig settings are never an error here.
    """
    path = path or resolve_config_path(env)
    if path is None:
        return RigSettings()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return RigSettings(config_path=path)
    try:
        rig = parse_rig_table(text)
    except Exception as exc:  # malformed TOML
        if re.search(r"^\s*(\[\s*rig\b|rig\s*[.=])", text, re.M):
            raise RigPrivacyError(f"cannot parse [rig] in {path}: {exc}") from exc
        return RigSettings(config_path=path)
    meeting = rig.get("meeting") if isinstance(rig.get("meeting"), dict) else {}
    return RigSettings(
        privacy=_clean(rig.get("privacy"), PRIVACY_MODES),
        profile=_clean(rig.get("profile"), PROFILES),
        meeting_base_url=_clean(meeting.get("base_url")),
        meeting_model=_clean(meeting.get("model")),
        config_path=path,
    )


def _profile_privacy(profile: str) -> str:
    """Privacy default declared by a built-in profile file; ``local`` if unreadable."""
    try:
        text = (PROFILE_DIR / f"{profile}.toml").read_text(encoding="utf-8")
    except OSError:
        return "local"
    match = re.search(r'^\s*privacy\s*=\s*"([a-z]+)"', text, re.M)
    value = match.group(1) if match else "local"
    return value if value in PRIVACY_MODES else "local"


# ── Locality ────────────────────────────────────────────────────────────────

_PRIVATE_V4 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]
_PRIVATE_V6 = [ipaddress.ip_network(n) for n in ("fc00::/7", "fe80::/10")]


def classify_ip(ip: "ipaddress._BaseAddress") -> str:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback"
    networks = _PRIVATE_V4 if isinstance(ip, ipaddress.IPv4Address) else _PRIVATE_V6
    return "private" if any(ip in net for net in networks) else "remote"


def system_resolve(host: str) -> Optional[list]:
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return None
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
    return addresses or None


def classify_host(host: str, resolver: Resolver = system_resolve) -> str:
    bare = host.strip().strip("[]").rstrip(".").lower()
    if bare == "localhost":
        return "loopback"
    try:
        return classify_ip(ipaddress.ip_address(bare))
    except ValueError:
        pass
    addresses = resolver(bare) or []
    if not addresses:
        return "remote"
    kinds = {classify_ip(address) for address in addresses}
    if "remote" in kinds:
        return "remote"
    return "private" if "private" in kinds else "loopback"


def classify_url(url: str, resolver: Resolver = system_resolve) -> str:
    try:
        host = urlparse(url.strip()).hostname
    except ValueError:
        return "remote"
    return classify_host(host, resolver) if host else "remote"


# ── Meeting settings and enforcement ───────────────────────────────────────


def meeting_base_url(default: str, env: Optional[Mapping[str, str]] = None,
                     settings: Optional[RigSettings] = None) -> str:
    env = os.environ if env is None else env
    explicit = (env.get("RAIN_LLM_BASE_URL") or env.get("LM_STUDIO_BASE_URL") or "").strip()
    if explicit:
        return explicit
    settings = settings if settings is not None else _safe_settings(env)
    return settings.meeting_base_url or default


def meeting_model(default: str, env: Optional[Mapping[str, str]] = None,
                  settings: Optional[RigSettings] = None) -> str:
    env = os.environ if env is None else env
    explicit = (env.get("RAIN_LLM_MODEL") or env.get("LM_STUDIO_MODEL") or "").strip()
    if explicit:
        return explicit
    settings = settings if settings is not None else _safe_settings(env)
    return settings.meeting_model or default


def _safe_settings(env: Mapping[str, str]) -> RigSettings:
    # Defaults must never crash import-time code; enforcement re-reads strictly.
    try:
        return load_rig_settings(env)
    except RigPrivacyError:
        return RigSettings()


def enforce_meeting_privacy(base_url: str, model: str, *, env: Optional[Mapping[str, str]] = None,
                            settings: Optional[RigSettings] = None,
                            resolver: Resolver = system_resolve) -> str:
    """Fail closed when ``[rig]`` privacy is ``local`` and the meeting would be hosted.

    Returns the effective privacy mode. Raises ``RigPrivacyError`` otherwise.
    """
    settings = settings if settings is not None else load_rig_settings(env)
    mode, source = settings.effective_privacy()
    if mode != "local":
        return mode
    origin = f"[rig] privacy = \"local\" ({source}{', ' + str(settings.config_path) if settings.config_path else ''})"
    if model.strip().endswith(":cloud"):
        raise RigPrivacyError(
            f"{origin} refuses the meeting model {model!r}: Ollama ':cloud' models run on a hosted "
            "service. Set RAIN_LLM_MODEL (or [rig.meeting] model) to a local model, or set "
            "[rig] privacy = \"hybrid\"."
        )
    locality = classify_url(base_url, resolver)
    if locality == "remote":
        host = urlparse(base_url).hostname or "(invalid URL)"
        raise RigPrivacyError(
            f"{origin} refuses the meeting endpoint host {host}: it is not loopback or "
            "private-network. Point RAIN_LLM_BASE_URL (or [rig.meeting] base_url) at a local "
            "server, or set [rig] privacy = \"hybrid\"."
        )
    return mode
