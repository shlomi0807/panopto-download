# Panopto Lecture Downloader 🎓

A Python automation script that downloads Panopto lectures in the highest available quality for offline viewing.

**Disclaimer:** This tool does NOT bypass DRM or any access controls. It simply automates the process of fetching the exact same authenticated stream URLs your browser requests when you watch a lecture, and reassembles them into a single video file. You must already have authorized access to the lecture via your university account.

## 🚀 How to Use (Step-by-Step)

1. **Run the script** using your preferred method (Terminal, PyCharm, VS code etc.).
2. **Paste the Panopto URL** of the lecture you want to download.
3. **Set the save location:** Paste the directory path where you want to save the download (or simply press `ENTER` to save it directly to your Desktop).
4. **Select Moodle:** In the browser window that pops up, select **moodle 4.5**.
5. **Log in** using your Moodle username and password.
6. Sit back! **The download will start automatically** once the video loads.

---

## 🛠️ Prerequisites & Installation

On your first use, you must install the required dependencies. **After installation, please close and reopen your terminal or IDE.**

Run the following commands in your terminal (Windows):

```bash
pip install playwright requests
playwright install chromium
winget install Gyan.FFmpeg