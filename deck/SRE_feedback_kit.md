# Practitioner feedback kit (needed by the NTT DATA brief)

The brief asks teams to "substantiate the chosen problem with … practitioner feedback". One or two short quotes from a real SRE / DevOps / platform engineer are enough. Annika owns this; everyone can help find people.

## Who to ask (in order of ease)
1. Seniors or alumni of Chennai Institute of Technology now working in DevOps, SRE, cloud or platform roles (LinkedIn search: "SRE" OR "DevOps" + "Chennai Institute of Technology").
2. Internship mentors or relatives working at IT services companies (TCS, Infosys, Zoho, Freshworks, NTT DATA, etc.).
3. Local communities: Kubernetes Chennai / CNCF Chennai meetups, DevOps India Discord or Slack groups.
4. Faculty who teach cloud computing (as a fallback; a working engineer is better).

Aim for 5 messages to get 1–2 replies. Ask for 10 minutes, not an hour.

## Message to send (copy, edit the name)

> Hi [Name], I'm [your name], a 1st-year CSE student at Chennai Institute of Technology. Our team is building **EvidenceTrail** for the CODERED '26 hackathon (NTT DATA track): a Gemini-powered tool that helps on-call engineers find the root cause of an incident, where every conclusion must link to a real log line, trace or metric, and no fix runs without human approval.
>
> Could I take 10 minutes of your time (call or text) for 4 quick questions about how you investigate incidents today? A 2-minute screen recording of the prototype is here: [video link]. Thank you!

## The 4 questions
1. When an alert fires, what takes the longest before you know which service is actually broken?
2. Have you used AI tools (ChatGPT, Gemini, Copilot, vendor AIOps) during an incident? What made you trust or distrust the answer?
3. Looking at the demo: would a diagnosis where every claim links to its evidence change how much you'd trust it? What's missing?
4. Would your team try something like this on a test environment? What would stop you (data privacy, cost, integration)?

## What to record (for the deck and Round 2)
| Name (or "SRE, 5 yrs, fintech") | Company type | Biggest pain | Quote we can use | Would they try it? |
|---|---|---|---|---|
| | | | | |

Ask permission before using their name. "Senior SRE at a Bengaluru fintech" is fine if they prefer to stay anonymous.

## How we'll use it
- Slide 2 (problem): one quote under "The problem".
- Round 2 pitch: "We tested with N practitioners; they asked for X, so we built X."
- README: a "Practitioner feedback" section, which the brief asks for.
