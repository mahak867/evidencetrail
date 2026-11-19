"""Turn the raw recording into the final MP4: speed up the waiting scenes, keep the rest real-time."""
import json
import subprocess

d = json.load(open("scenes.json"))
sc = d["scenes"]
parts = []
for a, b in zip(sc, sc[1:]):
    dur = b["t"] - a["t"]
    if dur > 0.2:
        parts.append((a["t"], b["t"], a.get("speed", 1)))
filters, labels = [], []
for i, (s, e, sp) in enumerate(parts):
    filters.append(f"[0:v]trim=start={s:.2f}:end={e:.2f},setpts=(PTS-STARTPTS)/{sp}[v{i}]")
    labels.append(f"[v{i}]")
filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0,fps=30,format=yuv420p[out]")
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", d["video"], "-filter_complex", ";".join(filters), "-map", "[out]",
       "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", "EvidenceTrail_demo.mp4"]
subprocess.run(cmd, check=True)
out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "EvidenceTrail_demo.mp4"],
                     capture_output=True, text=True).stdout.strip()
print("final duration (s):", out)
