# Panopto Lecture Downloader 🎓

A tool that downloads Panopto lectures in the highest available quality for offline viewing.

You can use it in two ways:

- **Download the ready-made app** (no Python needed), or
- **Run the Python script yourself** (if you prefer, or if you're on Linux / an Intel Mac).

**Disclaimer:** This tool does NOT bypass DRM or any access controls. It simply automates the process of fetching the exact same authenticated stream URLs your browser requests when you watch a lecture, and reassembles them into regular video files. You must already have authorized access to the lecture via your university account.

---

## ✨ Features

- Always downloads the **highest available quality** (e.g. 1080p), automatically.
- Detects **all video streams** of a lecture (for example camera + screen share) and saves each one as its own file.
- Saves everything into a **folder named after the lecture**.
- **Remembers your save location** between runs.
- After each download it asks whether you want to **download another lecture**, so you don't need to restart the program.
- **Stays logged in:** you only need to log in to your university account once.
- **ffmpeg is bundled** in the app, so there is nothing extra to install.

---

## 📥 Option 1: Download the app (easiest)

1. Go to the [**Releases page**](https://github.com/shlomi0807/panopto-download/releases) and download the latest file for your system:
   - **Windows:** `panopto_download-Windows.exe`
   - **macOS (Apple Silicon, M1 and newer):** `panopto_download-macOS`
2. Make sure **Google Chrome** (or Microsoft Edge on Windows) is installed.
3. Run the file and follow the steps in [How to use](#-how-to-use).

### "Windows protected your PC" (SmartScreen)

The app is not digitally signed yet, so Windows may show a blue warning on the first run. This is expected for new open-source tools. To continue:

1. Click **More info**.
2. Click **Run anyway**.

If you'd rather not run an unsigned file, use [Option 2](#-option-2-run-the-python-script) and run the script directly, or build the app yourself from the source code.

### macOS notes

- Chrome must be installed.
- The first time, macOS may block the file. Right-click it and choose **Open**, or run in Terminal:
  ```bash
  xattr -d com.apple.quarantine ./panopto_download-macOS
  chmod +x ./panopto_download-macOS
  ```
- Intel Macs: please use Option 2.

---

## 🐍 Option 2: Run the Python script

**Requirements:** Python 3.9+ and Google Chrome (or Microsoft Edge). ffmpeg is optional: if it's installed it will be used, otherwise a bundled copy is used.

```bash
git clone https://github.com/shlomi0807/panopto-download.git
cd panopto-download
pip install -r requirements.txt
python panopto_download.py
```

**Notes:**
- On Linux, or if you have neither Chrome nor Edge, also run once: `python -m playwright install chromium`
- On newer Linux / macOS (Homebrew Python) `pip install` may fail with `externally-managed-environment`. Use a virtual environment:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```
- If you run it from PyCharm / VS Code and it reports that ffmpeg is missing, close and reopen the IDE, or set `FFMPEG_PATH` at the top of `panopto_download.py` to the full path of your ffmpeg.

---

## 🚀 How to use

1. **Run the app / script.**
2. **Choose the save location:** paste a folder path, or press `ENTER` to use the remembered location (Desktop on the first run).
3. **Paste the Panopto lecture URL** (the `Viewer.aspx?id=...` page).
4. A browser window opens. **Log in** to your university account if asked (for example through Moodle).
5. If the lecture doesn't start playing by itself, **press Play**.
6. Wait. The download starts automatically once the streams are detected, and shows its progress.
7. When it finishes, you'll find the files in a folder named after the lecture:

   ```
   <save location>/
   └── <Lecture name>/
       ├── Video 1.mp4      (e.g. camera)
       └── Video 2.mp4      (e.g. screen share)
   ```
   A lecture with a single stream is saved as `<Lecture name>.mp4`.
8. The program asks **"Download another lecture?"**. Press `ENTER` to continue with another URL, or `n` to exit.

---

## 🧰 Troubleshooting

| Problem | What to do |
|---|---|
| `No video stream was detected` | Make sure the lecture actually started playing in the browser window, then try again. |
| `ffmpeg was not found` | Run `pip install imageio-ffmpeg`, or install ffmpeg (`winget install Gyan.FFmpeg` / `brew install ffmpeg`), then reopen your terminal. |
| `No supported browser could be launched` | Install Google Chrome (or Microsoft Edge on Windows). |
| Asked to log in again | Normal if you cleared browser data. The login is stored in a separate profile used only by this tool. |
| Windows SmartScreen warning | See [above](#windows-protected-your-pc-smartscreen). |

---

## 🔧 Build the app yourself

PyInstaller can't build for other systems, so build on the system you need:

```bash
pip install pyinstaller imageio-ffmpeg playwright requests
pyinstaller --onefile --collect-all playwright --collect-all imageio_ffmpeg panopto_download.py
```

The result is in `dist/`.

This repository also includes a GitHub Actions workflow (`.github/workflows/build.yml`) that builds the Windows and macOS versions automatically. To publish a new release, push a version tag:

```bash
git tag v1.1
git push --tags
```

---

## 📁 Where settings are stored

- **Settings** (your save location) and the **browser login profile** are stored outside this project, in `%LOCALAPPDATA%\PanoptoDownloader` on Windows, or `~/.panopto_downloader` on macOS / Linux. They are never uploaded to GitHub.