# Jarvis — Autonomous AI Voice Assistant & Android Device Controller

Two-tier system:
1. **Frontend (real native APK)** — Capacitor-wrapped HTML/CSS/JS dashboard (`www/`) + native Kotlin/Java plugins (`android/`) for real Android permissions and a real system-wide floating avatar overlay.
2. **Backend (Termux)** — `backend/jarvis_engine.py`, a local Flask server on `http://127.0.0.1:5000` with an LLM tool-calling agent loop: it doesn't just chat, it actually controls the device and can run arbitrary shell commands to get real work done (installs, builds, fixes its own errors).

---

## What's real here (not a mockup)

| Area | How it's real |
|---|---|
| **Permissions** | `PermissionPlugin.java` calls genuine Android APIs — root grant is the actual Magisk `su` prompt; overlay/accessibility/storage/battery open the real system Settings screens; mic uses Capacitor's real runtime-permission flow. Tapping a permission row fires a real request, not a fake "PENDING" label. |
| **Floating avatar** | `OverlayService.java` is a foreground service drawing a `WindowManager` view above every app (like Messenger chat heads) — it keeps running after you close the app. No avatar picked → nothing shows on screen, only a silent low-priority notification. |
| **Persona/name** | Whatever you type in the "Agent Name" field is sent with every request and becomes the LLM's actual system-prompt identity — it responds *as* that name, not a hardcoded one. |
| **Conversation memory** | Last 20 turns are stored client-side and replayed to the LLM, so it's a real back-and-forth conversation, not single-shot Q&A. |
| **Full device control** | The LLM has real tools — `open_app`, `open_website`, `search_web`, `open_settings`, `make_call`, `tap`, `swipe`, `click_text`, `type_text`, `go_back`, `go_home`, `read_screen` — and decides which to call from your plain-language request. |
| **Background wake-word listening** | `BackgroundListenerService.java` runs a silent, continuous speech-recognition loop even when the app is closed — no popup, no dialog, just a minimal low-priority notification (Android requires *some* visible notification for background mic use — that's an OS security rule, not a choice). Say whatever name you set in the Agent Name field ("Jarvis", "Nexus", anything) followed by a command, and it forwards straight to the backend. |
| **Talk to Jarvis (in-app)** | A text box + mic button in the dashboard for typing or speaking commands directly, with the conversation shown as chat bubbles. |
| **Natural voice, not robotic** | Every reply — chat *and* direct device actions — is spoken aloud via edge-tts's neural voice (`ur-PK-UzmaNeural`), played through the Termux side with mpv. This is a proper neural TTS voice, not the flat robotic Android system TTS. |
| **Self-healing / Termux automation** | `run_shell_command` lets the agent run *any* real Termux/root command itself (installs, git clone, gradle builds, fixes). If a command errors, the stderr goes straight back to the model in the same loop, so it corrects itself and retries — you don't type Termux commands manually anymore, you just describe the task. |
| **Device diagnostics** | `get_device_status` gives the agent live battery/storage/wifi/root health so it can diagnose before it fixes. |
| **API config** | Uses exactly the endpoint/key/model you specified — unchanged: `brain-api.faizanxhah150.workers.dev`, key `sk-faizan-ai`, model `openai/gpt-oss-120b`. |
| **No spam automation** | The persona explicitly refuses to auto-like/subscribe/comment on other people's content without you dictating the exact action each time — that's bot/spam behaviour and stays off-limits by design. |

---

## Repository layout

```
jarvis-assistant/
├── .github/workflows/build-apk.yml   # Auto-builds + releases app-debug.apk on push to main
├── android/                          # REAL native Android project (generated + hand-written plugins)
│   └── app/src/main/java/com/jarvis/assistant/
│       ├── MainActivity.java
│       ├── PermissionPlugin.java     # real permission requests
│       ├── OverlayService.java       # real system-wide floating overlay
│       ├── OverlayPlugin.java        # JS <-> OverlayService bridge
│       └── JarvisAccessibilityService.java
├── www/
│   ├── index.html
│   ├── css/style.css
│   └── js/{storage,permissions,bridge,overlay,settings,app}.js
├── backend/
│   ├── jarvis_engine.py              # Flask REST bridge + LLM tool-calling agent + device control + TTS
│   └── requirements.txt
├── capacitor.config.json
└── package.json
```

---

## 1. Install the app

1. Push this repo to GitHub (with `contents: write` permission enabled under **Settings → Actions → General → Workflow permissions**) → Actions builds `app-debug.apk` and attaches it to a Release.
2. Install the APK on the Redmi Note 9.
3. Open the app and go through **Permissions** — each tap now opens a real system dialog (Magisk root prompt, overlay settings, accessibility settings, mic prompt, all-files-access, battery exemption).

## 2. Set up the Termux backend

```bash
su
# tap "Grant" on the real Magisk prompt

pkg update -y
pkg install python android-tools ffmpeg mpv -y
pip install -r backend/requirements.txt
```

## 3. Start the engine

```bash
python backend/jarvis_engine.py
```

Leave it running (tmux/screen, or Termux:Boot for autostart).

## 4. Use it

Open the app, type/say your assistant's name once in the Agent Name field, pick an avatar (optional — skip it for zero on-screen UI, just the background service), press Start. From then on just describe what you want:

- *"YouTube khol do"* → opens YouTube
- *"is number pe call karo 03001234567"* → places the call
- *"is repo ko clone karke APK build kar do"* → agent runs `git clone`, installs whatever's missing, runs the Gradle build, and reports back — reading and fixing its own errors along the way
- *"battery aur storage check karo"* → live device status back in the chat

---

## Backend API reference

| Endpoint | Method | Body | Purpose |
|---|---|---|---|
| `/status` | GET | – | Health check, root/uiautomator2 state |
| `/process` | POST | `{"prompt","agent_name","mode","history"}` | Runs the LLM tool-calling agent loop; returns `{"reply","actions","tts"}` |
| `/action` | POST | `{"type": "open_app"/"tap"/"swipe"/"click_text", ...}` | Direct low-level device control escape hatch |

Storage cleanup (`/sdcard/.tmp/*`, `/data/local/tmp/*`, `~/.cache/*`) runs automatically after every request and every 15 minutes in the background.

---

## Notes / limits (read before relying on this)

- I can't compile/run a real Android Gradle build in the environment I built this in (no Android SDK access there) — every file has been syntax/structure-checked by hand, but the **first real compile happens in your GitHub Actions run**. If it fails, send me the exact error and I'll fix it immediately.
- Real lip-sync (mouth moving with speech) is not included — on a Redmi Note 9 with no GPU, models like Wav2Lip are impractical. The avatar has a gentle idle sway/bob instead.
- The agent will not auto-like/subscribe/comment on other users' content by itself — that's excluded on purpose.

