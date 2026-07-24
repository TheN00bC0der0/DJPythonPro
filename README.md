Add files via upload
# 🎧 Python DJ Pro Workstation

A feature-rich, desktop DJ mixing application built with Python, featuring dual mixing decks, custom audio signal processing, live audio-reactive background visuals (raindrops and lightning), and a mobile-friendly web request server!

---

## 🚀 Features

* **Dual Deck Mixing**: Load, play, pause, blend, and crossfade audio tracks.
* **Audio-Reactive Backgrounds**: Dynamic visualizers featuring real-time raindrops and interactive lightning effects driven by your audio intensity.
* **Mobile Request Server**: Built-in Flask server with dynamic QR code generation so guests can submit track requests directly from their phones.
* **Playlist Utilities**: Automated random pool generation and batch track management.
* **Cross-Platform**: Designed to run smoothly on both macOS and Windows.

---

## 🛠️ Prerequisites

Before running the application, make sure you have the following installed on your system:
* **Python 3.10+** (Ensure Python is added to your system PATH during installation).
* **pip** (Python package manager).

---

## 📦 Installation & Setup

1. **Clone or Download the Repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git](https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git)
   cd YOUR_REPOSITORY_NAME
or download dj_mixerexperemtnal.py and place in a folder.
-----------------------------------------------------------------------------------------
Install Required Dependencies:
Install the necessary Python libraries using pip:

Bash
pip install pygame flask qrcode pillow
(Note: Depending on your specific audio and tunneling setup, you may also need libraries like ngrok if you are hosting the web request server publicly).

2.

Configure Ngrok:
Make sure your Ngrok authtoken is configured on your machine so the app can generate public URLs for the QR code:

Bash

ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN

3.

On Windows
For the best experience on Windows, you can create a simple batch file to launch the application easily.

Create a new file named run_dj.bat in the project folder.

Add the following lines to the .bat file:

DOS
@echo off
echo Starting Python DJ Pro Workstation...
python dj_mixerexperemtnal.py
pause
Double-click run_dj.bat to start the program.

(Alternatively, just run python dj_mixerexperemtnal.py in your Command Prompt).

4.

On macOS
Open your Terminal, navigate to the project folder, and execute the script:

Bash
python3 dj_mixerexperemtnal.py

🎮 How to Use the App
Main Mixer: Load your local audio folders into the library, assign tracks to your decks, and use the central controls to mix and blend your audio.

View Utilities: Click the ⚙️ icon in the bottom-right corner to hide the main mixer and open the Extras drawer.

Web Requests: In the Extras drawer, you will find the auto-generated QR code. Guests can scan this to access the Flask web interface and drop track requests straight into your inbox queue.

Visuals Control: Use the visual toggle buttons in the utilities tab to switch between the raindrop effect and the lightning bolts (lightning triggers on hard audio hits!).

Return to Deck: Click the 🔙 BACK button to return to your main DJ workstation view.

5.

chrome book install Linux terminal and bash the following commands. 
create enviorment:python3 -m venv dj_env

Activate env:
source dj_env/bin/activate
Run code:
python3 dj_mixer.py
Experemental updates:
python3 dj_mixerexperemtnal.py

6. keep a copy of Dj_mixer.py for back up if you would like to experiment with your station. 

7. Dj_pro.desktop file must be altered to put your location of the file to run it in the correct directory.  specifically the execution line and the path.
