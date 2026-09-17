import os
import socket
import tkinter as tk
from tkinter import filedialog
import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import sys
import qrcode
import json
import time
from PIL import Image, ImageTk
from pyngrok import ngrok
from flask import Flask, request, render_template_string
import librosa
import random
import shutil

# --- 🗂️ Config & Setup 🗂️ ---
TRACK_DIR = "dj_tracks"
PLAYLIST_DIR = "dj_playlists" 
SAMPLE_DIR = "dj_samples" 
NOTESHEET_DIR = "dj_notesheets"
os.makedirs(TRACK_DIR, exist_ok=True) 
os.makedirs(PLAYLIST_DIR, exist_ok=True) 
os.makedirs(SAMPLE_DIR, exist_ok=True)
os.makedirs(NOTESHEET_DIR, exist_ok=True)

mixer = {
    'vol_a': 1.0, 'vol_b': 1.0, 'mic_vol': 0.8,
    'pos_a': 0, 'pos_b': 0,
    'playing_a': False, 'playing_b': False,
    'repeat_a': False, 'repeat_b': False,
    'crossfade': 0.0, 'master_vol': 1.0,
    'track_a_loaded': False, 'track_b_loaded': False,
    'blending': False, 'auto_dj': False,
    'playhead_id_a': None, 'playhead_id_b': None,
    'mic_on': False,
    'last_notesheet_A': None, 'last_notesheet_B': None,
    'file_a': None, 'file_b': None
}

deck_a_data = np.zeros((48000, 2), dtype='float32')
deck_b_data = np.zeros((48000, 2), dtype='float32')

# Thread lock to prevent race conditions when reading/writing the metadata cache
cache_lock = threading.Lock()

# --- ✨ Sampler Data & Engine ---
active_samples = [] 
samples_data = {}

def generate_synth_beep(freq, duration=0.5):
    t = np.linspace(0, duration, int(48000 * duration), False)
    wave = np.sin(freq * t * 2 * np.pi) * 0.3 
    return np.column_stack((wave, wave)).astype('float32')

# Base frequencies for the 8 pads
freqs = [261.6, 329.6, 392.0, 523.2, 130.8, 146.8, 164.8, 196.0] 
for i in range(1, 9):
    file_path = os.path.join(SAMPLE_DIR, f"sample_{i}.wav")
    if os.path.exists(file_path):
        try:
            data, fs = sf.read(file_path, dtype='float32')
            if data.ndim == 1: data = np.column_stack((data, data))
            if fs != 48000: data = librosa.resample(data.T, orig_sr=fs, target_sr=48000).T
            samples_data[str(i)] = data
        except Exception:
            samples_data[str(i)] = generate_synth_beep(freqs[i-1])
    else:
        samples_data[str(i)] = generate_synth_beep(freqs[i-1])

def play_sample(pad_num):
    active_samples.append({'data': samples_data[pad_num], 'pos': 0})

def assign_sample(pad_num):
    filepath = filedialog.askopenfilename(initialdir=".", title=f"Select Audio for Pad {pad_num}", filetypes=[("Audio Files", "*.wav *.mp3")])
    if filepath:
        try:
            y, sr = librosa.load(filepath, sr=48000, mono=False)
            if y.ndim == 1: y = np.vstack((y, y)) 
            samples_data[str(pad_num)] = y.T.astype('float32') 
            
            dest = os.path.join(SAMPLE_DIR, f"sample_{pad_num}.wav")
            sf.write(dest, y.T, 48000)
            print(f"✅ Pad {pad_num} loaded successfully!")
        except Exception as e:
            print(f"⚠️ Error loading sample: {e}")

# --- 🌐 Flask Web Server 🌐 ---
def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

FLASK_PORT = get_free_port()
flask_app = Flask(__name__)
incoming_messages = [] 

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DJ Requests</title>
    <style>
        body { background-color: #f4f4f9; color: #333333; font-family: Arial, sans-serif; text-align: center; padding: 20px; margin: 0; }
        .container { max-width: 400px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
        h2 { color: #ff00cc; }
        input, select, button { width: 100%; box-sizing: border-box; padding: 12px; margin-top: 10px; margin-bottom: 10px; border: 2px solid #ccc; border-radius: 5px; font-size: 16px; }
        button { background: #00ffcc; color: #121212; font-weight: bold; border: none; cursor: pointer; text-transform: uppercase;}
    </style>
</head>
<body>
    <div class="container">
        <h2>🎶 DJ BOOTH REQUESTS 🎶</h2>
        <form action="/submit" method="POST">
            <label><b>Search Library:</b></label>
            <input type="text" id="searchBox" onkeyup="filterSongs()" placeholder="Type to filter tracks...">
            <label><b>Pick a track:</b></label>
            <select name="library_song" id="songSelect">
                <option value="">-- Choose a track --</option>
                {% for song in songs %}
                <option value="{{ song }}">{{ song }}</option>
                {% endfor %}
            </select>
            <input type="text" name="custom_msg" placeholder="Custom request (e.g. Play Freebird!)">
            <input type="text" name="sender_name" placeholder="Your Name">
            <button type="submit">SEND TO DJ</button>
        </form>
    </div>
    <script>
        let allOptions = [];
        document.addEventListener("DOMContentLoaded", function() {
            let select = document.getElementById('songSelect');
            for (let i = 1; i < select.options.length; i++) {
                allOptions.push(select.options[i].cloneNode(true)); 
            }
        });
        function filterSongs() {
            let input = document.getElementById('searchBox').value.toLowerCase();
            let select = document.getElementById('songSelect');
            select.options.length = 1;
            for (let i = 0; i < allOptions.length; i++) {
                if (allOptions[i].text.toLowerCase().includes(input)) {
                    select.add(allOptions[i].cloneNode(true));
                }
            }
        }
    </script>
</body>
</html>
"""

@flask_app.route('/')
def index():
    songs = [f for f in os.listdir(TRACK_DIR) if f.lower().endswith(('.mp3', '.wav'))]
    return render_template_string(HTML_TEMPLATE, songs=songs)

@flask_app.route('/submit', methods=['POST'])
def submit():
    lib_song = request.form.get('library_song', '')
    custom_msg = request.form.get('custom_msg', '')
    name = request.form.get('sender_name', 'Anonymous')
    if lib_song: incoming_messages.append(f"📥 [{name}]: {lib_song}")
    if custom_msg: incoming_messages.append(f"💬 [{name}]: {custom_msg}")
    return "<body style='background:#f4f4f9; text-align:center; padding:50px; font-family:Arial;'><h2 style='color:#ff00cc;'>Sent! The DJ sees it. 🎧</h2><br><a href='/' style='color:#333; font-weight:bold;'>Send another</a></body>"

threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False), daemon=True).start()

# --- 🎧 Real-Time Audio Engine 🎧 ---
def audio_callback(indata, outdata, frames, time_info, status):
    global deck_a_data, deck_b_data, active_samples
    out = np.zeros((frames, 2), dtype='float32')
    cf = mixer['crossfade']
    cf_a_mix = 1.0 if cf <= 0 else 1.0 - cf
    cf_b_mix = 1.0 if cf >= 0 else 1.0 + cf
    
    if mixer['playing_a']:
        end_a = mixer['pos_a'] + frames
        if end_a >= len(deck_a_data):
            if mixer['repeat_a']: mixer['pos_a'] = 0; end_a = frames
            else: mixer['playing_a'] = False
        if mixer['playing_a']:
            chunk_a = deck_a_data[mixer['pos_a']:end_a]
            valid_a = len(chunk_a)
            if valid_a > 0: out[:valid_a] += chunk_a * mixer['vol_a'] * cf_a_mix; mixer['pos_a'] += valid_a
                
    if mixer['playing_b']:
        end_b = mixer['pos_b'] + frames
        if end_b >= len(deck_b_data):
            if mixer['repeat_b']: mixer['pos_b'] = 0; end_b = frames
            else: mixer['playing_b'] = False
        if mixer['playing_b']:
            chunk_b = deck_b_data[mixer['pos_b']:end_b]
            valid_b = len(chunk_b)
            if valid_b > 0: out[:valid_b] += chunk_b * mixer['vol_b'] * cf_b_mix; mixer['pos_b'] += valid_b
                
    if mixer['mic_on']:
        mic_data = indata[:, 0] * mixer['mic_vol']
        out += np.column_stack((mic_data, mic_data))
        
    for samp in active_samples[:]:
        rem = len(samp['data']) - samp['pos']
        valid = min(frames, rem)
        if valid > 0:
            out[:valid] += samp['data'][samp['pos']:samp['pos']+valid]
            samp['pos'] += valid
        if samp['pos'] >= len(samp['data']):
            active_samples.remove(samp)

    out = np.clip(out * mixer.get('master_vol', 1.0), -1.0, 1.0)
    outdata[:] = out

def render_deck_visuals(deck, peaks, bpm, filename):
    if deck == 'A':
        label_track_a.config(text=f"🎵 {filename}  |  ⚡ {bpm} BPM")
        canvas_wave_a.delete("all")
        for x, y in enumerate(peaks):
            h = y * 50 
            canvas_wave_a.create_line(x, 30-h/2, x, 30+h/2, fill="#00ffcc")
        mixer['playhead_id_a'] = canvas_wave_a.create_line(0, 0, 0, 60, fill="#ff00cc", width=2)
    else:
        label_track_b.config(text=f"🎵 {filename}  |  ⚡ {bpm} BPM")
        canvas_wave_b.delete("all")
        for x, y in enumerate(peaks):
            h = y * 50
            canvas_wave_b.create_line(x, 30-h/2, x, 30+h/2, fill="#00ffcc")
        mixer['playhead_id_b'] = canvas_wave_b.create_line(0, 0, 0, 60, fill="#ff00cc", width=2)

# --- 📂 Control & Automation Logic 📂 ---
def analyze_and_save_notes(deck):
    """Analyzes 30 beats of the track, maps pitches to pads, and saves a note sheet."""
    def task():
        if deck == 'A' and not mixer['track_a_loaded']: return
        if deck == 'B' and not mixer['track_b_loaded']: return
        
        btn = btn_notes_a if deck == 'A' else btn_notes_b
        root.after(0, lambda: btn.config(text="⏳ Analyzing...", state="disabled", bg="#555"))
        
        data = deck_a_data if deck == 'A' else deck_b_data
        mono_data = np.mean(data, axis=1)
        
        # Get up to 30 beats for the note sheet sequence
        tempo, beat_frames = librosa.beat.beat_track(y=mono_data, sr=48000)
        if len(beat_frames) > 30:
            beat_frames = beat_frames[:30]
            
        note_sequence = []
        target_freqs = np.array(freqs)
        pad_keys = ['1', '2', '3', '4', '5', '6', '7', '8']
        
        for i in range(len(beat_frames) - 1):
            start = librosa.frames_to_samples(beat_frames[i], hop_length=512)
            end = librosa.frames_to_samples(beat_frames[i+1], hop_length=512)
            segment = mono_data[start:end]
            
            if len(segment) == 0: continue
            
            # Fundamental frequency estimation
            f0 = librosa.yin(segment, fmin=65, fmax=2000, sr=48000)
            valid_f0 = f0[f0 > 0]
            
            if len(valid_f0) > 0:
                med_freq = np.median(valid_f0)
                # Snap to closest pad frequency
                idx = (np.abs(target_freqs - med_freq)).argmin()
                duration_ms = (len(segment) / 48000.0) * 1000
                note_sequence.append({'pad': pad_keys[idx], 'duration': duration_ms})
                
        # Save to JSON
        timestamp = int(time.time())
        out_path = os.path.join(NOTESHEET_DIR, f"notesheet_deck_{deck}_{timestamp}.json")
        with open(out_path, 'w') as f:
            json.dump(note_sequence, f)
            
        mixer[f'last_notesheet_{deck}'] = out_path
        
        def reset_btn():
            btn.config(text="📝 Extract Notes", state="normal", bg="#333333")
            print(f"✅ Notesheet saved to {out_path}")
            
        root.after(0, reset_btn)
        
    threading.Thread(target=task, daemon=True).start()

def play_last_notesheet(deck):
    """Loads and plays the extracted JSON note sheet mapped to the 8 pads."""
    filepath = mixer.get(f'last_notesheet_{deck}')
    
    if not filepath or not os.path.exists(filepath):
        filepath = filedialog.askopenfilename(initialdir=NOTESHEET_DIR, title="Select Note Sheet", filetypes=[("JSON Files", "*.json")])
        if not filepath: return
        
    def task():
        btn = btn_playnotes_a if deck == 'A' else btn_playnotes_b
        root.after(0, lambda: btn.config(text="🎹 Playing...", state="disabled", bg="#ff00cc"))
        
        with open(filepath, 'r') as f:
            sequence = json.load(f)
            
        for note in sequence:
            pad = note['pad']
            play_sample(pad)
            time.sleep(note['duration'] / 1000.0)
            
        root.after(0, lambda: btn.config(text="🎹 Auto-Play Sheet", state="normal", bg="#333333"))
            
    threading.Thread(target=task, daemon=True).start()

def load_audio_file(filepath, deck):
    global deck_a_data, deck_b_data
    try:
        filename = os.path.basename(filepath)
        label_track_a.config(text=f"⏳ Loading RAM & Resampling...") if deck == 'A' else label_track_b.config(text=f"⏳ Loading RAM & Resampling...")
        
        data, fs = sf.read(filepath, dtype='float32')
        if data.ndim == 1: data = np.column_stack((data, data))
        if fs != 48000: data = librosa.resample(data.T, orig_sr=fs, target_sr=48000).T

        # --- BASS DROP DETECTION ---
        mono_for_drop = np.mean(data, axis=1)
        rms = librosa.feature.rms(y=mono_for_drop, frame_length=2048, hop_length=512)[0]
        drop_frame_idx = librosa.frames_to_samples(np.argmax(rms), hop_length=512)
        
        if deck == 'A': 
            deck_a_data = data; mixer['pos_a'] = 0; mixer['playing_a'] = False; mixer['track_a_loaded'] = True
            mixer['drop_idx_a'] = int(drop_frame_idx)
            mixer['file_a'] = filename
            btn_play_a.config(text="▶ Play")
        else: 
            deck_b_data = data; mixer['pos_b'] = 0; mixer['playing_b'] = False; mixer['track_b_loaded'] = True
            mixer['drop_idx_b'] = int(drop_frame_idx)
            mixer['file_b'] = filename
            btn_play_b.config(text="▶ Play")

        cache_file = "dj_track_metadata.json"
        metadata_cache = {}
        
        with cache_lock:
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as f: metadata_cache = json.load(f)
                except Exception: pass

            if filename not in metadata_cache:
                metadata_cache[filename] = {}

        cache_updated = False
        mono_data = None 

        if 'bpm' in metadata_cache[filename]:
            bpm = metadata_cache[filename]['bpm']
        else:
            label_track_a.config(text=f"⏳ Calculating BPM...") if deck == 'A' else label_track_b.config(text=f"⏳ Calculating BPM...")
            mono_data = np.mean(data, axis=1)
            tempo, _ = librosa.beat.beat_track(y=mono_data, sr=48000) 
            bpm = int(np.atleast_1d(tempo)[0]) 
            metadata_cache[filename]['bpm'] = bpm
            cache_updated = True

        if 'peaks' in metadata_cache[filename]:
            peaks = metadata_cache[filename]['peaks']
        else:
            label_track_a.config(text=f"⏳ Drawing Waveform...") if deck == 'A' else label_track_b.config(text=f"⏳ Drawing Waveform...")
            canvas_width = 250
            chunk_size = len(data) // canvas_width
            if mono_data is None: mono_data = np.mean(data, axis=1) 
            
            peaks = [float(np.max(np.abs(mono_data[i*chunk_size:(i+1)*chunk_size]))) for i in range(canvas_width)]
            max_val = max(peaks) if max(peaks) > 0 else 1
            peaks = [p / max_val for p in peaks] 
            metadata_cache[filename]['peaks'] = peaks
            cache_updated = True

        if cache_updated:
            with cache_lock:
                try:
                    with open(cache_file, "w") as f: json.dump(metadata_cache, f)
                except Exception: pass
            
        root.after(0, render_deck_visuals, deck, peaks, bpm, filename)
    except Exception as e: print(f"⚠️ Error: {e}")

def toggle_play(deck):
    if deck == 'A':
        mixer['playing_a'] = not mixer['playing_a']
        btn_play_a.config(text="⏸ Pause" if mixer['playing_a'] else "▶ Play")
    else:
        mixer['playing_b'] = not mixer['playing_b']
        btn_play_b.config(text="⏸ Pause" if mixer['playing_b'] else "▶ Play")
        
def trigger_bass_drop():
    if mixer['playing_a'] and mixer['track_b_loaded']:
        mixer['pos_b'] = mixer['drop_idx_b']
        mixer['crossfade'] = 1.0
        cf_slider.set(1.0)
        mixer['playing_b'] = True
        mixer['playing_a'] = False
        btn_play_b.config(text="⏸ Pause")
        btn_play_a.config(text="▶ Play")
        
    elif mixer['playing_b'] and mixer['track_a_loaded']:
        mixer['pos_a'] = mixer['drop_idx_a']
        mixer['crossfade'] = -1.0
        cf_slider.set(-1.0)
        mixer['playing_a'] = True
        mixer['playing_b'] = False
        btn_play_a.config(text="⏸ Pause")
        btn_play_b.config(text="▶ Play")

def auto_blend():
    if mixer['blending']: return
    mixer['blending'] = True
    
    if mixer['playing_a'] and not mixer['playing_b']: target_val = 1.0
    elif mixer['playing_b'] and not mixer['playing_a']: target_val = -1.0
    else: target_val = 1.0 if mixer['crossfade'] <= 0 else -1.0
        
    step = 0.02 if target_val == 1.0 else -0.02
    
    if target_val == 1.0 and not mixer['playing_b']: toggle_play('B')
    if target_val == -1.0 and not mixer['playing_a']: toggle_play('A')
    
    def blend_step():
        current = mixer['crossfade']
        if (step > 0 and current < target_val) or (step < 0 and current > target_val):
            new_val = max(-1.0, min(1.0, current + step))
            mixer['crossfade'] = new_val; cf_slider.set(new_val)
            root.after(40, blend_step) 
        else:
            mixer['blending'] = False
            if target_val == 1.0: 
                mixer['playing_a'] = False; mixer['track_a_loaded'] = False
                btn_play_a.config(text="▶ Play"); label_track_a.config(text="[No Track Loaded]"); canvas_wave_a.delete("all")
            if target_val == -1.0: 
                mixer['playing_b'] = False; mixer['track_b_loaded'] = False
                btn_play_b.config(text="▶ Play"); label_track_b.config(text="[No Track Loaded]"); canvas_wave_b.delete("all")
    blend_step()

def pick_random_library_track(exclude=None):
    """Grabs a random track from the library folder, avoiding the one already on the other deck when possible."""
    try:
        files = [f for f in os.listdir(TRACK_DIR) if f.lower().endswith(('.mp3', '.wav'))]
    except Exception:
        files = []
    if not files:
        return None
    if exclude:
        candidates = [f for f in files if f != exclude]
        if candidates:
            files = candidates
    return random.choice(files)

def toggle_auto_dj():
    mixer['auto_dj'] = not mixer['auto_dj']
    btn_autodj.config(bg="#ff00cc" if mixer['auto_dj'] else "#333333", text="🤖 AUTO-DJ: ON" if mixer['auto_dj'] else "🤖 AUTO-DJ: OFF")

def load_from_queue(deck):
    if queue_listbox.size() > 0:
        idx = queue_listbox.curselection()
        target_idx = idx[0] if idx else 0 
        selected = queue_listbox.get(target_idx)
        queue_listbox.delete(target_idx) 
        threading.Thread(target=load_audio_file, args=(os.path.join(TRACK_DIR, selected), deck), daemon=True).start()

def scrub_audio(event, deck):
    jump_size = 4800 
    if deck == 'A':
        if event.x > 125: mixer['pos_a'] = min(len(deck_a_data)-1, mixer['pos_a'] + jump_size)
        elif event.x < 125: mixer['pos_a'] = max(0, mixer['pos_a'] - jump_size)
    else:
        if event.x > 125: mixer['pos_b'] = min(len(deck_b_data)-1, mixer['pos_b'] + jump_size)
        elif event.x < 125: mixer['pos_b'] = max(0, mixer['pos_b'] - jump_size)

def save_playlist():
    if queue_listbox.size() == 0: return 
    filepath = filedialog.asksaveasfilename(initialdir=PLAYLIST_DIR, title="Save Playlist", defaultextension=".json", filetypes=[("JSON Files", "*.json")])
    if filepath:
        tracks = queue_listbox.get(0, tk.END)
        with open(filepath, 'w') as f: json.dump(tracks, f)

def load_playlist():
    filepath = filedialog.askopenfilename(initialdir=PLAYLIST_DIR, title="Load Playlist", filetypes=[("JSON Files", "*.json")])
    if filepath:
        try:
            with open(filepath, 'r') as f: tracks = json.load(f)
            queue_listbox.delete(0, tk.END)
            for t in tracks: queue_listbox.insert(tk.END, t)
        except Exception as e: print(f"⚠️ Error loading playlist: {e}")

def generate_bpm_playlist():
    def analysis_task():
        btn_utils.config(text="⏳ Checking Track Database...", state="disabled", bg="#555555")
        
        try: pool_size = int(pool_var.get())
        except ValueError: pool_size = 50
        try: target_len = int(length_var.get())
        except ValueError: target_len = 15

        files = [f for f in os.listdir(TRACK_DIR) if f.lower().endswith(('.mp3', '.wav'))]
        random.shuffle(files)
        files = files[:pool_size] 
        
        cache_file = "dj_track_metadata.json"
        metadata_cache = {}
        with cache_lock:
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as f: metadata_cache = json.load(f)
                except Exception: pass
        
        track_data = []
        cache_updated = False
        
        for f in files:
            if f in metadata_cache and 'bpm' in metadata_cache[f] and 'key' in metadata_cache[f]:
                track_dict = metadata_cache[f].copy()
                track_dict['file'] = f
                track_data.append(track_dict)
            else:
                btn_utils.config(text=f"⏳ Analyzing NEW track: {f[:15]}...")
                try:
                    y, sr = librosa.load(os.path.join(TRACK_DIR, f), duration=30, sr=22050)
                    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                    bpm = float(np.atleast_1d(tempo)[0])
                    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
                    key = int(np.argmax(np.sum(chroma, axis=1)))
                    
                    if f not in metadata_cache: metadata_cache[f] = {}
                    metadata_cache[f]['bpm'] = bpm
                    metadata_cache[f]['key'] = key
                    metadata_cache[f]['file'] = f 
                    
                    track_data.append({'file': f, 'bpm': bpm, 'key': key})
                    cache_updated = True
                except Exception: pass
                
        if cache_updated:
            with cache_lock:
                try:
                    with open(cache_file, "w") as f: json.dump(metadata_cache, f)
                except Exception: pass

        if not track_data:
            root.after(0, lambda: btn_utils.config(text="⚡ Auto-Build Perfect Playlist", state="normal", bg="#00ffcc", fg="#121212"))
            return

        start_index = random.randint(0, len(track_data) - 1)
        playlist = [track_data.pop(start_index)]
        
        while track_data and len(playlist) < target_len:
            current_track = playlist[-1]
            best_score = float('inf')
            best_idx = -1
            
            for i, candidate in enumerate(track_data):
                bpm_c = candidate['bpm']
                bpm_t = current_track['bpm']
                
                if bpm_c > 0 and bpm_t > 0:
                    ratio = bpm_c / bpm_t
                    if 1.8 < ratio < 2.2: bpm_c /= 2.0
                    elif 0.45 < ratio < 0.55: bpm_c *= 2.0
                
                bpm_diff = bpm_c - bpm_t
                if bpm_diff < 0: bpm_penalty = abs(bpm_diff) * 10
                else: bpm_penalty = bpm_diff * 2 
                    
                pos_c = (candidate['key'] * 7) % 12
                pos_t = (current_track['key'] * 7) % 12
                dist = abs(pos_c - pos_t)
                harmonic_dist = min(dist, 12 - dist)
                key_penalty = harmonic_dist * 8 
                    
                score = bpm_penalty + key_penalty
                
                if score < best_score:
                    best_score = score
                    best_idx = i
                    
            playlist.append(track_data.pop(best_idx))
        
        def update_gui():
            queue_listbox.delete(0, tk.END)
            for t in playlist: 
                filename = t.get('file', 'Unknown Track')
                queue_listbox.insert(tk.END, filename)
            btn_utils.config(text="⚡ Auto-Build Perfect Playlist", state="normal", bg="#00ffcc", fg="#121212")
            
        root.after(0, update_gui)
    threading.Thread(target=analysis_task, daemon=True).start()

try:
    stream = sd.Stream(samplerate=48000, blocksize=4096, channels=(2, 2), callback=audio_callback)
    stream.start()
except Exception as e:
    print(f"Failed to open audio stream: {e}")
    sys.exit(1)

# --- 🖥️ Build the GUI Dashboard 🖥️ ---
root = tk.Tk()
root.title("DJ Sam Bolin's Pro Workstation")
root.geometry("1440x850") 
root.configure(bg="#121212")

bg_canvas = tk.Canvas(root, bg="#050505", highlightthickness=0)
bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)

active_waves = []
active_bolts = []
visual_mode = "raindrops" 

def toggle_visuals():
    global visual_mode
    if visual_mode == "raindrops":
        visual_mode = "lightning"
        btn_visual_toggle.config(text="👁️ VISUALS: LIGHTNING", fg="#fff600")
    elif visual_mode == "lightning":
        visual_mode = "off"
        btn_visual_toggle.config(text="👁️ VISUALS: OFF", fg="#777777")
    else:
        visual_mode = "raindrops"
        btn_visual_toggle.config(text="👁️ VISUALS: RAINDROPS", fg="#00ffcc")

def update_background_wave():
    global active_waves, active_bolts, visual_mode
    
    intensity = 0.0
    try:
        if mixer.get('playing_a') and 'deck_a_data' in globals() and deck_a_data is not None:
            pos = mixer['pos_a']
            chunk = deck_a_data[pos:pos+2000]
            if len(chunk) > 0: intensity = max(intensity, float(np.max(np.abs(chunk))))
            
        if mixer.get('playing_b') and 'deck_b_data' in globals() and deck_b_data is not None:
            pos = mixer['pos_b']
            chunk = deck_b_data[pos:pos+2000]
            if len(chunk) > 0: intensity = max(intensity, float(np.max(np.abs(chunk))))
    except Exception: 
        pass

    w = bg_canvas.winfo_width()
    h = bg_canvas.winfo_height()
    
    if w < 10 or h < 10: 
        root.after(30, update_background_wave)
        return

    bg_canvas.delete("wave") 

    if visual_mode == "off":
        active_waves.clear()
        active_bolts.clear()
        root.after(30, update_background_wave)
        return

    if visual_mode == "raindrops":
        if intensity > 0.35 and (not active_waves or active_waves[-1]['radius'] > 45):
            active_waves.append({'radius': 10, 'intensity': intensity, 'x': random.randint(50, w - 50), 'y': random.randint(50, h - 50)})

        new_waves = []
        max_r = max(w, h)
        for wave in active_waves:
            r = wave['radius']
            wave_int = wave['intensity']
            wx, wy = wave['x'], wave['y']
            fade = max(0, 1 - (r / max_r))
            
            if fade > 0:
                r_col = int(5 + (0 - 5) * fade * wave_int)
                g_col = int(5 + (255 - 5) * fade * wave_int)
                b_col = int(5 + (204 - 5) * fade * wave_int)
                hex_color = f"#{max(0, min(255, r_col)):02x}{max(0, min(255, g_col)):02x}{max(0, min(255, b_col)):02x}"
                
                bg_canvas.create_oval(wx - r, wy - r, wx + r, wy + r, outline=hex_color, width=max(1, int(4 * wave_int)), tags="wave")
                wave['radius'] += 6 + (12 * wave_int)
                new_waves.append(wave)
        active_waves = new_waves

    elif visual_mode == "lightning":
        if intensity > 0.45 and (not active_bolts or active_bolts[-1]['life'] < 0.6):
            start_x = random.randint(100, w - 100)
            start_y = random.randint(0, h // 3) 
            segments = []
            curr_x, curr_y = start_x, start_y
            
            for _ in range(random.randint(6, 15)):
                next_x = curr_x + random.randint(-80, 80)
                next_y = curr_y + random.randint(30, 90)
                segments.append((curr_x, curr_y, next_x, next_y))
                curr_x, curr_y = next_x, next_y
                
            active_bolts.append({'segments': segments, 'life': 1.0, 'intensity': intensity})

        new_bolts = []
        for bolt in active_bolts:
            fade = bolt['life']
            if fade > 0:
                r_col = int(5 + (255 - 5) * fade)
                g_col = int(5 + (246 - 5) * fade)
                b_col = int(5 + (0 - 5) * fade)
                hex_color = f"#{max(0, min(255, r_col)):02x}{max(0, min(255, g_col)):02x}{max(0, min(255, b_col)):02x}"
                
                bolt_width = max(1, int(5 * bolt['intensity'] * fade))
                for x1, y1, x2, y2 in bolt['segments']:
                    bg_canvas.create_line(x1, y1, x2, y2, fill=hex_color, width=bolt_width, tags="wave")
                
                bolt['life'] -= 0.12 
                new_bolts.append(bolt)
        active_bolts = new_bolts

    root.after(30, update_background_wave)

def nudge_crossfader(event, direction):
    if event.widget.winfo_class() == 'Entry':
        return
    current = mixer['crossfade']
    step = 0.05 
    if direction == 'left': new_val = max(-1.0, current - step)
    else: new_val = min(1.0, current + step)
    mixer['crossfade'] = new_val; cf_slider.set(new_val)

root.bind('<Left>', lambda e: nudge_crossfader(e, 'left'))
root.bind('<Right>', lambda e: nudge_crossfader(e, 'right'))

def safe_play(pad_num, event):
    if event.widget.winfo_class() == 'Entry': return
    play_sample(pad_num)

root.bind('a', lambda e: safe_play('1', e))
root.bind('w', lambda e: safe_play('2', e))
root.bind('s', lambda e: safe_play('3', e))
root.bind('d', lambda e: safe_play('4', e))
root.bind('h', lambda e: safe_play('5', e))
root.bind('u', lambda e: safe_play('6', e))
root.bind('j', lambda e: safe_play('7', e))
root.bind('k', lambda e: safe_play('8', e))

header_style = {'bg': '#121212', 'fg': '#ffffff', 'font': ('Arial', 12, 'bold')}
track_style = {'bg': '#121212', 'fg': '#00ffcc', 'font': ('Arial', 9, 'bold'), 'wraplength': 250}
btn_style = {'bg': '#333333', 'fg': '#ffffff', 'font': ('Arial', 10, 'bold'), 'relief': 'flat', 'cursor': 'hand2'}
pad_btn_style = {'bg': '#222222', 'fg': '#ff00cc', 'font': ('Arial', 10, 'bold'), 'relief': 'flat', 'cursor': 'hand2', 'width': 4, 'height': 2}

def refresh_library(*args):
    lib_listbox.delete(0, tk.END)
    try: query = search_var.get().lower()
    except NameError: query = ""
    for f in os.listdir(TRACK_DIR):
        if f.lower().endswith(('.mp3', '.wav')):
            if query in f.lower(): lib_listbox.insert(tk.END, f)

def add_selected_to_queue(event=None):
    try:
        if lib_listbox.curselection(): queue_listbox.insert(tk.END, lib_listbox.get(lib_listbox.curselection()))
    except Exception: pass
        
tk.Label(root, text="🎧 DJ PRO WORKSTATION 🎧", bg="#050505", fg="#00ffcc", font=('Arial', 18, 'bold')).pack(pady=10)

current_view = "main"
def toggle_view():
    global current_view
    if current_view == "main":
        frame_left.pack_forget()
        mixer_container.pack_forget()
        frame_right.pack_forget()
        frame_extras.pack(expand=True, pady=40)
        btn_view_toggle.config(text="🔙", fg="#00ffcc")
        current_view = "extras"
    else:
        frame_extras.pack_forget()
        frame_left.pack(side="left", fill="y", padx=(60, 20), pady=60)
        mixer_container.pack(side="left", expand=True, fill="both", padx=30, pady=60)
        frame_right.pack(side="right", fill="y", padx=(20, 60), pady=60)
        btn_view_toggle.config(text="⚙️", fg="#ff00cc")
        current_view = "main"

btn_view_toggle = tk.Button(root, text="⚙️", command=toggle_view, bg="#222", fg="#ff00cc", font=('Arial', 14, 'bold'), relief='flat', cursor='hand2')
btn_view_toggle.place(relx=1.0, rely=1.0, x=-20, y=-20, anchor="se", width=45, height=45)

frame_extras = tk.Frame(root, bg="#121212")

frame_left = tk.Frame(root, bg="#121212", width=280) 
frame_left.pack(side="left", fill="y", padx=(60, 20), pady=60) 

tk.Label(frame_left, text="📋 UP NEXT", **header_style).pack(pady=5)
queue_listbox = tk.Listbox(frame_left, bg="#222", fg="#00ffcc", height=12, width=32, highlightthickness=0)
queue_listbox.pack()
tk.Button(frame_left, text="Load to DECK A", command=lambda: load_from_queue('A'), **btn_style).pack(fill="x", pady=2)
tk.Button(frame_left, text="Load to DECK B", command=lambda: load_from_queue('B'), **btn_style).pack(fill="x", pady=2)

tk.Label(frame_left, text="💽 SETLISTS / PLAYLISTS", bg="#121212", fg="#777", font=('Arial', 10, 'bold')).pack(pady=(15, 2))
pl_frame = tk.Frame(frame_left, bg="#121212")
pl_frame.pack(fill="x")
tk.Button(pl_frame, text="💾 Save Queue", command=save_playlist, bg="#333", fg="#fff", font=('Arial', 9, 'bold'), relief='flat').pack(side="left", fill="x", expand=True, padx=(0, 2))
tk.Button(pl_frame, text="📂 Load List", command=load_playlist, bg="#333", fg="#fff", font=('Arial', 9, 'bold'), relief='flat').pack(side="right", fill="x", expand=True, padx=(2, 0))

tk.Label(frame_extras, text="🛠️ UTILITIES", bg="#121212", fg="#777", font=('Arial', 14, 'bold')).pack(pady=(15, 5))
settings_frame = tk.Frame(frame_extras, bg="#121212")
settings_frame.pack(fill="x", pady=5)
tk.Label(settings_frame, text="Random Pool:", bg="#121212", fg="#777").pack(side="left")
pool_var = tk.StringVar(value="50")
pool_entry = tk.Entry(settings_frame, textvariable=pool_var, width=4, bg="#222", fg="#00ffcc", insertbackground="#00ffcc", relief="flat")
pool_entry.pack(side="left", padx=(2, 10))
tk.Label(settings_frame, text="Output Size:", bg="#121212", fg="#777").pack(side="left")
length_var = tk.StringVar(value="15")
length_entry = tk.Entry(settings_frame, textvariable=length_var, width=4, bg="#222", fg="#00ffcc", insertbackground="#00ffcc", relief="flat")
length_entry.pack(side="left", padx=2)

btn_utils = tk.Button(frame_extras, text="⚡ Auto-Build Perfect Playlist", command=generate_bpm_playlist, bg="#00ffcc", fg="#121212", font=('Arial', 10, 'bold'), relief='flat', cursor='hand2')
btn_utils.pack(fill="x", pady=5)

btn_visual_toggle = tk.Button(frame_extras, text="👁️ VISUALS: RAINDROPS", command=toggle_visuals, bg="#222222", fg="#00ffcc", font=('Arial', 10, 'bold'), relief='flat', cursor='hand2')
btn_visual_toggle.pack(fill="x", pady=10)

btn_bass_drop = tk.Button(frame_extras, text="💣 DROP THE BASS", command=trigger_bass_drop, bg="#ff00cc", fg="#ffffff", font=('Arial', 10, 'bold'), relief='raised', cursor='hand2')
btn_bass_drop.pack(fill="x", pady=10)

btn_visual_toggle_left = tk.Button(frame_left, text="👁️ VISUALS: RAINDROPS", command=toggle_visuals, bg="#222222", fg="#00ffcc", font=('Arial', 9, 'bold'), relief='flat', cursor='hand2')
btn_visual_toggle_left.pack(fill="x", pady=2)

tk.Label(frame_left, text="💬 DJ INBOX", bg="#121212", fg="#ff00cc", font=('Arial', 12, 'bold')).pack(pady=(20, 5))
inbox_listbox = tk.Listbox(frame_left, bg="#222", fg="#ffffff", height=10, width=32, highlightthickness=0)
inbox_listbox.pack()

# === CENTER COLUMN (MIXER & VISUALS) ===
# 1. Create an outer container to hold the canvas and scrollbar
mixer_container = tk.Frame(root, bg="#050505")
mixer_container.pack(side="left", expand=True, fill="both", padx=30, pady=60)

# 2. Create the Canvas & Scrollbar
mixer_canvas = tk.Canvas(mixer_container, bg="#050505", highlightthickness=0)
mixer_scrollbar = tk.Scrollbar(mixer_container, orient="vertical", command=mixer_canvas.yview)
mixer_canvas.configure(yscrollcommand=mixer_scrollbar.set)

mixer_scrollbar.pack(side="right", fill="y")
mixer_canvas.pack(side="left", fill="both", expand=True)

# 3. Create your original frame_mixer INSIDE the Canvas
frame_mixer = tk.Frame(mixer_canvas, bg="#050505")
mixer_canvas.create_window((0, 0), window=frame_mixer, anchor="nw")

# 4. Tell the Canvas to update its scrollable area whenever widgets are added
def configure_mixer_scroll(event):
    mixer_canvas.configure(scrollregion=mixer_canvas.bbox("all"))

frame_mixer.bind("<Configure>", configure_mixer_scroll)

# 5. (Bonus) Enable Mouse-wheel scrolling when hovering over the mixer
def _on_mousewheel(event):
    if hasattr(event, 'delta') and event.delta != 0: # Windows/Mac
        mixer_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    elif event.num == 4: # Linux Scroll Up
        mixer_canvas.yview_scroll(-1, "units")
    elif event.num == 5: # Linux Scroll Down
        mixer_canvas.yview_scroll(1, "units")

mixer_canvas.bind('<Enter>', lambda e: root.bind_all("<MouseWheel>", _on_mousewheel))
mixer_canvas.bind('<Leave>', lambda e: root.unbind_all("<MouseWheel>"))

# Now continue with your normal layout code...
mixer_decks = tk.Frame(frame_mixer, bg="#050505")
mixer_decks.pack()

# --- DECK A ---
f_a = tk.Frame(mixer_decks, bg="#121212")
f_a.grid(row=0, column=0, padx=20, sticky="n")
tk.Label(f_a, text="DECK A", **header_style).pack()
label_track_a = tk.Label(f_a, text="[No Track Loaded]", **track_style); label_track_a.pack(pady=2)
canvas_wave_a = tk.Canvas(f_a, width=250, height=60, bg="#1a1a1a", highlightthickness=1, highlightbackground="#333")
canvas_wave_a.pack(pady=5)
lbl_time_a = tk.Label(f_a, text="00:00 / 00:00", bg="#121212", fg="#777", font=('Arial', 10, 'bold')); lbl_time_a.pack(pady=2)
btn_play_a = tk.Button(f_a, text="▶ Play", command=lambda: toggle_play('A'), **btn_style); btn_play_a.pack(fill="x", pady=2)
vol_slider_a = tk.Scale(f_a, from_=1.0, to=0.0, resolution=0.01, orient="vertical", length=200, bg='#121212', fg='#00ffcc', troughcolor='#333', highlightthickness=0, command=lambda v: mixer.update({'vol_a': float(v)}))
vol_slider_a.set(1.0); vol_slider_a.pack(pady=5)
pad_a = tk.Canvas(f_a, width=250, height=50, bg="#222", highlightthickness=1, highlightbackground="#00ffcc")
pad_a.create_text(125, 25, text="<- SCRUB PAD ->", fill="#777", font=('Arial', 10, 'bold')); pad_a.bind("<B1-Motion>", lambda e: scrub_audio(e, 'A')); pad_a.pack()

samp_frame_a = tk.Frame(f_a, bg="#121212")
samp_frame_a.pack(pady=10)
tk.Label(f_a, text="(Right-Click a pad to load a new sound)", bg="#121212", fg="#555", font=('Arial', 8)).pack()

pad_a1 = tk.Button(samp_frame_a, text="A", **pad_btn_style); pad_a1.grid(row=0, column=0, padx=5)
pad_a1.bind("<Button-1>", lambda e: play_sample('1')); pad_a1.bind("<Button-3>", lambda e: assign_sample('1'))
pad_a2 = tk.Button(samp_frame_a, text="W", **pad_btn_style); pad_a2.grid(row=0, column=1, padx=5)
pad_a2.bind("<Button-1>", lambda e: play_sample('2')); pad_a2.bind("<Button-3>", lambda e: assign_sample('2'))
pad_a3 = tk.Button(samp_frame_a, text="S", **pad_btn_style); pad_a3.grid(row=0, column=2, padx=5)
pad_a3.bind("<Button-1>", lambda e: play_sample('3')); pad_a3.bind("<Button-3>", lambda e: assign_sample('3'))
pad_a4 = tk.Button(samp_frame_a, text="D", **pad_btn_style); pad_a4.grid(row=0, column=3, padx=5)
pad_a4.bind("<Button-1>", lambda e: play_sample('4')); pad_a4.bind("<Button-3>", lambda e: assign_sample('4'))

# (FIXED) Note Sheet Extractor Buttons correctly bound to Deck A
btn_notes_a = tk.Button(f_a, text="📝 Extract Notes", command=lambda: analyze_and_save_notes('A'), **btn_style)
btn_notes_a.pack(fill="x", pady=(5, 2))
btn_playnotes_a = tk.Button(f_a, text="🎹 Auto-Play Sheet", command=lambda: play_last_notesheet('A'), **btn_style)
btn_playnotes_a.pack(fill="x", pady=2)


# --- MIC ---
f_m = tk.Frame(mixer_decks, bg="#121212")
f_m.grid(row=0, column=1, padx=20, sticky="n")
tk.Label(f_m, text="MIC", **header_style).pack()
tk.Label(f_m, text="Headset", **track_style).pack(pady=5)
mic_var = tk.BooleanVar(value=False)
tk.Checkbutton(f_m, text="🎙️ MIC ACTIVE", variable=mic_var, bg="#121212", fg="#ff00cc", selectcolor="#222", font=('Arial', 10, 'bold'), command=lambda: mixer.update({'mic_on': mic_var.get()})).pack(pady=2)
tk.Scale(f_m, from_=1.0, to=0.0, resolution=0.01, orient="vertical", length=200, bg='#121212', fg='#00ffcc', troughcolor='#333', highlightthickness=0, command=lambda v: mixer.update({'mic_vol': float(v)})).pack(pady=5)

# --- DECK B ---
f_b = tk.Frame(mixer_decks, bg="#121212")
f_b.grid(row=0, column=2, padx=20, sticky="n")
tk.Label(f_b, text="DECK B", **header_style).pack()
label_track_b = tk.Label(f_b, text="[No Track Loaded]", **track_style); label_track_b.pack(pady=2)
canvas_wave_b = tk.Canvas(f_b, width=250, height=60, bg="#1a1a1a", highlightthickness=1, highlightbackground="#333")
canvas_wave_b.pack(pady=5)
lbl_time_b = tk.Label(f_b, text="00:00 / 00:00", bg="#121212", fg="#777", font=('Arial', 10, 'bold')); lbl_time_b.pack(pady=2)
btn_play_b = tk.Button(f_b, text="▶ Play", command=lambda: toggle_play('B'), **btn_style); btn_play_b.pack(fill="x", pady=2)
vol_slider_b = tk.Scale(f_b, from_=1.0, to=0.0, resolution=0.01, orient="vertical", length=200, bg='#121212', fg='#00ffcc', troughcolor='#333', highlightthickness=0, command=lambda v: mixer.update({'vol_b': float(v)}))
vol_slider_b.set(1.0); vol_slider_b.pack(pady=5)
pad_b = tk.Canvas(f_b, width=250, height=50, bg="#222", highlightthickness=1, highlightbackground="#00ffcc")
pad_b.create_text(125, 25, text="<- SCRUB PAD ->", fill="#777", font=('Arial', 10, 'bold')); pad_b.bind("<B1-Motion>", lambda e: scrub_audio(e, 'B')); pad_b.pack()

samp_frame_b = tk.Frame(f_b, bg="#121212")
samp_frame_b.pack(pady=10)
tk.Label(f_b, text="(Right-Click a pad to load a new sound)", bg="#121212", fg="#555", font=('Arial', 8)).pack()

pad_b1 = tk.Button(samp_frame_b, text="H", **pad_btn_style); pad_b1.grid(row=0, column=0, padx=5)
pad_b1.bind("<Button-1>", lambda e: play_sample('5')); pad_b1.bind("<Button-3>", lambda e: assign_sample('5'))
pad_b2 = tk.Button(samp_frame_b, text="U", **pad_btn_style); pad_b2.grid(row=0, column=1, padx=5)
pad_b2.bind("<Button-1>", lambda e: play_sample('6')); pad_b2.bind("<Button-3>", lambda e: assign_sample('6'))
pad_b3 = tk.Button(samp_frame_b, text="J", **pad_btn_style); pad_b3.grid(row=0, column=2, padx=5)
pad_b3.bind("<Button-1>", lambda e: play_sample('7')); pad_b3.bind("<Button-3>", lambda e: assign_sample('7'))
pad_b4 = tk.Button(samp_frame_b, text="K", **pad_btn_style); pad_b4.grid(row=0, column=3, padx=5)
pad_b4.bind("<Button-1>", lambda e: play_sample('8')); pad_b4.bind("<Button-3>", lambda e: assign_sample('8'))

# Note Sheet Extractor Buttons for Deck B
btn_notes_b = tk.Button(f_b, text="📝 Extract Notes", command=lambda: analyze_and_save_notes('B'), **btn_style)
btn_notes_b.pack(fill="x", pady=(5, 2))
btn_playnotes_b = tk.Button(f_b, text="🎹 Auto-Play Sheet", command=lambda: play_last_notesheet('B'), **btn_style)
btn_playnotes_b.pack(fill="x", pady=2)


# CROSSFADER & AUTO-DJ
frame_cf = tk.Frame(frame_mixer, bg="#050505")
frame_cf.pack(pady=20)
tk.Label(frame_cf, text="CROSSFADER", bg="#050505", fg="#ffffff", font=('Arial', 12, 'bold')).pack()
cf_slider = tk.Scale(frame_cf, from_=-1.0, to=1.0, resolution=0.01, orient="horizontal", length=400, bg='#050505', fg='#00ffcc', troughcolor='#333', highlightthickness=0, command=lambda v: mixer.update({'crossfade': float(v)}))
cf_slider.set(0.0)
cf_slider.pack()

tk.Label(frame_cf, text="MASTER VOLUME", bg="#050505", fg="#ffffff", font=('Arial', 10, 'bold')).pack(pady=(15, 0))
master_slider = tk.Scale(frame_cf, from_=0.0, to=1.0, resolution=0.01, orient="horizontal", length=400, bg='#050505', fg='#00ffcc', troughcolor='#333', highlightthickness=0, command=lambda v: mixer.update({'master_vol': float(v)}))
master_slider.set(1.0)
master_slider.pack()

cf_btn_frame = tk.Frame(frame_cf, bg="#050505")
cf_btn_frame.pack(pady=10)
tk.Button(cf_btn_frame, text="✨ MANUAL BLEND ✨", command=auto_blend, bg="#00ffcc", fg="#121212", font=('Arial', 10, 'bold'), relief='flat', cursor='hand2').grid(row=0, column=0, padx=10)
btn_autodj = tk.Button(cf_btn_frame, text="🤖 AUTO-DJ: OFF", command=toggle_auto_dj, bg="#333333", fg="#ffffff", font=('Arial', 10, 'bold'), relief='flat', cursor='hand2')
btn_autodj.grid(row=0, column=1, padx=10)

frame_right = tk.Frame(root, bg="#121212", width=280) 
frame_right.pack(side="right", fill="y", padx=(20, 60), pady=60) 

tk.Label(frame_extras, text="📱 SCAN TO REQUEST", **header_style).pack(pady=(20, 5))

try:
    server_url = ngrok.connect(FLASK_PORT).public_url
except Exception as e:
    server_url = f"http://127.0.0.1:{FLASK_PORT}"

qr = qrcode.make(server_url).resize((200, 200))
qr_img = ImageTk.PhotoImage(qr)
qr_label = tk.Label(frame_extras, image=qr_img, bg="#121212")
qr_label.image = qr_img
qr_label.pack(pady=5)
tk.Label(frame_extras, text=f"Or visit:\n{server_url}", bg="#121212", fg="#777", font=('Arial', 10), wraplength=250).pack(pady=(0, 20))

tk.Label(frame_right, text="📂 TRACK LIBRARY", **header_style).pack(pady=(15, 2))
search_var = tk.StringVar()
search_var.trace("w", refresh_library)
search_entry = tk.Entry(frame_right, textvariable=search_var, bg="#222", fg="#00ffcc", insertbackground="#00ffcc", font=('Arial', 10), relief="flat")
search_entry.pack(fill="x", pady=(0, 5))

lib_container = tk.Frame(frame_right, bg="#121212")
lib_container.pack(fill="both", expand=True)
lib_scrollbar = tk.Scrollbar(lib_container, orient="vertical")
lib_scrollbar.pack(side="right", fill="y")
lib_listbox = tk.Listbox(lib_container, bg="#222", fg="#00ffcc", height=13, width=32, highlightthickness=0, yscrollcommand=lib_scrollbar.set)
lib_listbox.pack(side="left", fill="both", expand=True)
lib_scrollbar.config(command=lib_listbox.yview)

lib_listbox.bind("<Double-Button-1>", add_selected_to_queue)
tk.Button(frame_right, text="⬅️ Add to Queue", command=add_selected_to_queue, **btn_style).pack(fill="x", pady=2)
tk.Button(frame_right, text="🔄 Refresh Folder", command=refresh_library, **btn_style).pack(fill="x", pady=2)

refresh_library() 

# --- 🖱️ Drag & Drop: drag a track from the Library onto the Queue or a Deck ---
def is_descendant(widget, ancestor):
    while widget is not None:
        if widget == ancestor:
            return True
        widget = widget.master
    return False

drag_data = {'track': None, 'ghost': None}

def clear_drop_highlights():
    f_a.config(highlightthickness=0)
    f_b.config(highlightthickness=0)
    queue_listbox.config(highlightthickness=0)

def start_drag(event):
    idx = lib_listbox.nearest(event.y)
    if idx < 0 or idx >= lib_listbox.size():
        return
    lib_listbox.selection_clear(0, tk.END)
    lib_listbox.selection_set(idx)
    drag_data['track'] = lib_listbox.get(idx)

    ghost = tk.Toplevel(root)
    ghost.overrideredirect(True)
    ghost.attributes('-topmost', True)
    tk.Label(ghost, text=f"🎵 {drag_data['track']}", bg="#00ffcc", fg="#121212",
             font=('Arial', 9, 'bold'), padx=8, pady=4).pack()
    ghost.geometry(f"+{event.x_root + 15}+{event.y_root + 10}")
    drag_data['ghost'] = ghost

def do_drag(event):
    if not drag_data['track']:
        return
    drag_data['ghost'].geometry(f"+{event.x_root + 15}+{event.y_root + 10}")

    target = root.winfo_containing(event.x_root, event.y_root)
    clear_drop_highlights()
    if target and is_descendant(target, f_a):
        f_a.config(highlightthickness=2, highlightbackground="#00ffcc")
    elif target and is_descendant(target, f_b):
        f_b.config(highlightthickness=2, highlightbackground="#00ffcc")
    elif target is queue_listbox:
        queue_listbox.config(highlightthickness=2, highlightbackground="#00ffcc")

def end_drag(event):
    track = drag_data['track']
    drag_data['track'] = None
    if drag_data['ghost']:
        drag_data['ghost'].destroy()
        drag_data['ghost'] = None
    clear_drop_highlights()
    if not track:
        return

    target = root.winfo_containing(event.x_root, event.y_root)
    if target is None:
        return

    if is_descendant(target, f_a):
        threading.Thread(target=load_audio_file, args=(os.path.join(TRACK_DIR, track), 'A'), daemon=True).start()
    elif is_descendant(target, f_b):
        threading.Thread(target=load_audio_file, args=(os.path.join(TRACK_DIR, track), 'B'), daemon=True).start()
    elif target is queue_listbox:
        queue_listbox.insert(tk.END, track)

lib_listbox.bind("<ButtonPress-1>", start_drag, add="+")
lib_listbox.bind("<B1-Motion>", do_drag, add="+")
lib_listbox.bind("<ButtonRelease-1>", end_drag, add="+")


def unfocus_search(event):
    if event.widget not in (search_entry, pool_entry, length_entry):
        root.focus_set()

root.bind('<Button-1>', unfocus_search)

def format_time(frames):
    s = int(frames / 48000)
    return f"{s//60:02d}:{s%60:02d}"

def master_gui_loop():
    while incoming_messages: inbox_listbox.insert(0, incoming_messages.pop(0))
        
    if mixer['track_a_loaded']: 
        lbl_time_a.config(text=f"{format_time(mixer['pos_a'])} / {format_time(len(deck_a_data))}")
        if mixer['playhead_id_a']:
            progress_x = (mixer['pos_a'] / len(deck_a_data)) * 250
            canvas_wave_a.coords(mixer['playhead_id_a'], progress_x, 0, progress_x, 60)
            
    if mixer['track_b_loaded']: 
        lbl_time_b.config(text=f"{format_time(mixer['pos_b'])} / {format_time(len(deck_b_data))}")
        if mixer['playhead_id_b']:
            progress_x = (mixer['pos_b'] / len(deck_b_data)) * 250
            canvas_wave_b.coords(mixer['playhead_id_b'], progress_x, 0, progress_x, 60)
        
    if mixer['auto_dj'] and not mixer['blending']:
        if mixer['playing_a'] and not mixer['playing_b']:
            rem_sec_a = (len(deck_a_data) - mixer['pos_a']) / 48000
            if not mixer['track_b_loaded']:
                if queue_listbox.size() > 0:
                    load_from_queue('B'); mixer['track_b_loaded'] = True
                else:
                    next_track = pick_random_library_track(exclude=mixer.get('file_a'))
                    if next_track:
                        threading.Thread(target=load_audio_file, args=(os.path.join(TRACK_DIR, next_track), 'B'), daemon=True).start()
                        mixer['track_b_loaded'] = True
            if rem_sec_a < 6.0 and mixer['track_b_loaded']: auto_blend()
                
        elif mixer['playing_b'] and not mixer['playing_a']:
            rem_sec_b = (len(deck_b_data) - mixer['pos_b']) / 48000
            if not mixer['track_a_loaded']:
                if queue_listbox.size() > 0:
                    load_from_queue('A'); mixer['track_a_loaded'] = True
                else:
                    next_track = pick_random_library_track(exclude=mixer.get('file_b'))
                    if next_track:
                        threading.Thread(target=load_audio_file, args=(os.path.join(TRACK_DIR, next_track), 'A'), daemon=True).start()
                        mixer['track_a_loaded'] = True
            if rem_sec_b < 6.0 and mixer['track_a_loaded']: auto_blend()

    root.after(100, master_gui_loop) 

master_gui_loop()
update_background_wave()

def on_closing():
    print("🛑 Shutting down system and cleaning up ngrok...")
    try:
        ngrok.kill() 
    except Exception as e:
        print(f"Ngrok cleanup issue: {e}")
        
    try:
        stream.stop()
        stream.close()
    except Exception:
        pass
        
    root.destroy()
    os._exit(0)

root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()