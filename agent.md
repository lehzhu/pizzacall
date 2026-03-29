# Biggest Lessons Learned

1. Do not ship blind IVR progression as the primary path.
Prompt-driven IVR handling is mandatory. Hardcoding DTMF and fixed phase progression caused wrong behavior on real calls and made personal-number tests misleading.

2. The voice agent must optimize for turn-taking discipline before anything else.
Talking over IVRs, hold audio, or uncertain pickup states breaks the call faster than weak phrasing does. Silence is often the correct action.

3. Human detection must be conservative.
A permissive classifier promoted IVR prompts into human conversation and caused the agent to speak at the wrong time. False positives are worse than extra waiting.

4. Prompt quality matters, but plumbing quality matters more.
A stronger "you are the customer" prompt improved behavior, but the larger failures were media timing, transcript quality, websocket lifecycle, and state transitions.

5. Deterministic policy should constrain the model, not replace it.
Business rules like substitutions, budget limits, extras rejection, and completion criteria should stay deterministic. The model should handle phrasing and transcript interpretation within those limits.

6. Telephony race conditions are real.
Twilio status callbacks, voice webhooks, and websocket media start events can arrive in different orders. The state machine must tolerate that instead of assuming an ideal sequence.

7. Audio format and transport details directly affect perceived quality.
Using the provider's native telephony format was better than homemade transcoding. Low-level media mistakes show up immediately to the callee.

8. Self-calls are useful but noisy.
They exposed real issues quickly, especially with IVR detection and transcript quality, but they also produced noisy transcripts that made debugging harder.

9. Logging was useful, but not complete enough.
The JSONL logs preserved transcripts and major events, which helped isolate failures. Missing per-event timestamps and provider latency metrics made turn-latency analysis weak.

10. The shortest path to reliability is to make the call path boring.
The next implementation should prioritize a narrow, repeatable flow:
- prompt-driven IVR handling
- strict silence rules
- conservative human detection
- timestamped observability
- minimal moving parts on the live audio path
