#!/usr/bin/env python3
"""
Text-to-Video Word Player
A GUI application that displays pasted text one word at a time with BPM-based timing.
Supports video export to AVI, MP4, and MOV formats with loop support.
"""

import tkinter as tk
from tkinter import ttk, colorchooser, font as tkfont, filedialog, messagebox
import threading
import time
import os

# Audio dependencies for metronome
try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

# Video export dependencies
try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    VIDEO_EXPORT_AVAILABLE = True
except ImportError:
    VIDEO_EXPORT_AVAILABLE = False


class MetronomeSound:
    def __init__(self):
        if not AUDIO_AVAILABLE:
            return
        self.sample_rate = 44100
        self.click_sound = self._generate_click()
        self.accent_sound = self._generate_click(freq=1200, duration=0.03)
        
    def _generate_click(self, freq=800, duration=0.02):
        import array, math
        n_samples = int(self.sample_rate * duration)
        samples = array.array('h')
        for i in range(n_samples):
            t = i / self.sample_rate
            envelope = math.exp(-t * 100)
            value = int(32767 * envelope * math.sin(2 * math.pi * freq * t))
            samples.append(value)
        sound = pygame.mixer.Sound(buffer=samples.tobytes())
        sound.set_volume(0.5)
        return sound
        
    def play_click(self, accent=False):
        if not AUDIO_AVAILABLE:
            return
        (self.accent_sound if accent else self.click_sound).play()


class TextVideoPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Text-to-Video Word Player")
        self.root.geometry("1600x1000")
        self.root.minsize(1200, 800)
        
        self.is_playing = False
        self.is_paused = False
        self.current_word_index = 0
        self.words = []
        self.play_thread = None
        self.playback_start_time = 0
        self.loop_current = 0
        self._updating_aspect = False  # Guard flag to prevent infinite recursion
        self._updating_seek = False  # Guard flag to prevent infinite recursion in seek
        
        self.note_values = {
            "1/32": 1/8, "1/16": 1/4, "1/8": 1/2, "1/4": 1,
            "1/2": 2, "1": 4, "2": 8, "4": 16, "8": 32, "16": 64
        }
        
        # Settings
        self.bpm = tk.IntVar(value=120)
        self.word_note_value = tk.StringVar(value="1/4")
        self.fade_in_note = tk.StringVar(value="1/16")
        self.fade_out_note = tk.StringVar(value="1/16")
        self.gap_note = tk.StringVar(value="0")
        self.gap_negative = tk.BooleanVar(value=False)
        
        self.metronome_enabled = tk.BooleanVar(value=True)
        self.metronome_volume = tk.DoubleVar(value=0.5)
        self.time_signature_num = tk.IntVar(value=4)
        self.time_signature_den = tk.IntVar(value=4)
        
        # Loop settings
        self.loop_enabled = tk.BooleanVar(value=False)
        self.loop_mode = tk.StringVar(value="all_words")
        self.loop_bars = tk.IntVar(value=4)
        self.loop_times = tk.IntVar(value=2)
        self.loop_infinite = tk.BooleanVar(value=False)
        self.start_word = tk.IntVar(value=1)
        
        self.font_family = tk.StringVar(value="Arial")
        self.font_size = tk.IntVar(value=72)
        self.font_color = "#FFFFFF"
        self.bg_color = "#000000"
        self.aspect_ratio = tk.StringVar(value="16:9")
        self.export_fps = tk.IntVar(value=30)
        self.export_format = tk.StringVar(value="mp4")
        self.export_resolution = tk.StringVar(value="1920x1080")
        self.export_transparent = tk.BooleanVar(value=False)
        
        if AUDIO_AVAILABLE:
            self.metronome_sound = MetronomeSound()
        
        self.setup_ui()
        # Delay aspect update until window is fully rendered
        self.root.after(100, self.update_video_aspect)
        self.update_timing_display()
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left panel - Text input and settings
        left_frame = ttk.LabelFrame(main_frame, text="Text Input", padding="10")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        text_scroll = ttk.Scrollbar(left_frame)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.text_input = tk.Text(left_frame, wrap=tk.WORD, width=40, height=12,
                                   yscrollcommand=text_scroll.set, font=("Arial", 11))
        self.text_input.pack(fill=tk.BOTH, expand=True)
        text_scroll.config(command=self.text_input.yview)
        
        ttk.Button(left_frame, text="Load Text for Playback", 
                   command=self.load_text).pack(pady=10)
        
        self.word_count_label = ttk.Label(left_frame, text="Words: 0")
        self.word_count_label.pack()
        self.duration_label = ttk.Label(left_frame, text="Duration: 0:00")
        self.duration_label.pack()
        
        # Start word slider
        start_frame = ttk.LabelFrame(left_frame, text="Start Position", padding="10")
        start_frame.pack(fill=tk.X, pady=10)
        
        self.start_word_label = ttk.Label(start_frame, text="Start Word: 1", font=("Arial", 10, "bold"))
        self.start_word_label.pack()
        
        self.start_word_preview = ttk.Label(start_frame, text="", font=("Arial", 9, "italic"))
        self.start_word_preview.pack()
        
        self.start_slider = ttk.Scale(start_frame, from_=1, to=1, orient=tk.HORIZONTAL,
                                       variable=self.start_word, command=self.on_start_change)
        self.start_slider.pack(fill=tk.X, pady=5)
        
        start_btn_frame = ttk.Frame(start_frame)
        start_btn_frame.pack(fill=tk.X)
        ttk.Button(start_btn_frame, text="<< First", command=self.goto_first).pack(side=tk.LEFT, padx=2)
        ttk.Button(start_btn_frame, text="<< -10", command=lambda: self.adjust_start(-10)).pack(side=tk.LEFT, padx=2)
        ttk.Button(start_btn_frame, text="< -1", command=lambda: self.adjust_start(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(start_btn_frame, text="+1 >", command=lambda: self.adjust_start(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(start_btn_frame, text="+10 >>", command=lambda: self.adjust_start(10)).pack(side=tk.LEFT, padx=2)
        ttk.Button(start_btn_frame, text="Last >>", command=self.goto_last).pack(side=tk.LEFT, padx=2)
        
        # Loop settings
        loop_frame = ttk.LabelFrame(left_frame, text="Loop Settings", padding="10")
        loop_frame.pack(fill=tk.X, pady=10)
        
        ttk.Checkbutton(loop_frame, text="Enable Loop", variable=self.loop_enabled,
                        command=self.update_timing_display).pack(anchor=tk.W)
        
        mode_frame = ttk.Frame(loop_frame)
        mode_frame.pack(fill=tk.X, pady=5)
        ttk.Label(mode_frame, text="Loop Mode:").pack(side=tk.LEFT)
        
        ttk.Radiobutton(mode_frame, text="All Words", variable=self.loop_mode,
                        value="all_words", command=self.update_timing_display).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="By Bars", variable=self.loop_mode,
                        value="bars", command=self.update_timing_display).pack(side=tk.LEFT, padx=5)
        
        bars_frame = ttk.Frame(loop_frame)
        bars_frame.pack(fill=tk.X, pady=5)
        ttk.Label(bars_frame, text="Loop Bars:").pack(side=tk.LEFT)
        bars_spin = ttk.Spinbox(bars_frame, from_=1, to=64, textvariable=self.loop_bars,
                                 width=5, command=self.update_timing_display)
        bars_spin.pack(side=tk.LEFT, padx=5)
        self.bars_duration_label = ttk.Label(bars_frame, text="= 0.00s")
        self.bars_duration_label.pack(side=tk.LEFT)
        
        times_frame = ttk.Frame(loop_frame)
        times_frame.pack(fill=tk.X, pady=5)
        ttk.Checkbutton(times_frame, text="Infinite Loop", variable=self.loop_infinite,
                        command=self.on_infinite_toggle).pack(side=tk.LEFT)
        ttk.Label(times_frame, text="  Loop Count:").pack(side=tk.LEFT, padx=(10, 0))
        self.loop_times_spin = ttk.Spinbox(times_frame, from_=1, to=100, 
                                            textvariable=self.loop_times, width=5)
        self.loop_times_spin.pack(side=tk.LEFT, padx=5)
        
        self.loop_status_label = ttk.Label(loop_frame, text="Loop: - / -", font=("Courier", 11, "bold"))
        self.loop_status_label.pack(pady=5)
        
        # Export section
        export_frame = ttk.LabelFrame(left_frame, text="Video Export", padding="10")
        export_frame.pack(fill=tk.X, pady=10)
        
        if not VIDEO_EXPORT_AVAILABLE:
            ttk.Label(export_frame, text="[!] Install opencv-python, numpy, pillow",
                     foreground="red").pack()
        else:
            format_frame = ttk.Frame(export_frame)
            format_frame.pack(fill=tk.X, pady=2)
            ttk.Label(format_frame, text="Format:").pack(side=tk.LEFT)
            ttk.Combobox(format_frame, textvariable=self.export_format,
                        values=["mp4", "avi", "mov", "png_sequence"], state="readonly", width=12).pack(side=tk.LEFT, padx=5)
            ttk.Label(format_frame, text="FPS:").pack(side=tk.LEFT, padx=(10, 0))
            ttk.Combobox(format_frame, textvariable=self.export_fps,
                        values=[24, 25, 30, 48, 50, 60], width=6).pack(side=tk.LEFT, padx=5)
            
            res_frame = ttk.Frame(export_frame)
            res_frame.pack(fill=tk.X, pady=2)
            ttk.Label(res_frame, text="Resolution:").pack(side=tk.LEFT)
            ttk.Combobox(res_frame, textvariable=self.export_resolution,
                        values=["1920x1080", "1280x720", "3840x2160", 
                               "1080x1920", "720x1280", "1080x1080"], width=12).pack(side=tk.LEFT, padx=5)
            
            ttk.Checkbutton(export_frame, text="Transparent Background", 
                           variable=self.export_transparent).pack(anchor=tk.W, pady=2)
            
            ttk.Button(export_frame, text="Export Video", command=self.export_video).pack(pady=5)
            self.export_progress = ttk.Progressbar(export_frame, mode='determinate')
            self.export_progress.pack(fill=tk.X, pady=2)
            self.export_status = ttk.Label(export_frame, text="")
            self.export_status.pack()
        
        # Right panel
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # Video output
        video_frame = ttk.LabelFrame(right_frame, text="Video Output", padding="5")
        video_frame.pack(fill=tk.BOTH, expand=True)
        
        self.video_container = ttk.Frame(video_frame)
        self.video_container.pack(fill=tk.BOTH, expand=True)
        
        self.video_canvas = tk.Canvas(self.video_container, bg=self.bg_color,
                                       highlightthickness=2, highlightbackground="gray")
        self.video_canvas.pack(expand=True)
        
        progress_frame = ttk.Frame(video_frame)
        progress_frame.pack(pady=5)
        
        self.progress_label = ttk.Label(progress_frame, text="Word 0 / 0")
        self.progress_label.pack(side=tk.LEFT, padx=10)
        
        self.beat_label = ttk.Label(progress_frame, text="Beat: 0 | Bar: 0", 
                                     font=("Courier", 12, "bold"))
        self.beat_label.pack(side=tk.LEFT, padx=10)
        
        self.time_label = ttk.Label(progress_frame, text="0:00.000")
        self.time_label.pack(side=tk.LEFT, padx=10)
        
        # Controls notebook
        controls_notebook = ttk.Notebook(right_frame)
        controls_notebook.pack(fill=tk.X, pady=10)
        
        # Timing tab
        timing_tab = ttk.Frame(controls_notebook, padding="10")
        controls_notebook.add(timing_tab, text="Timing / BPM")
        
        bpm_frame = ttk.Frame(timing_tab)
        bpm_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(bpm_frame, text="BPM:", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        bpm_spin = ttk.Spinbox(bpm_frame, from_=20, to=300, textvariable=self.bpm, 
                                width=6, command=self.update_timing_display)
        bpm_spin.grid(row=0, column=1, padx=5)
        bpm_spin.bind("<KeyRelease>", lambda e: self.update_timing_display())
        
        ttk.Label(bpm_frame, text="Time Sig:").grid(row=0, column=2, padx=(20, 0))
        ttk.Spinbox(bpm_frame, from_=1, to=16, textvariable=self.time_signature_num, 
                    width=4, command=self.update_timing_display).grid(row=0, column=3, padx=2)
        ttk.Label(bpm_frame, text="/").grid(row=0, column=4)
        ts_den = ttk.Combobox(bpm_frame, textvariable=self.time_signature_den,
                              values=[2, 4, 8, 16], state="readonly", width=4)
        ts_den.grid(row=0, column=5, padx=2)
        ts_den.bind("<<ComboboxSelected>>", lambda e: self.update_timing_display())
        
        self.timing_info_label = ttk.Label(bpm_frame, text="", font=("Courier", 10))
        self.timing_info_label.grid(row=0, column=6, padx=(20, 0))
        
        # Note values
        note_frame = ttk.LabelFrame(timing_tab, text="Note Values", padding="5")
        note_frame.pack(fill=tk.X, pady=5)
        
        note_values_list = ["1/32", "1/16", "1/8", "1/4", "1/2", "1", "2", "4", "8", "16"]
        gap_values_list = ["0"] + note_values_list
        
        ttk.Label(note_frame, text="Word Duration:").grid(row=0, column=0, sticky=tk.W)
        word_combo = ttk.Combobox(note_frame, textvariable=self.word_note_value,
                                   values=note_values_list, state="readonly", width=8)
        word_combo.grid(row=0, column=1, padx=5)
        word_combo.bind("<<ComboboxSelected>>", lambda e: self.update_timing_display())
        self.word_duration_label = ttk.Label(note_frame, text="= 0.000s", width=12)
        self.word_duration_label.grid(row=0, column=2)
        
        ttk.Label(note_frame, text="Fade In:").grid(row=1, column=0, sticky=tk.W)
        fade_in = ttk.Combobox(note_frame, textvariable=self.fade_in_note,
                                values=gap_values_list, state="readonly", width=8)
        fade_in.grid(row=1, column=1, padx=5)
        fade_in.bind("<<ComboboxSelected>>", lambda e: self.update_timing_display())
        self.fade_in_duration_label = ttk.Label(note_frame, text="= 0.000s", width=12)
        self.fade_in_duration_label.grid(row=1, column=2)
        
        ttk.Label(note_frame, text="Fade Out:").grid(row=2, column=0, sticky=tk.W)
        fade_out = ttk.Combobox(note_frame, textvariable=self.fade_out_note,
                                 values=gap_values_list, state="readonly", width=8)
        fade_out.grid(row=2, column=1, padx=5)
        fade_out.bind("<<ComboboxSelected>>", lambda e: self.update_timing_display())
        self.fade_out_duration_label = ttk.Label(note_frame, text="= 0.000s", width=12)
        self.fade_out_duration_label.grid(row=2, column=2)
        
        gap_frame = ttk.Frame(note_frame)
        gap_frame.grid(row=3, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(gap_frame, text="Gap:").pack(side=tk.LEFT)
        ttk.Checkbutton(gap_frame, text="Negative", variable=self.gap_negative,
                        command=self.update_timing_display).pack(side=tk.LEFT, padx=10)
        gap_combo = ttk.Combobox(note_frame, textvariable=self.gap_note,
                                  values=gap_values_list, state="readonly", width=8)
        gap_combo.grid(row=3, column=1, padx=5)
        gap_combo.bind("<<ComboboxSelected>>", lambda e: self.update_timing_display())
        self.gap_duration_label = ttk.Label(note_frame, text="= 0.000s", width=12)
        self.gap_duration_label.grid(row=3, column=2)
        
        # Metronome
        metro_frame = ttk.LabelFrame(timing_tab, text="Metronome", padding="5")
        metro_frame.pack(fill=tk.X, pady=5)
        
        if not AUDIO_AVAILABLE:
            ttk.Label(metro_frame, text="[!] Install pygame for metronome", foreground="orange").pack()
        else:
            metro_ctrl = ttk.Frame(metro_frame)
            metro_ctrl.pack(fill=tk.X)
            ttk.Checkbutton(metro_ctrl, text="Enable", variable=self.metronome_enabled).pack(side=tk.LEFT)
            ttk.Label(metro_ctrl, text="Volume:").pack(side=tk.LEFT, padx=(20, 5))
            ttk.Scale(metro_ctrl, from_=0, to=1, variable=self.metronome_volume,
                     command=self.update_metronome_volume, length=100).pack(side=tk.LEFT)
            
            self.beat_indicators = []
            beat_frame = ttk.Frame(metro_frame)
            beat_frame.pack(pady=5)
            for i in range(16):
                ind = tk.Canvas(beat_frame, width=20, height=20, bg="#333", highlightthickness=1)
                ind.pack(side=tk.LEFT, padx=1)
                self.beat_indicators.append(ind)
        
        # Appearance tab
        appearance_tab = ttk.Frame(controls_notebook, padding="10")
        controls_notebook.add(appearance_tab, text="Appearance")
        
        aspect_frame = ttk.Frame(appearance_tab)
        aspect_frame.pack(fill=tk.X, pady=5)
        ttk.Label(aspect_frame, text="Aspect Ratio:").pack(side=tk.LEFT)
        aspect = ttk.Combobox(aspect_frame, textvariable=self.aspect_ratio,
                              values=["16:9", "4:3", "1:1", "9:16", "21:9"], state="readonly", width=10)
        aspect.pack(side=tk.LEFT, padx=5)
        aspect.bind("<<ComboboxSelected>>", lambda e: self.update_video_aspect())
        
        font_frame = ttk.LabelFrame(appearance_tab, text="Font", padding="5")
        font_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(font_frame, text="Font:").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(font_frame, textvariable=self.font_family,
                    values=sorted(tkfont.families()), width=20).grid(row=0, column=1, padx=5)
        ttk.Label(font_frame, text="Size:").grid(row=0, column=2, padx=(10, 0))
        ttk.Spinbox(font_frame, from_=12, to=200, textvariable=self.font_size, width=6).grid(row=0, column=3, padx=5)
        
        color_frame = ttk.Frame(font_frame)
        color_frame.grid(row=1, column=0, columnspan=4, pady=5)
        self.font_color_btn = tk.Button(color_frame, text="Text Color", bg=self.font_color,
                                         fg=self.bg_color, command=self.pick_font_color, width=12)
        self.font_color_btn.pack(side=tk.LEFT, padx=5)
        self.bg_color_btn = tk.Button(color_frame, text="Background", bg=self.bg_color,
                                       fg=self.font_color, command=self.pick_bg_color, width=12)
        self.bg_color_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(color_frame, text="Pick Color", command=self.pick_screen_color).pack(side=tk.LEFT, padx=5)
        
        # Playback controls
        playback_frame = ttk.LabelFrame(right_frame, text="Playback", padding="5")
        playback_frame.pack(fill=tk.X, pady=5)
        
        btn_frame = ttk.Frame(playback_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(btn_frame, text="Play", command=self.play).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Pause", command=self.pause).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Stop", command=self.stop).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Restart", command=self.restart).pack(side=tk.LEFT, padx=5)
        
        self.count_in = tk.BooleanVar(value=True)
        ttk.Checkbutton(btn_frame, text="Count-in", variable=self.count_in).pack(side=tk.LEFT, padx=20)
        
        seek_frame = ttk.Frame(playback_frame)
        seek_frame.pack(fill=tk.X, pady=5)
        ttk.Label(seek_frame, text="Seek:").pack(side=tk.LEFT)
        self.seek_scale = ttk.Scale(seek_frame, from_=0, to=100, command=self.on_seek)
        self.seek_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.video_container.bind("<Configure>", lambda e: self.update_video_aspect())

    # Start word controls
    def on_start_change(self, val):
        idx = int(float(val))
        self.start_word.set(idx)
        self.start_word_label.config(text=f"Start Word: {idx}")
        if self.words and 0 < idx <= len(self.words):
            self.start_word_preview.config(text=f'"{self.words[idx-1]}"')
            self.current_word_index = idx - 1
            self.refresh_display()
        self.update_timing_display()
        
    def adjust_start(self, delta):
        new_val = max(1, min(len(self.words) if self.words else 1, self.start_word.get() + delta))
        self.start_word.set(new_val)
        self.on_start_change(new_val)
        
    def goto_first(self):
        self.start_word.set(1)
        self.on_start_change(1)
        
    def goto_last(self):
        if self.words:
            self.start_word.set(len(self.words))
            self.on_start_change(len(self.words))

    def on_infinite_toggle(self):
        self.loop_times_spin.config(state="disabled" if self.loop_infinite.get() else "normal")
        self.update_timing_display()

    def note_to_seconds(self, note_str):
        if note_str == "0":
            return 0.0
        return self.note_values.get(note_str, 1) * 60.0 / self.bpm.get()
    
    def get_bar_seconds(self):
        return self.time_signature_num.get() * 60.0 / self.bpm.get()

    def update_timing_display(self):
        bpm = self.bpm.get()
        spb = 60.0 / bpm
        
        word_dur = self.note_to_seconds(self.word_note_value.get())
        fade_in = self.note_to_seconds(self.fade_in_note.get())
        fade_out = self.note_to_seconds(self.fade_out_note.get())
        gap = self.note_to_seconds(self.gap_note.get())
        if self.gap_negative.get():
            gap = -gap
        
        self.word_duration_label.config(text=f"= {word_dur:.3f}s")
        self.fade_in_duration_label.config(text=f"= {fade_in:.3f}s")
        self.fade_out_duration_label.config(text=f"= {fade_out:.3f}s")
        self.gap_duration_label.config(text=f"= {gap:+.3f}s")
        self.timing_info_label.config(text=f"1 beat = {spb:.3f}s")
        
        bar_dur = self.get_bar_seconds()
        loop_bar_dur = self.loop_bars.get() * bar_dur
        self.bars_duration_label.config(text=f"= {loop_bar_dur:.2f}s")
        
        # Update duration display
        self.update_duration_display()
        
        if AUDIO_AVAILABLE and hasattr(self, 'beat_indicators'):
            ts = self.time_signature_num.get()
            for i, ind in enumerate(self.beat_indicators):
                ind.config(bg="#333" if i < ts else "#111")

    def update_duration_display(self):
        if not self.words:
            self.duration_label.config(text="Duration: 0:00")
            return
            
        start_idx = self.start_word.get() - 1
        word_count = len(self.words) - start_idx
        
        word_dur = self.note_to_seconds(self.word_note_value.get())
        gap = self.note_to_seconds(self.gap_note.get())
        if self.gap_negative.get():
            gap = -gap
        
        single_pass = max(0, word_count * word_dur + (word_count - 1) * gap)
        
        if self.loop_enabled.get():
            if self.loop_mode.get() == "bars":
                loop_dur = self.loop_bars.get() * self.get_bar_seconds()
            else:
                loop_dur = single_pass
                
            if self.loop_infinite.get():
                self.duration_label.config(text=f"Duration: {loop_dur:.2f}s x inf")
            else:
                total = loop_dur * self.loop_times.get()
                self.duration_label.config(text=f"Duration: {total:.2f}s ({self.loop_times.get()}x)")
        else:
            mins = int(single_pass // 60)
            secs = single_pass % 60
            self.duration_label.config(text=f"Duration: {mins}:{secs:05.2f}")

    def update_metronome_volume(self, val=None):
        if AUDIO_AVAILABLE:
            v = self.metronome_volume.get()
            self.metronome_sound.click_sound.set_volume(v)
            self.metronome_sound.accent_sound.set_volume(v)

    def update_video_aspect(self):
        if self._updating_aspect:
            return
        self._updating_aspect = True
        try:
            self.root.update_idletasks()
            cw = self.video_container.winfo_width()
            ch = self.video_container.winfo_height()
            if cw < 10 or ch < 10:
                cw, ch = 640, 480
            
            w, h = map(int, self.aspect_ratio.get().split(":"))
            ratio = w / h
            
            if cw / ch > ratio:
                canvas_h = ch - 20
                canvas_w = int(canvas_h * ratio)
            else:
                canvas_w = cw - 20
                canvas_h = int(canvas_w / ratio)
            
            self.video_canvas.config(width=canvas_w, height=canvas_h)
            self.refresh_display()
        finally:
            self._updating_aspect = False

    def load_text(self):
        text = self.text_input.get("1.0", tk.END).strip()
        self.words = text.split()
        self.current_word_index = 0
        
        n = len(self.words)
        self.word_count_label.config(text=f"Words: {n}")
        
        if n > 0:
            self.start_slider.config(to=n)
            self.start_word.set(1)
            self.on_start_change(1)
            self.seek_scale.config(to=n - 1)
        
        self.update_timing_display()
        self.refresh_display()

    def hex_to_rgb(self, hex_color):
        h = hex_color.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    
    def blend_color(self, fg, bg, opacity):
        fg_rgb = self.hex_to_rgb(fg)
        bg_rgb = self.hex_to_rgb(bg)
        blended = tuple(int(f * opacity + b * (1 - opacity)) for f, b in zip(fg_rgb, bg_rgb))
        return '#{:02x}{:02x}{:02x}'.format(*blended)

    def refresh_display(self, opacity=1.0):
        self.video_canvas.delete("all")
        self.video_canvas.config(bg=self.bg_color)
        
        if self.words and 0 <= self.current_word_index < len(self.words):
            word = self.words[self.current_word_index]
            cw = self.video_canvas.winfo_width()
            ch = self.video_canvas.winfo_height()
            font = (self.font_family.get(), self.font_size.get(), "bold")
            color = self.blend_color(self.font_color, self.bg_color, opacity)
            self.video_canvas.create_text(cw/2, ch/2, text=word, font=font, fill=color)

    def display_word(self, word, opacity=1.0, prev_word=None, prev_opacity=0.0):
        self.video_canvas.delete("all")
        self.video_canvas.config(bg=self.bg_color)
        cw = self.video_canvas.winfo_width()
        ch = self.video_canvas.winfo_height()
        font = (self.font_family.get(), self.font_size.get(), "bold")
        
        if prev_word and prev_opacity > 0:
            color = self.blend_color(self.font_color, self.bg_color, prev_opacity)
            self.video_canvas.create_text(cw/2, ch/2, text=prev_word, font=font, fill=color)
        
        if word and opacity > 0:
            color = self.blend_color(self.font_color, self.bg_color, opacity)
            self.video_canvas.create_text(cw/2, ch/2, text=word, font=font, fill=color)

    def clear_display(self):
        self.video_canvas.delete("all")
        self.video_canvas.config(bg=self.bg_color)

    def update_progress(self):
        start = self.start_word.get() - 1
        total = len(self.words) - start
        current = self.current_word_index - start + 1
        self.progress_label.config(text=f"Word {current} / {total}")
        
        # Only update seek scale if we're not already handling a seek event
        if not self._updating_seek:
            self._updating_seek = True
            try:
                self.seek_scale.set(self.current_word_index)
            finally:
                self._updating_seek = False

    def update_beat_display(self, beat, bar, elapsed):
        self.beat_label.config(text=f"Beat: {beat+1} | Bar: {bar+1}")
        mins = int(elapsed // 60)
        secs = elapsed % 60
        self.time_label.config(text=f"{mins}:{secs:06.3f}")
        
        if AUDIO_AVAILABLE and hasattr(self, 'beat_indicators'):
            ts = self.time_signature_num.get()
            for i, ind in enumerate(self.beat_indicators):
                if i < ts:
                    ind.config(bg="#F50" if i == beat and i == 0 else "#0F0" if i == beat else "#666")
                else:
                    ind.config(bg="#111")

    def update_loop_display(self):
        if self.loop_infinite.get():
            self.loop_status_label.config(text=f"Loop: {self.loop_current + 1} / inf")
        else:
            self.loop_status_label.config(text=f"Loop: {self.loop_current + 1} / {self.loop_times.get()}")

    def play(self):
        if not self.words:
            self.load_text()
            if not self.words:
                return
        
        if self.is_paused:
            self.is_paused = False
            return
        
        if self.is_playing:
            return
        
        self.current_word_index = self.start_word.get() - 1
        self.loop_current = 0
        self.is_playing = True
        self.is_paused = False
        self.play_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.play_thread.start()

    def _playback_loop(self):
        bpm = self.bpm.get()
        spb = 60.0 / bpm
        ts = self.time_signature_num.get()
        
        word_dur = self.note_to_seconds(self.word_note_value.get())
        fade_in = self.note_to_seconds(self.fade_in_note.get())
        fade_out = self.note_to_seconds(self.fade_out_note.get())
        gap = self.note_to_seconds(self.gap_note.get())
        if self.gap_negative.get():
            gap = -gap
        
        start_idx = self.start_word.get() - 1
        fade_steps = 20
        
        # Count-in
        if self.count_in.get():
            for beat in range(ts):
                if not self.is_playing:
                    return
                beat_start = time.time()
                if self.metronome_enabled.get() and AUDIO_AVAILABLE:
                    self.metronome_sound.play_click(accent=(beat == 0))
                self.root.after(0, lambda b=beat: self.update_beat_display(b, -1, -(ts - b) * spb))
                while time.time() - beat_start < spb:
                    if not self.is_playing:
                        return
                    time.sleep(0.001)
        
        # Main playback with loop support
        while self.is_playing:
            self.current_word_index = start_idx
            loop_start = time.time()
            self.playback_start_time = loop_start
            metro_beat = 0
            next_beat = 0.0
            
            bar_duration = self.loop_bars.get() * self.get_bar_seconds()
            
            self.root.after(0, self.update_loop_display)
            
            while self.is_playing and self.current_word_index < len(self.words):
                # Pause handling
                while self.is_paused and self.is_playing:
                    time.sleep(0.01)
                
                if not self.is_playing:
                    break
                
                # Check bar-based loop end
                if self.loop_enabled.get() and self.loop_mode.get() == "bars":
                    if time.time() - loop_start >= bar_duration:
                        break
                
                word = self.words[self.current_word_index]
                prev_word = self.words[self.current_word_index - 1] if self.current_word_index > start_idx else None
                
                # Fade in
                if fade_in > 0:
                    step_t = fade_in / fade_steps
                    for i in range(fade_steps + 1):
                        if not self.is_playing:
                            break
                        
                        # Metronome check
                        elapsed = time.time() - self.playback_start_time
                        if elapsed >= next_beat:
                            b = metro_beat % ts
                            bar = metro_beat // ts
                            if self.metronome_enabled.get() and AUDIO_AVAILABLE:
                                self.metronome_sound.play_click(accent=(b == 0))
                            self.root.after(0, lambda b=b, bar=bar, e=elapsed: self.update_beat_display(b, bar, e))
                            metro_beat += 1
                            next_beat = metro_beat * spb
                        
                        op = i / fade_steps
                        if gap < 0 and prev_word:
                            self.root.after(0, lambda w=word, o=op, pw=prev_word, po=1-op: self.display_word(w, o, pw, po))
                        else:
                            self.root.after(0, lambda w=word, o=op: self.display_word(w, o))
                        time.sleep(step_t)
                else:
                    self.root.after(0, lambda w=word: self.display_word(w, 1.0))
                
                self.root.after(0, self.update_progress)
                
                # Main display
                main_dur = max(0.01, word_dur - fade_in - fade_out)
                end_time = time.time() + main_dur
                
                while time.time() < end_time and self.is_playing:
                    elapsed = time.time() - self.playback_start_time
                    if elapsed >= next_beat:
                        b = metro_beat % ts
                        bar = metro_beat // ts
                        if self.metronome_enabled.get() and AUDIO_AVAILABLE:
                            self.metronome_sound.play_click(accent=(b == 0))
                        self.root.after(0, lambda b=b, bar=bar, e=elapsed: self.update_beat_display(b, bar, e))
                        metro_beat += 1
                        next_beat = metro_beat * spb
                    time.sleep(0.001)
                
                # Fade out
                if fade_out > 0 and gap >= 0:
                    step_t = fade_out / fade_steps
                    for i in range(fade_steps + 1):
                        if not self.is_playing:
                            break
                        elapsed = time.time() - self.playback_start_time
                        if elapsed >= next_beat:
                            b = metro_beat % ts
                            bar = metro_beat // ts
                            if self.metronome_enabled.get() and AUDIO_AVAILABLE:
                                self.metronome_sound.play_click(accent=(b == 0))
                            self.root.after(0, lambda b=b, bar=bar, e=elapsed: self.update_beat_display(b, bar, e))
                            metro_beat += 1
                            next_beat = metro_beat * spb
                        op = 1.0 - i / fade_steps
                        self.root.after(0, lambda w=word, o=op: self.display_word(w, o))
                        time.sleep(step_t)
                
                # Gap
                if gap > 0:
                    self.root.after(0, self.clear_display)
                    end_time = time.time() + gap
                    while time.time() < end_time and self.is_playing:
                        elapsed = time.time() - self.playback_start_time
                        if elapsed >= next_beat:
                            b = metro_beat % ts
                            bar = metro_beat // ts
                            if self.metronome_enabled.get() and AUDIO_AVAILABLE:
                                self.metronome_sound.play_click(accent=(b == 0))
                            self.root.after(0, lambda b=b, bar=bar, e=elapsed: self.update_beat_display(b, bar, e))
                            metro_beat += 1
                            next_beat = metro_beat * spb
                        time.sleep(0.001)
                
                self.current_word_index += 1
            
            # Loop logic
            if not self.loop_enabled.get():
                break
            
            self.loop_current += 1
            
            if not self.loop_infinite.get() and self.loop_current >= self.loop_times.get():
                break
        
        self.is_playing = False
        self.root.after(0, lambda: self.progress_label.config(text="Complete"))

    def pause(self):
        self.is_paused = True

    def stop(self):
        self.is_playing = False
        self.is_paused = False
        self.current_word_index = self.start_word.get() - 1
        self.loop_current = 0
        self.clear_display()
        self.update_progress()
        self.loop_status_label.config(text="Loop: - / -")
        self.beat_label.config(text="Beat: 0 | Bar: 0")
        self.time_label.config(text="0:00.000")
        if AUDIO_AVAILABLE and hasattr(self, 'beat_indicators'):
            for ind in self.beat_indicators:
                ind.config(bg="#333")

    def restart(self):
        self.stop()
        self.root.after(100, self.play)

    def on_seek(self, val):
        if self._updating_seek:
            return
        self._updating_seek = True
        try:
            if self.words:
                self.current_word_index = int(float(val))
                self.update_progress()
                if not self.is_playing:
                    self.refresh_display()
        finally:
            self._updating_seek = False

    def pick_font_color(self):
        color = colorchooser.askcolor(initialcolor=self.font_color, title="Text Color")
        if color[1]:
            self.font_color = color[1]
            self.font_color_btn.config(bg=self.font_color)
            self.refresh_display()

    def pick_bg_color(self):
        color = colorchooser.askcolor(initialcolor=self.bg_color, title="Background Color")
        if color[1]:
            self.bg_color = color[1]
            self.bg_color_btn.config(bg=self.bg_color)
            self.video_canvas.config(bg=self.bg_color)
            self.refresh_display()

    def pick_screen_color(self):
        """Screen-wide eyedropper tool to pick colors from anywhere"""
        try:
            from PIL import ImageGrab
        except ImportError:
            messagebox.showerror("Error", "PIL/Pillow is required for screen color picker")
            return
        
        # Capture screenshot before showing overlay
        screenshot = ImageGrab.grab()
        
        # Create fullscreen overlay window
        picker_win = tk.Toplevel(self.root)
        picker_win.attributes('-fullscreen', True)
        picker_win.attributes('-alpha', 0.3)  # Semi-transparent
        picker_win.attributes('-topmost', True)
        picker_win.config(cursor="cross", bg="black")
        
        # Instructions label
        info_label = tk.Label(picker_win, text="Click anywhere to pick a color | Press ESC to cancel",
                             font=("Arial", 16, "bold"), fg="white", bg="black")
        info_label.place(relx=0.5, rely=0.05, anchor="center")
        
        def on_click(event):
            x, y = event.x_root, event.y_root
            # Get color from screenshot
            try:
                color = screenshot.getpixel((x, y))
                hex_color = '#{:02x}{:02x}{:02x}'.format(*color[:3])  # Handle RGBA
                picker_win.destroy()
                
                # Show dialog to apply to text or background
                apply_win = tk.Toplevel(self.root)
                apply_win.title("Apply Color")
                apply_win.geometry("300x200")
                apply_win.attributes("-topmost", True)
                apply_win.transient(self.root)
                
                ttk.Label(apply_win, text=f"Selected Color: {hex_color}", 
                         font=("Arial", 11, "bold")).pack(pady=10)
                
                preview = tk.Frame(apply_win, width=100, height=50, bg=hex_color, 
                                  relief=tk.SUNKEN, bd=3)
                preview.pack(pady=10)
                preview.pack_propagate(False)
                
                btn_frame = ttk.Frame(apply_win)
                btn_frame.pack(pady=10)
                
                def apply_text():
                    self.font_color = hex_color
                    self.font_color_btn.config(bg=hex_color)
                    self.refresh_display()
                    apply_win.destroy()
                
                def apply_bg():
                    self.bg_color = hex_color
                    self.bg_color_btn.config(bg=hex_color)
                    self.video_canvas.config(bg=hex_color)
                    self.refresh_display()
                    apply_win.destroy()
                
                ttk.Button(btn_frame, text="Apply to Text", command=apply_text).pack(side=tk.LEFT, padx=5)
                ttk.Button(btn_frame, text="Apply to Background", command=apply_bg).pack(side=tk.LEFT, padx=5)
                ttk.Button(btn_frame, text="Cancel", command=apply_win.destroy).pack(side=tk.LEFT, padx=5)
                
            except Exception as e:
                picker_win.destroy()
                messagebox.showerror("Error", f"Failed to pick color: {e}")
        
        picker_win.bind('<Button-1>', on_click)
        picker_win.bind('<Escape>', lambda e: picker_win.destroy())

    def find_system_font(self, family):
        import platform
        system = platform.system()
        
        if system == "Windows":
            dirs = [os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')]
        elif system == "Darwin":
            dirs = ['/Library/Fonts', '/System/Library/Fonts', os.path.expanduser('~/Library/Fonts')]
        else:
            dirs = ['/usr/share/fonts', '/usr/local/share/fonts', os.path.expanduser('~/.fonts')]
        
        name = family.lower().replace(' ', '')
        for d in dirs:
            if os.path.exists(d):
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.lower().endswith(('.ttf', '.otf')) and name in f.lower().replace(' ', ''):
                            return os.path.join(root, f)
        
        for d in dirs:
            if os.path.exists(d):
                for root, _, files in os.walk(d):
                    for f in ['arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf']:
                        if f in files:
                            return os.path.join(root, f)
        return None

    def export_video(self):
        if not VIDEO_EXPORT_AVAILABLE:
            messagebox.showerror("Error", "Install opencv-python, numpy, pillow")
            return
        
        if not self.words:
            self.load_text()
            if not self.words:
                return
        
        fmt = self.export_format.get()
        
        if fmt == "png_sequence":
            # For PNG sequence, select a directory
            foldername = filedialog.askdirectory(title="Select Folder for PNG Sequence")
            if not foldername:
                return
            filename = foldername
        else:
            filename = filedialog.asksaveasfilename(
                defaultextension=f".{fmt}",
                filetypes=[("MP4", "*.mp4"), ("AVI", "*.avi"), ("MOV", "*.mov")],
                title="Export Video"
            )
            if not filename:
                return
        
        threading.Thread(target=self._export_thread, args=(filename,), daemon=True).start()

    def _export_thread(self, filename):
        try:
            self.root.after(0, lambda: self.export_status.config(text="Preparing..."))
            
            w, h = map(int, self.export_resolution.get().split('x'))
            fps = self.export_fps.get()
            
            fmt = self.export_format.get().lower()
            is_png_seq = (fmt == "png_sequence")
            use_transparency = self.export_transparent.get()
            
            # Setup output
            if is_png_seq:
                # Create folder for PNG sequence
                os.makedirs(filename, exist_ok=True)
                out = None
            else:
                fourcc = cv2.VideoWriter_fourcc(*('mp4v' if fmt in ['mp4', 'mov'] else 'XVID'))
                out = cv2.VideoWriter(filename, fourcc, fps, (w, h))
                
                if not out.isOpened():
                    self.root.after(0, lambda: messagebox.showerror("Error", "Failed to create video"))
                    return
            
            font_path = self.find_system_font(self.font_family.get())
            font_size = int(self.font_size.get() * h / 1080)
            try:
                pil_font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
            except:
                pil_font = ImageFont.load_default()
            
            word_dur = self.note_to_seconds(self.word_note_value.get())
            fade_in = self.note_to_seconds(self.fade_in_note.get())
            fade_out = self.note_to_seconds(self.fade_out_note.get())
            gap = self.note_to_seconds(self.gap_note.get())
            if self.gap_negative.get():
                gap = -gap
            
            fade_in_f = int(fade_in * fps)
            fade_out_f = int(fade_out * fps)
            word_f = int(word_dur * fps)
            gap_f = int(abs(gap) * fps) if gap > 0 else 0
            main_f = max(1, word_f - fade_in_f - fade_out_f)
            
            bg = self.hex_to_rgb(self.bg_color)
            fg = self.hex_to_rgb(self.font_color)
            
            start_idx = self.start_word.get() - 1
            words_to_export = self.words[start_idx:]
            
            # Calculate loops
            if self.loop_enabled.get():
                if self.loop_mode.get() == "bars":
                    bar_frames = int(self.loop_bars.get() * self.get_bar_seconds() * fps)
                    loops = 1 if self.loop_infinite.get() else self.loop_times.get()
                else:
                    loops = 1 if self.loop_infinite.get() else self.loop_times.get()
            else:
                loops = 1
            
            frame_count = 0
            
            # Helper function to write frames
            def write_frame(frame_data):
                nonlocal frame_count
                if is_png_seq:
                    # Save as PNG
                    png_path = os.path.join(filename, f"frame_{frame_count:06d}.png")
                    cv2.imwrite(png_path, frame_data)
                else:
                    out.write(frame_data)
                frame_count += 1
            
            for loop in range(loops):
                word_idx = 0
                loop_frames = 0
                bar_limit = int(self.loop_bars.get() * self.get_bar_seconds() * fps) if self.loop_enabled.get() and self.loop_mode.get() == "bars" else float('inf')
                
                while word_idx < len(words_to_export) and loop_frames < bar_limit:
                    word = words_to_export[word_idx]
                    prev_word = words_to_export[word_idx - 1] if word_idx > 0 else None
                    
                    progress = int(((loop * len(words_to_export) + word_idx) / (loops * len(words_to_export))) * 100)
                    self.root.after(0, lambda p=progress: self.export_progress.config(value=p))
                    self.root.after(0, lambda l=loop+1, t=loops, i=word_idx+1, n=len(words_to_export): 
                                   self.export_status.config(text=f"Loop {l}/{t} - Word {i}/{n}"))
                    
                    # Fade in
                    for i in range(fade_in_f):
                        if loop_frames >= bar_limit:
                            break
                        op = i / fade_in_f if fade_in_f > 0 else 1.0
                        pop = 1.0 - op if gap < 0 and prev_word else 0.0
                        frame = self._render_frame(w, h, word, op, prev_word, pop, pil_font, bg, fg, use_transparency)
                        write_frame(frame)
                        loop_frames += 1
                    
                    # Main
                    for _ in range(main_f):
                        if loop_frames >= bar_limit:
                            break
                        frame = self._render_frame(w, h, word, 1.0, None, 0, pil_font, bg, fg, use_transparency)
                        write_frame(frame)
                        loop_frames += 1
                    
                    # Fade out
                    if gap >= 0:
                        for i in range(fade_out_f):
                            if loop_frames >= bar_limit:
                                break
                            op = 1.0 - i / fade_out_f if fade_out_f > 0 else 0.0
                            frame = self._render_frame(w, h, word, op, None, 0, pil_font, bg, fg, use_transparency)
                            write_frame(frame)
                            loop_frames += 1
                    
                    # Gap
                    if gap > 0:
                        blank = self._render_frame(w, h, "", 0, None, 0, pil_font, bg, fg, use_transparency)
                        for _ in range(gap_f):
                            if loop_frames >= bar_limit:
                                break
                            write_frame(blank)
                            loop_frames += 1
                    
                    word_idx += 1
            
            if not is_png_seq:
                out.release()
            
            dur = frame_count / fps
            self.root.after(0, lambda: self.export_progress.config(value=100))
            self.root.after(0, lambda: self.export_status.config(text="Complete!"))
            self.root.after(0, lambda: messagebox.showinfo("Success", 
                f"Exported: {filename}\nFrames: {frame_count}\nDuration: {dur:.1f}s"))
            
        except Exception as e:
            self.root.after(0, lambda: self.export_status.config(text=f"Error: {e}"))
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _render_frame(self, w, h, word, op, prev_word, prev_op, font, bg, fg, use_alpha=False):
        """Render a single frame with optional alpha channel for transparency"""
        if use_alpha:
            # Create RGBA image for transparency
            img = Image.new('RGBA', (w, h), (0, 0, 0, 0))  # Transparent background
            draw = ImageDraw.Draw(img)
            
            if prev_word and prev_op > 0:
                # Calculate color with alpha
                alpha = int(255 * prev_op)
                color = (*fg, alpha)
                bbox = draw.textbbox((0, 0), prev_word, font=font)
                x = (w - bbox[2] + bbox[0]) // 2
                y = (h - bbox[3] + bbox[1]) // 2
                draw.text((x, y), prev_word, font=font, fill=color)
            
            if word and op > 0:
                # Calculate color with alpha
                alpha = int(255 * op)
                color = (*fg, alpha)
                bbox = draw.textbbox((0, 0), word, font=font)
                x = (w - bbox[2] + bbox[0]) // 2
                y = (h - bbox[3] + bbox[1]) // 2
                draw.text((x, y), word, font=font, fill=color)
            
            # Convert RGBA to BGRA for OpenCV
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGBA2BGRA)
        else:
            # Original RGB rendering with background
            img = Image.new('RGB', (w, h), bg)
            draw = ImageDraw.Draw(img)
            
            if prev_word and prev_op > 0:
                color = tuple(int(f * prev_op + b * (1 - prev_op)) for f, b in zip(fg, bg))
                bbox = draw.textbbox((0, 0), prev_word, font=font)
                x = (w - bbox[2] + bbox[0]) // 2
                y = (h - bbox[3] + bbox[1]) // 2
                draw.text((x, y), prev_word, font=font, fill=color)
            
            if word and op > 0:
                color = tuple(int(f * op + b * (1 - op)) for f, b in zip(fg, bg))
                bbox = draw.textbbox((0, 0), word, font=font)
                x = (w - bbox[2] + bbox[0]) // 2
                y = (h - bbox[3] + bbox[1]) // 2
                draw.text((x, y), word, font=font, fill=color)
            
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def main():
    root = tk.Tk()
    app = TextVideoPlayer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
