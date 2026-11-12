# Manual voice test checklist (real Gnani, real phone)

Run on the phone you'll demo with, over the HTTPS tunnel. Play shop noise from a second phone at roughly 60 to 65 dB (a YouTube "Indian market ambience" clip, about an arm's length away). Tick each item and write down the latency shown in the header.

**Pass rule:** exact amount, right customer, right direction, right date, and the balance on the Khata tab matches.

| # | Say | Expect | Quiet | Noise | Latency |
|---|---|---|---|---|---|
| 1 | (tap Shuru karein) | Greeting says it's an AI sahayak | | | |
| 2 | Suresh ka teen sau chaalis udhaar | Suresh +₹340 | | | |
| 3 | Suresh ka three-forty | Suresh +₹340 | | | |
| 4 | Amit ka barah sau pachaas | Amit +₹1,250 | | | |
| 5 | Ramesh ka 340 udhaar, kal 200 diya tha | Asks "कौन से रमेश?" | | | |
| 6 | Kumar wale | Ramesh Kumar +₹340 today, −₹200 yesterday | | | |
| 7 | nahi, 430 | The ₹200 becomes ₹430; old one struck through | | | |
| 8 | Ramesh nahi Suresh | Entry moves to Suresh | | | |
| 9 | kal nahi, parso | Date moves to day before yesterday | | | |
| 10 | last entry cancel karo | Last entry voided | | | |
| 11 | Ramesh Kumar ka total? | Correct balance, answered within 2 s | | | |
| 12 | Aaj kitna udhaar gaya? | Matches Hisaab tab | | | |
| 13 | Kitna paisa market mein pending hai? | Matches Hisaab tab | | | |
| 14 | Sabse zyada udhaar kispe hai? | Top debtor | | | |
| 15 | Suresh kal 200 dega | Nothing written | | | |
| 16 | Mahesh ka 250 udhaar likho → haan | New account, +₹250 | | | |
| 17 | Priya ne 900 diye | Asks about advance | | | |
| 18 | Hold the button while the agent is talking | Agent stops instantly | | | |
| 19 | Hands-free: talk over the reply | Agent stops (barge-in) | | | |
| 20 | English: "How much does Gupta ji owe?" | English answer + AI disclosure line | | | |
| 21 | Kannada/Bengali sentence with a number | Correct entry (needs LLM fallback if the parser misses it) | | | |
| 22 | Gupta ji ko reminder bhejo / Ramesh Sharma ko reminder bhejo | Ready / refused (no opt-in) | | | |

If a number is wrong, note what the transcript bubble shows. If the transcript is right but the entry is wrong, that's a parser fix (send me the sentence). If the transcript is wrong, tune `keyterms`, `GNANI_VAD_THRESHOLD` or the language hints.
