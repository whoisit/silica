# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Countdown before a real-input GUI test (tools/dev.py): a red always-on-top note and a beep, so whoever sits at
the machine lets go of the mouse. It closes before the test starts, so it can never be under the moving cursor.

    python -I tools/handsoff.py [seconds] [test name]
"""
import sys


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    name = sys.argv[2] if len(sys.argv) > 2 else "a real-mouse test"
    try:
        import tkinter as tk
    except ImportError:
        print("HANDS OFF THE MOUSE: %s starts in %d s" % (name, secs), flush=True)
        import time
        time.sleep(secs)
        return
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
    root = tk.Tk()
    root.title("Silica test")
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.configure(bg="#b01515")
    w, h = 520, 150
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+%d+%d" % (w, h, sw - w - 30, sh - h - 80))      # bottom right, clear of the test window
    tk.Label(root, text="HANDS OFF THE MOUSE", fg="white", bg="#b01515", font=("Segoe UI", 20, "bold")).pack(pady=(14, 2))
    info = tk.Label(root, fg="white", bg="#b01515", font=("Segoe UI", 11))
    info.pack()
    tk.Label(root, text="until the Blender test window closes (a few seconds)", fg="white", bg="#b01515",
             font=("Segoe UI", 10)).pack()
    left = [secs]

    def tick():
        if left[0] <= 0:
            root.destroy()
            return
        info.configure(text="%s moves the cursor in %d s" % (name, left[0]))
        left[0] -= 1
        root.after(1000, tick)
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
