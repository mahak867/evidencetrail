# Voice-over script for EvidenceTrail_demo.mp4 (147s)

Read each line when the video reaches its start time. Speak at a normal pace; each line fits its slot. Record on a phone in a quiet room, then add it as the audio track (CapCut, Clipchamp, iMovie or `ffmpeg -i EvidenceTrail_demo.mp4 -i voice.m4a -c:v copy -shortest out.mp4`).

| Start | Slot | Scene | Say |
|---|---|---|---|
| 00:00 | 6s | title | Hi, we're team EvidenceTrail from Chennai Institute of Technology. This is our entry for the NTT DATA track, problem statement two. |
| 00:06 | 9s | problem | When one service fails, alerts fire everywhere. And AI answers can't be trusted: the best agent on OpenRCA finds the true cause only eleven percent of the time. |
| 00:15 | 9s | arch | EvidenceTrail works in six steps: scan health, walk the call graph, prefetch evidence, let Gemini test hypotheses, gate every claim on evidence, and keep a human in charge. |
| 00:24 | 9s | map_healthy | Here's our nine-service test shop running live, with traces, metrics and logs. |
| 00:32 | 7s | inject | We inject a known fault: a bad deployment of the payment service. |
| 00:39 | 5s | wait_incident | Errors spread upstream. Checkout and frontend go red too, so which one is the real cause? |
| 00:44 | 25s | investigate | The on-call engineer pastes the alert and clicks Investigate. Watch each step complete live. |
| 01:09 | 7s | verdict | Root cause: payment, from a bad deploy, with confidence, time and token cost shown. |
| 01:16 | 7s | graph | The blast radius shows the failure path, and the timeline shows where every second went. |
| 01:23 | 13s | claims | Every claim links to real evidence. Click it and you see the exact log line or deploy event. |
| 01:36 | 10s | approve | The fix is labelled risky, shown as a dry run, and only runs after a named engineer approves it. |
| 01:46 | 3s | recover | After approval, the deploy rolls back and the services recover. |
| 01:49 | 14s | scorecard | We measure everything against two baselines on the same faults, and we report every miss. |
| 02:03 | 10s | results | Twelve out of twelve on root cause and fault type, zero confident wrong answers on the hard set, and seven made-up claims blocked. |
| 02:13 | 8s | team | Mahak built the agent, Roshini the interface, Kanish the test platform, and Annika the evaluation and research. |
| 02:21 | 6s | close | EvidenceTrail. Find the cause, show the evidence. Thank you. |
