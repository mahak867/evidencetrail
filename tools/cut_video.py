"""Turn the raw recording into the final MP4, speeding up the waiting scenes.
Also writes subtitles (SRT) and a timed voice-over script that match the final video."""
import json
import subprocess

d = json.load(open("scenes.json"))
sc = d["scenes"]
parts = []
for a, b in zip(sc, sc[1:]):
    if b["t"] - a["t"] > 0.2:
        parts.append({"name": a["name"], "s": a["t"], "e": b["t"], "speed": a.get("speed", 1)})

# map raw time -> final time
acc = 0.0
for p in parts:
    p["out"] = acc
    acc += (p["e"] - p["s"]) / p["speed"]
TOTAL = acc


def out_t(t):
    for p in parts:
        if p["s"] <= t < p["e"]:
            return p["out"] + (t - p["s"]) / p["speed"]
    return TOTAL


filters, labels = [], []
for i, p in enumerate(parts):
    filters.append(f"[0:v]trim=start={p['s']:.2f}:end={p['e']:.2f},setpts=(PTS-STARTPTS)/{p['speed']}[v{i}]")
    labels.append(f"[v{i}]")
filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0,fps=30,format=yuv420p[out]")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", d["video"], "-filter_complex", ";".join(filters), "-map", "[out]",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", "EvidenceTrail_demo.mp4"], check=True)


def ts(x, sep=","):
    h, r = divmod(x, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int((s % 1) * 1000):03d}"


# subtitles from the on-screen captions
caps = [c for c in d.get("caps", []) if c["text"]]
with open("EvidenceTrail_demo.srt", "w") as f:
    for i, c in enumerate(caps, 1):
        start = out_t(c["t"])
        nxt = out_t(caps[i]["t"]) if i < len(caps) else TOTAL
        f.write(f"{i}\n{ts(start)} --> {ts(min(nxt, start + 9))}\n{c['text']}\n\n")

LINES = {
    "title": "Hi, we're team EvidenceTrail from Chennai Institute of Technology. This is our entry for the NTT DATA track, problem statement two.",
    "problem": "When one service fails, alerts fire everywhere. And AI answers can't be trusted: the best agent on OpenRCA finds the true cause only eleven percent of the time.",
    "arch": "EvidenceTrail works in six steps: scan health, walk the call graph, prefetch evidence, let Gemini test hypotheses, gate every claim on evidence, and keep a human in charge.",
    "map_healthy": "Here's our nine-service test shop running live, with traces, metrics and logs.",
    "inject": "We inject a known fault: a bad deployment of the payment service.",
    "wait_incident": "Errors spread upstream. Checkout and frontend go red too, so which one is the real cause?",
    "investigate": "The on-call engineer pastes the alert and clicks Investigate. Watch each step complete live.",
    "retry": "Gemini's free tier was busy, so it retries automatically.",
    "verdict": "Root cause: payment, from a bad deploy, with confidence, time and token cost shown.",
    "graph": "The blast radius shows the failure path, and the timeline shows where every second went.",
    "claims": "Every claim links to real evidence. Click it and you see the exact log line or deploy event.",
    "approve": "The fix is labelled risky, shown as a dry run, and only runs after a named engineer approves it.",
    "recover": "After approval, the deploy rolls back and the services recover.",
    "scorecard": "We measure everything against two baselines on the same faults, and we report every miss.",
    "results": "Twelve out of twelve on root cause and fault type, zero confident wrong answers on the hard set, and seven made-up claims blocked.",
    "team": "Mahak built the agent, Roshini the interface, Kanish the test platform, and Annika the evaluation and research.",
    "close": "EvidenceTrail. Find the cause, show the evidence. Thank you.",
}
with open("VOICEOVER.md", "w") as f:
    f.write(f"# Voice-over script for EvidenceTrail_demo.mp4 ({TOTAL:.0f}s)\n\n"
            "Read each line when the video reaches its start time. Speak at a normal pace; each line fits its slot. "
            "Record on a phone in a quiet room, then add it as the audio track (CapCut, Clipchamp, iMovie or `ffmpeg -i EvidenceTrail_demo.mp4 -i voice.m4a -c:v copy -shortest out.mp4`).\n\n"
            "| Start | Slot | Scene | Say |\n|---|---|---|---|\n")
    for p in parts:
        dur = (p["e"] - p["s"]) / p["speed"]
        line = LINES.get(p["name"], "")
        if line:
            f.write(f"| {ts(p['out'], '.')[3:8]} | {dur:.0f}s | {p['name']} | {line} |\n")
print(f"final duration: {TOTAL:.1f}s · diagnosis ok: {d.get('ok')}")
