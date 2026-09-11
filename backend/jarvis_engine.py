#!/usr/bin/env python3
"""
Jarvis Engine — Local Backend Execution Layer
================================================
Runs inside Termux on the device (http://127.0.0.1:5000) and gives the
Capacitor/HTML dashboard a local REST bridge to:
  - talk to the cloud LLM (OpenAI-compatible Cloudflare Worker endpoint)
  - execute rooted shell commands via Magisk (`su -c ...`)
  - drive the screen with uiautomator2 for app/UI automation
  - synthesize speech locally with edge-tts and play it back
  - keep device storage clean with a scheduled temp-file sweep

This file is meant to be started with:
    python backend/jarvis_engine.py

Everything here only talks to 127.0.0.1 and the configured LLM endpoint —
it does not open any inbound network port beyond localhost, and every
device-control action runs with the permissions the *user* already
granted their own phone via Magisk root.
"""

import os
import re
import glob
import json
import shlex
import shutil
import asyncio
import logging
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

from flask import Flask, request, jsonify

# --------------------------------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------------------------------

API_BASE_URL = "https://brain-api.faizanxhah150.workers.dev/v1"
API_KEY = "sk-faizan-ai"
LLM_MODEL = "openai/gpt-oss-120b"

HOST = "127.0.0.1"
PORT = 5000

TTS_VOICE = "ur-PK-UzmaNeural"

TMP_AUDIO_DIR = os.path.expanduser("~/.cache/jarvis")
CLEAN_PATHS = [
    "/sdcard/.tmp/*",
    "/data/local/tmp/*",
    os.path.expanduser("~/.cache/*"),
]

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jarvis")

app = Flask(__name__)

STATE = {
    "started_at": datetime.now().isoformat(),
    "requests_handled": 0,
    "last_error": None,
    "root_available": None,
    "uiautomator2_connected": False,
}

# --------------------------------------------------------------------------
# 2. ROOT SHELL EXECUTION
# --------------------------------------------------------------------------


def run_root_shell(command: str, timeout: int = 20) -> dict:
    """
    Executes a shell command with root privileges via Magisk (`su -c`).
    Returns dict with stdout/stderr/returncode. Never raises — errors are
    captured and returned so the caller (and the LLM) can react to them.
    """
    try:
        full_cmd = ["su", "-c", command]
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "su binary not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "command timed out"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}


def check_root_available() -> bool:
    res = run_root_shell("id", timeout=5)
    STATE["root_available"] = res["ok"] and "uid=0" in res["stdout"]
    return STATE["root_available"]


def open_app(package_name: str) -> dict:
    """Launch an installed app by package name using the root monkey command."""
    cmd = f"monkey -p {shlex.quote(package_name)} -c android.intent.category.LAUNCHER 1"
    return run_root_shell(cmd)


def tap_screen(x: int, y: int) -> dict:
    """Root-level fallback tap using `input tap` (works even without uiautomator2)."""
    return run_root_shell(f"input tap {int(x)} {int(y)}")


def swipe_screen(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> dict:
    return run_root_shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")


# --------------------------------------------------------------------------
# 3. UIAUTOMATOR2 SCREEN CONTROL
# --------------------------------------------------------------------------
# uiautomator2 gives us reliable element-based control (find by text/id,
# not just raw coordinates). It's optional at import time so the rest of
# the engine still works if the device isn't connected yet.

_u2_device = None


def get_u2_device():
    """Lazily connects to the local device over uiautomator2. Cached after first success."""
    global _u2_device
    if _u2_device is not None:
        return _u2_device
    try:
        import uiautomator2 as u2

        _u2_device = u2.connect()  # connects to the local/default device
        STATE["uiautomator2_connected"] = True
        log.info("uiautomator2 connected: %s", _u2_device.info)
        return _u2_device
    except Exception as exc:
        STATE["uiautomator2_connected"] = False
        log.warning("uiautomator2 not available: %s", exc)
        return None


def u2_click_text(text: str) -> dict:
    d = get_u2_device()
    if not d:
        return {"ok": False, "error": "uiautomator2 unavailable"}
    try:
        el = d(text=text)
        if el.exists(timeout=3):
            el.click()
            return {"ok": True}
        return {"ok": False, "error": f'element with text "{text}" not found'}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def u2_click_xy(x: int, y: int) -> dict:
    d = get_u2_device()
    if not d:
        return tap_screen(x, y)  # fall back to root `input tap`
    try:
        d.click(x, y)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def u2_type_text(text: str) -> dict:
    d = get_u2_device()
    try:
        if d:
            d.send_keys(text, clear=False)
            return {"ok": True}
        # Fallback: root `input text` (spaces must be escaped as %s)
        escaped = text.replace(" ", "%s")
        return run_root_shell(f"input text {shlex.quote(escaped)}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def press_back() -> dict:
    return run_root_shell("input keyevent 4")


def press_home() -> dict:
    return run_root_shell("input keyevent 3")


def read_screen_text() -> dict:
    """
    Lets the agent 'see' the current screen (element text + positions)
    via uiautomator2's UI hierarchy dump, so it can decide what to tap
    next or notice something went wrong and self-correct.
    """
    d = get_u2_device()
    if not d:
        return {"ok": False, "error": "uiautomator2 unavailable"}
    try:
        info = d.dump_hierarchy(compressed=True)
        return {"ok": True, "hierarchy_xml_excerpt": info[:4000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --- App name -> package resolution ---------------------------------

COMMON_APP_ALIASES = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "instagram": "com.instagram.android",
    "chrome": "com.android.chrome",
    "browser": "com.android.chrome",
    "settings": "com.android.settings",
    "camera": "com.android.camera",
    "gallery": "com.miui.gallery",
    "photos": "com.google.android.apps.photos",
    "phone": "com.android.dialer",
    "dialer": "com.android.dialer",
    "contacts": "com.android.contacts",
    "maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm",
    "facebook": "com.facebook.katana",
    "tiktok": "com.zhiliaoapp.musically",
    "twitter": "com.twitter.android",
    "x": "com.twitter.android",
    "telegram": "org.telegram.messenger",
    "spotify": "com.spotify.music",
    "playstore": "com.android.vending",
    "play store": "com.android.vending",
}

_installed_packages_cache = {"list": None, "ts": 0}


def list_installed_packages() -> list:
    now = time.time()
    if _installed_packages_cache["list"] is not None and now - _installed_packages_cache["ts"] < 300:
        return _installed_packages_cache["list"]
    res = run_root_shell("pm list packages", timeout=15)
    pkgs = []
    if res["ok"]:
        for line in res["stdout"].splitlines():
            if line.startswith("package:"):
                pkgs.append(line[len("package:"):].strip())
    _installed_packages_cache["list"] = pkgs
    _installed_packages_cache["ts"] = now
    return pkgs


def resolve_package(name: str) -> str | None:
    """Best-effort: turn a spoken app name ('YouTube', 'whatsapp') into an
    installed package name, using a known-alias table first, then a
    substring match against every installed package."""
    key = name.strip().lower()
    if key in COMMON_APP_ALIASES:
        return COMMON_APP_ALIASES[key]
    if "." in key:  # looks like a package name already
        return name.strip()
    for pkg in list_installed_packages():
        if key.replace(" ", "") in pkg.lower():
            return pkg
    return None


# --------------------------------------------------------------------------
# 3.5 HIGH-LEVEL DEVICE ACTIONS (used by both the regex fast-path and the
# LLM tool-calling agent loop below)
# --------------------------------------------------------------------------


def action_open_app(app_name: str) -> dict:
    pkg = resolve_package(app_name)
    if not pkg:
        return {"ok": False, "error": f'could not find an installed app matching "{app_name}"'}
    result = open_app(pkg)
    result["resolved_package"] = pkg
    return result


def action_open_website(url: str) -> dict:
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return run_root_shell(f"am start -a android.intent.action.VIEW -d {shlex.quote(url)}")


def action_search_web(query: str) -> dict:
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    return action_open_website(url)


def action_open_settings(section: str = "") -> dict:
    intent = {
        "wifi": "android.settings.WIFI_SETTINGS",
        "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
        "apps": "android.settings.APPLICATION_SETTINGS",
        "display": "android.settings.DISPLAY_SETTINGS",
        "battery": "android.settings.BATTERY_SAVER_SETTINGS",
        "location": "android.settings.LOCATION_SOURCE_SETTINGS",
        "": "android.settings.SETTINGS",
    }.get(section.strip().lower(), "android.settings.SETTINGS")
    return run_root_shell(f"am start -a {intent}")


def action_make_call(number: str) -> dict:
    digits = re.sub(r"[^0-9+]", "", number)
    if not digits:
        return {"ok": False, "error": "no valid phone number given"}
    return run_root_shell(f"am start -a android.intent.action.CALL -d tel:{digits}")


def action_run_shell(command: str, timeout: int = 60) -> dict:
    """
    General-purpose Termux/root shell execution — this is what lets the
    agent do the 'self-healing' workflow the user asked for: run a real
    command (pip install, git clone, gradle build, file ops, whatever),
    see the actual stdout/stderr/exit code, and — because this result
    goes straight back into the tool-call loop in call_llm() — the model
    can read the error and retry with a corrected command itself instead
    of just reporting failure back to the user.
    """
    # Raised ceiling (10 min) so real work — gradle builds, big pip/npm
    # installs, git clones — has room to actually finish instead of
    # getting killed mid-way.
    timeout = max(5, min(int(timeout or 60), 600))
    return run_root_shell(command, timeout=timeout)


def action_get_device_status() -> dict:
    """Live device diagnostics so the agent can 'see' what's actually
    wrong (low storage, battery, wifi down) before deciding what to fix."""
    battery = run_root_shell("dumpsys battery | grep -E 'level|status'", timeout=10)
    storage = run_root_shell("df -h /data /sdcard 2>/dev/null", timeout=10)
    wifi = run_root_shell("dumpsys wifi | grep -m1 'Wi-Fi is'", timeout=10)
    return {
        "ok": True,
        "battery": battery.get("stdout", ""),
        "storage": storage.get("stdout", ""),
        "wifi": wifi.get("stdout", ""),
        "root_available": STATE.get("root_available"),
        "uiautomator2_connected": STATE.get("uiautomator2_connected"),
        "last_error": STATE.get("last_error"),
    }


# --------------------------------------------------------------------------
# 4. LLM CALL (OpenAI-compatible Cloudflare Worker) — with tool-calling
#    agent loop so the model can actually DO things, not just talk.
# --------------------------------------------------------------------------
def build_persona_system_prompt(agent_name: str, mode: str) -> str:
    """
    Builds the system message that gives the LLM its identity. This is
    what makes "call it whatever name you set in the app" actually work:
    the name typed into the dashboard is injected here on every request,
    not hard-coded anywhere.
    """
    mode_hint = {
        "responsive": "Wait for the user's command before acting; keep replies concise.",
        "proactive": "Feel free to proactively suggest next steps after finishing a task.",
        "silent": "Keep spoken replies very short — the user prefers minimal talking.",
    }.get(mode, "")

    return (
        f"You are {agent_name}, a personal AI voice assistant with full control of the "
        f"user's own Android phone (they rooted it themselves and granted you this "
        f"access on purpose). Always respond as {agent_name} — never say you are a "
        f"generic AI/language model. Reply in the same language/script the user used "
        f"(Roman Urdu, Urdu, Hindi, or English) in a natural, conversational tone. "
        f"{mode_hint} "
        f"When the user asks you to DO something on the phone (open an app, open a "
        f"website, search something, call someone, change a setting, tap/type on "
        f"screen), use the provided tools to actually do it — don't just describe it. "
        f"If a tool call fails or returns an error, read the error, adjust, and try "
        f"again yourself (e.g. a different app name, a corrected coordinate, a fixed "
        f"shell command) instead of asking the user to fix it, unless you're truly "
        f"stuck after a couple of tries — you have a run_shell_command tool for "
        f"anything else (installing things, running scripts, checking logs) and a "
        f"get_device_status tool to diagnose problems first. You will never use these "
        f"tools to automatically like, subscribe to, or comment on other people's "
        f"content without the user explicitly dictating the exact action each time — "
        f"that would be spam/bot behaviour and is off limits. Once a task is done (or "
        f"you give up), reply with a short natural confirmation, not a tool call."
    )


# Tool schema in OpenAI's function-calling format. If the LLM endpoint
# doesn't support tool calling, these are simply ignored and the model
# replies with plain text (handled gracefully below).
DEVICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open an installed app by its common name (e.g. 'YouTube', 'WhatsApp', 'Settings').",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Open a URL/website in the browser.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the given query on Google in the browser.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_settings",
            "description": "Open the device Settings app, optionally a specific section.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "One of: wifi, bluetooth, apps, display, battery, location, or empty for the main settings screen.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_call",
            "description": "Place a phone call to a number.",
            "parameters": {
                "type": "object",
                "properties": {"number": {"type": "string"}},
                "required": ["number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tap",
            "description": "Tap the screen at pixel coordinates x,y.",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swipe",
            "description": "Swipe the screen from x1,y1 to x2,y2.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x1": {"type": "integer"},
                    "y1": {"type": "integer"},
                    "x2": {"type": "integer"},
                    "y2": {"type": "integer"},
                },
                "required": ["x1", "y1", "x2", "y2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_text",
            "description": "Tap the on-screen element that contains this exact visible text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text into the currently focused input field on screen.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "go_back",
            "description": "Press the Android back button.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "go_home",
            "description": "Press the Android home button.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_screen",
            "description": "Read what's currently on screen (element text/positions) so you can decide what to tap next, or check whether a previous action worked.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": (
                "Run any Termux/root shell command directly (pip install, git clone, file "
                "management, checking logs, building things, etc.). Use this for anything "
                "the other tools don't cover. If it errors, read the stderr and try a "
                "corrected command yourself before giving up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "description": "Max 600, default 60. Use a higher value for builds/installs that take a while."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_status",
            "description": "Check live device health: battery, storage space, wifi status, root/automation availability. Use this to diagnose problems before fixing them.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name: str, args: dict) -> dict:
    """Dispatches a single tool call from the LLM to the matching device
    action, always returning a JSON-serialisable result (success or a
    clear error) so the model can see what actually happened."""
    try:
        if name == "open_app":
            return action_open_app(args.get("app_name", ""))
        if name == "open_website":
            return action_open_website(args.get("url", ""))
        if name == "search_web":
            return action_search_web(args.get("query", ""))
        if name == "open_settings":
            return action_open_settings(args.get("section", ""))
        if name == "make_call":
            return action_make_call(args.get("number", ""))
        if name == "tap":
            return u2_click_xy(int(args.get("x", 0)), int(args.get("y", 0)))
        if name == "swipe":
            return swipe_screen(
                int(args.get("x1", 0)), int(args.get("y1", 0)),
                int(args.get("x2", 0)), int(args.get("y2", 0)),
            )
        if name == "click_text":
            return u2_click_text(args.get("text", ""))
        if name == "type_text":
            return u2_type_text(args.get("text", ""))
        if name == "go_back":
            return press_back()
        if name == "go_home":
            return press_home()
        if name == "read_screen":
            return read_screen_text()
        if name == "run_shell_command":
            return action_run_shell(args.get("command", ""), args.get("timeout_seconds", 60))
        if name == "get_device_status":
            return action_get_device_status()
        return {"ok": False, "error": f"unknown tool '{name}'"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


MAX_AGENT_STEPS = 10


def call_llm(prompt: str, agent_name: str = "Jarvis", mode: str = "responsive", history: list | None = None) -> tuple[str, list]:
    """
    Runs the persona + prompt through the LLM with tool-calling enabled.
    If the model requests tool calls, executes them via the device
    action functions above, feeds the results back, and loops (so it
    can chain multiple steps and self-correct on errors) until it
    returns a final natural-language reply or MAX_AGENT_STEPS is hit.

    Returns (final_reply_text, list_of_executed_actions).
    """
    messages = [{"role": "system", "content": build_persona_system_prompt(agent_name, mode)}]
    for turn in (history or [])[-20:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    executed_actions = []

    for _ in range(MAX_AGENT_STEPS):
        payload = {"model": LLM_MODEL, "messages": messages, "tools": DEVICE_TOOLS, "tool_choice": "auto"}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE_URL}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"LLM call failed: {exc}") from exc

        choice = body["choices"][0]["message"]
        tool_calls = choice.get("tool_calls")

        if not tool_calls:
            # Plain text reply — the model is done (or the endpoint
            # doesn't support tool calling at all, which degrades
            # gracefully to a normal chat reply).
            return choice.get("content") or "", executed_actions

        # The model wants to act: run every requested tool call, log it,
        # and feed the results back so it can continue/self-correct.
        messages.append(choice)
        for call in tool_calls:
            fn = call.get("function", {})
            fn_name = fn.get("name", "")
            try:
                fn_args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            result = execute_tool(fn_name, fn_args)
            executed_actions.append({"tool": fn_name, "args": fn_args, "result": result})

            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps(result),
            })

    # Ran out of steps — ask it to wrap up in plain text.
    messages.append({"role": "user", "content": "Please summarize what you did so far in one short reply."})
    payload = {"model": LLM_MODEL, "messages": messages}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE_URL}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"].get("content") or "", executed_actions
    except Exception:
        return "Kaam ho gaya.", executed_actions


# --------------------------------------------------------------------------
# 5. TEXT-TO-SPEECH (edge-tts) + PLAYBACK
# --------------------------------------------------------------------------


def synthesize_and_play(text: str) -> dict:
    """
    Converts `text` to speech with edge-tts (ur-PK-UzmaNeural) and plays it
    back via mpv (falls back to ffplay if mpv isn't installed).
    """
    if not text:
        return {"ok": False, "error": "empty text"}

    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)
    out_path = os.path.join(TMP_AUDIO_DIR, f"tts_{int(time.time() * 1000)}.mp3")

    try:
        import edge_tts

        async def _gen():
            communicate = edge_tts.Communicate(text, TTS_VOICE)
            await communicate.save(out_path)

        asyncio.run(_gen())
    except Exception as exc:
        return {"ok": False, "error": f"tts generation failed: {exc}"}

    player = shutil.which("mpv") or shutil.which("ffplay")
    if not player:
        return {"ok": False, "error": "no audio player (mpv/ffplay) found on PATH", "file": out_path}

    try:
        if "mpv" in player:
            subprocess.run([player, "--no-terminal", "--really-quiet", out_path], timeout=60)
        else:
            subprocess.run([player, "-nodisp", "-autoexit", "-loglevel", "quiet", out_path], timeout=60)
        return {"ok": True, "file": out_path}
    except Exception as exc:
        return {"ok": False, "error": f"playback failed: {exc}", "file": out_path}


# --------------------------------------------------------------------------
# 6. AUTOMATED STORAGE MAINTENANCE
# --------------------------------------------------------------------------


def auto_clean_failed_cache():
    """
    Deletes temp files from /sdcard/.tmp/*, /data/local/tmp/*, and
    ~/.cache/* so leftover TTS clips / scratch files don't fill up
    storage over time. Runs after every /process cycle and on error.
    """
    cleaned = []
    for pattern in CLEAN_PATHS:
        if pattern.startswith("/sdcard") or pattern.startswith("/data/local/tmp"):
            # These need root to touch reliably on most ROMs.
            res = run_root_shell(f"rm -rf {pattern}", timeout=10)
            cleaned.append({"path": pattern, "ok": res["ok"], "via": "root"})
        else:
            try:
                for f in glob.glob(pattern):
                    if os.path.isfile(f):
                        os.remove(f)
                    elif os.path.isdir(f):
                        shutil.rmtree(f, ignore_errors=True)
                cleaned.append({"path": pattern, "ok": True, "via": "local"})
            except Exception as exc:
                cleaned.append({"path": pattern, "ok": False, "error": str(exc), "via": "local"})
    log.info("auto_clean_failed_cache: %s", cleaned)
    return cleaned


def _cleanup_scheduler(interval_seconds: int = 900):
    """Background thread: also sweeps temp files every 15 min regardless of activity."""
    while True:
        time.sleep(interval_seconds)
        try:
            auto_clean_failed_cache()
        except Exception as exc:
            log.warning("scheduled cleanup failed: %s", exc)


# --------------------------------------------------------------------------
# 7. COMMAND ROUTING — turn an LLM reply / raw prompt into device actions
# --------------------------------------------------------------------------
# Very small, explicit action grammar so the LLM (or the user directly)
# can trigger device control without arbitrary code execution. Extend the
# ACTION_PATTERNS table to teach Jarvis new actions.

ACTION_PATTERNS = [
    (re.compile(r"^open\s+app\s+(\S+)$", re.I), lambda m: action_open_app(m.group(1))),
    (re.compile(r"^tap\s+(\d+)\s*,?\s*(\d+)$", re.I), lambda m: u2_click_xy(int(m.group(1)), int(m.group(2)))),
    (re.compile(r"^click\s+text\s+(.+)$", re.I), lambda m: u2_click_text(m.group(1).strip())),
    (re.compile(r"^swipe\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$", re.I), lambda m: swipe_screen(*[int(g) for g in m.groups()])),
    (re.compile(r"^open\s+(?:website\s+|site\s+)?(https?://\S+|\S+\.\S+)$", re.I), lambda m: action_open_website(m.group(1))),
    (re.compile(r"^search\s+(?:for\s+)?(.+)$", re.I), lambda m: action_search_web(m.group(1).strip())),
    (re.compile(r"^(?:open\s+)?settings(?:\s+(\w+))?$", re.I), lambda m: action_open_settings(m.group(1) or "")),
    (re.compile(r"^call\s+([0-9+\-\s]+)$", re.I), lambda m: action_make_call(m.group(1).strip())),
    (re.compile(r"^(?:go\s+)?back$", re.I), lambda m: press_back()),
    (re.compile(r"^(?:go\s+)?home$", re.I), lambda m: press_home()),
]


def strip_wake_name(prompt: str, agent_name: str) -> str:
    """Removes a leading 'AgentName, ' / 'AgentName:' prefix so saved
    action patterns still match even when the user addresses Jarvis by
    its custom name first (e.g. 'Nexus, tap 500 300')."""
    pattern = re.compile(rf"^\s*{re.escape(agent_name)}\s*[,:]?\s*", re.I)
    return pattern.sub("", prompt, count=1)


def try_execute_device_action(text: str):
    """If `text` matches a known device-action pattern, execute it. Returns
    the action result dict, or None if nothing matched (i.e. it's just a
    conversational prompt for the LLM)."""
    stripped = text.strip()
    for pattern, handler in ACTION_PATTERNS:
        m = pattern.match(stripped)
        if m:
            return handler(m)
    return None


# --------------------------------------------------------------------------
# 8. REST ENDPOINTS
# --------------------------------------------------------------------------


@app.route("/status", methods=["GET"])
def status():
    STATE["requests_handled"] += 1
    return jsonify(
        {
            "ok": True,
            "state": "running",
            "started_at": STATE["started_at"],
            "requests_handled": STATE["requests_handled"],
            "root_available": STATE["root_available"],
            "uiautomator2_connected": STATE["uiautomator2_connected"],
            "llm_model": LLM_MODEL,
            "tts_voice": TTS_VOICE,
            "last_error": STATE["last_error"],
        }
    )


@app.route("/process", methods=["POST"])
def process():
    """
    Main entry point from the dashboard: { "prompt": "..." }
    1. If the prompt matches a known device-action pattern, execute it
       directly (no LLM round-trip needed).
    2. Otherwise, send it to the LLM, speak the reply with edge-tts, and
       return the reply text to the UI.
    Always finishes with a cache sweep, win or lose.
    """
    STATE["requests_handled"] += 1
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    agent_name = (body.get("agent_name") or "Jarvis").strip() or "Jarvis"
    mode = (body.get("mode") or "responsive").strip()
    history = body.get("history") or []

    if not prompt:
        return jsonify({"ok": False, "error": "missing 'prompt'"}), 400

    try:
        action_result = try_execute_device_action(strip_wake_name(prompt, agent_name))
        if action_result is not None:
            return jsonify({"ok": True, "type": "action", "action_result": action_result})

        reply_text, executed_actions = call_llm(prompt, agent_name=agent_name, mode=mode, history=history)
        tts_result = synthesize_and_play(reply_text)

        return jsonify(
            {
                "ok": True,
                "type": "chat",
                "reply": reply_text,
                "actions": executed_actions,
                "tts": tts_result,
            }
        )
    except Exception as exc:
        STATE["last_error"] = str(exc)
        log.exception("error handling /process")
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        auto_clean_failed_cache()


@app.route("/action", methods=["POST"])
def action():
    """
    Lower-level escape hatch for direct device control from the UI, e.g.
    { "type": "open_app", "package": "com.whatsapp" }
    { "type": "tap", "x": 500, "y": 900 }
    { "type": "swipe", "x1":.., "y1":.., "x2":.., "y2":.. }
    """
    body = request.get_json(silent=True) or {}
    kind = body.get("type")
    try:
        if kind == "open_app":
            result = open_app(body["package"])
        elif kind == "tap":
            result = u2_click_xy(body["x"], body["y"])
        elif kind == "swipe":
            result = swipe_screen(body["x1"], body["y1"], body["x2"], body["y2"], body.get("duration_ms", 300))
        elif kind == "click_text":
            result = u2_click_text(body["text"])
        else:
            return jsonify({"ok": False, "error": f"unknown action type '{kind}'"}), 400
        return jsonify({"ok": True, "result": result})
    except KeyError as exc:
        return jsonify({"ok": False, "error": f"missing field {exc}"}), 400
    finally:
        auto_clean_failed_cache()


# --------------------------------------------------------------------------
# 9. STARTUP
# --------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Jarvis engine starting on http://%s:%s", HOST, PORT)
    check_root_available()
    get_u2_device()  # best-effort; failure is non-fatal
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)

    threading.Thread(target=_cleanup_scheduler, daemon=True).start()

    app.run(host=HOST, port=PORT, debug=False, threaded=True)
