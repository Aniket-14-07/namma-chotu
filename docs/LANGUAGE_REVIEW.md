# Language review (Kannada + Hindi) for the team's native speakers

Claude wrote these. Before the demo, a fluent speaker should read every line aloud.
Fix wording directly in `app/responses.py` (dict `T`) and keywords in `app/nlu/lexicon.py`,
then run `pytest -q` to check nothing broke. Keep replies **short**: every extra word adds TTS latency.

## Things to check first
- **ಉದ್ರಿ (udri)** for credit. Is this what Bengaluru kirana owners actually say, or ಸಾಲ / ಬಾಕಿ?
- **ಜಮಾ** for payment. Natural, or would they say ಕೊಟ್ಟರು / ಕಟ್ಟಿದರು?
- **Amounts are spoken as digits** in Kannada ("340 ರೂಪಾಯಿ") and Timbre reads them. Run
  `python scripts/smoke_tts.py "ರಮೇಶ್ ಕುಮಾರ್: 340 ರೂಪಾಯಿ ಉದ್ರಿ. ಒಟ್ಟು ಬಾಕಿ 1240 ರೂಪಾಯಿ." kn-IN` and listen.
- Kannada words the parser understands (add any your shop-talk uses):
  udri, baaki, saala, bari/bareyiri/barko, haaku, kottru/kottaru/kotte, tagondru/togondru, jama, ninne, monne,
  ivattu, naale + kodtaare (future, no write), illa/alla (correction), houdu/sari (yes), eshtu/ottu (how much / total),
  yaaru/jaasti (who most), tegi (remove), numbers: munnooru nalavattu, eradu saavira, ippattaidu...

## Reply phrasebook

| key | ಕನ್ನಡ | हिंदी | English |
|---|---|---|---|
| greeting | ನಮಸ್ಕಾರ! ನಾನು ನಮ್ಮ ಛೋಟು, ಒಂದು AI ಸಹಾಯಕ. ಉದ್ರಿ ಅಥವಾ ಜಮಾ ಹೇಳಿ, ನಾನು ಖಾತೆಯಲ್ಲಿ ಬರೆಯುತ್ತೇನೆ. | नमस्ते! मैं नम्मा छोटू हूँ, एक AI सहायक। उधार या जमा बोलिए, मैं खाते में लिख दूँगा। | Hello! I'm Namma Chotu, an AI assistant. Tell me any credit or payment and I'll record it. |
| disclosure | ನಾನು ಒಂದು AI ಸಹಾಯಕ.  | मैं एक AI सहायक हूँ।  | I'm an AI assistant.  |
| credit | ಉದ್ರಿ | उधार | credit |
| payment | ಜಮಾ | जमा | payment |
| stop | .  | ।  | .  |
| corrected | ಸರಿ ಮಾಡಿದೆ.  | ठीक किया।  | Corrected.  |
| due | ಒಟ್ಟು ಬಾಕಿ {a}. | कुल बाकी {a}। | Total due {a}. |
| nothing_due | ಈಗ ಏನೂ ಬಾಕಿ ಇಲ್ಲ. | अब कुछ बाकी नहीं। | Nothing due now. |
| advance | {a} ಮುಂಗಡ ಇದೆ. | {a} एडवांस है। | {a} in advance. |
| ask_which | ಯಾವ {first}? {opts}? | कौन से {first}? {opts}? | Which {first}? {opts}? |
| or |  ಅಥವಾ  |  या  |  or  |
| ask_new_customer | {name} ಹೆಸರಿನ ಗ್ರಾಹಕರು ಇಲ್ಲ. ಹೊಸ ಖಾತೆ ತೆರೆಯಲೇ? | {name} नाम का कोई ग्राहक नहीं है। नया खाता बनाऊँ? | There's no customer named {name}. Shall I open a new account? |
| ask_amount | {name} ಎಷ್ಟು ರೂಪಾಯಿ {kind}? | {name} के कितने रुपये {kind}? | How much {kind} for {name}? |
| ask_customer | {a} ಯಾರ ಹೆಸರಿಗೆ ಬರೆಯಲಿ? | {a} किसके नाम लिखूँ? | Whose account should I put {a} in? |
| confirm_q | . ಸರಿನಾ? | । सही है? | . Is that right? |
| overpay | {name} ಬಾಕಿ ಕೇವಲ {bal}. {a} ಜಮಾ ಮಾಡಲೇ? {adv} ಮುಂಗಡ ಉಳಿಯುತ್ತದೆ. | {name} का बाकी सिर्फ़ {bal} है। {a} जमा करूँ? {adv} एडवांस रहेगा। | {name} only owes {bal}. Record {a}? {adv} will stay as advance. |
| overpay_zero | {name} ಏನೂ ಬಾಕಿ ಇಲ್ಲ. {a} ಮುಂಗಡ ಜಮಾ ಮಾಡಲೇ? | {name} का कोई बाकी नहीं है। {a} एडवांस जमा करूँ? | {name} owes nothing. Record {a} as advance? |
| cancelled | ಸರಿ, ಏನೂ ಬರೆದಿಲ್ಲ. | ठीक है, कुछ नहीं लिखा। | Okay, nothing recorded. |
| nothing_to_undo | ತೆಗೆಯಲು ಯಾವುದೇ ಹೊಸ ಎಂಟ್ರಿ ಇಲ್ಲ. | हटाने के लिए कोई ताज़ा एंट्री नहीं है। | There's no recent entry to remove. |
| nothing_to_correct | ಸರಿಪಡಿಸಲು ಯಾವುದೇ ಹೊಸ ಎಂಟ್ರಿ ಇಲ್ಲ. ಪೂರ್ತಿ ಎಂಟ್ರಿ ಮತ್ತೆ ಹೇಳಿ. | ठीक करने के लिए कोई ताज़ा एंट्री नहीं है। पूरी एंट्री दोबारा बोलिए। | There's no recent entry to correct. Please say the full entry again. |
| duplicate | ಈ ಎಂಟ್ರಿ ಈಗಾಗಲೇ ಬರೆದಿದ್ದೇನೆ. | ये एंट्री अभी लिख चुका हूँ। | I've already recorded that entry. |
| not_understood | ಕ್ಷಮಿಸಿ, ಅರ್ಥ ಆಗಲಿಲ್ಲ. ಹೀಗೆ ಹೇಳಿ: ರಮೇಶ್ ಮುನ್ನೂರ ನಲವತ್ತು ಉದ್ರಿ. | माफ़ कीजिए, समझ नहीं आया। ऐसे बोलिए: रमेश का तीन सौ चालीस उधार। | Sorry, I didn't get that. Try: Ramesh, 340 credit. |
| greeting_reply | ನಮಸ್ಕಾರ! ಯಾರ ಲೆಕ್ಕ ಬರೆಯಲಿ? | नमस्ते! बताइए, किसका हिसाब लिखूँ? | Hello! Whose account shall I update? |
| yes_no_pending | ಹೇಳಿ? | जी, बताइए? | Yes, go ahead? |
| unknown_customer | {name} ಹೆಸರಿನ ಗ್ರಾಹಕರು ಸಿಗಲಿಲ್ಲ. | {name} नाम का कोई ग्राहक नहीं मिला। | I couldn't find a customer named {name}. |
| future | ಸರಿ, {name} ಹಣ ಕೊಟ್ಟಾಗ ಹೇಳಿ. ಈಗ ಏನೂ ಬರೆದಿಲ್ಲ. | ठीक है, जब {name} पैसे देंगे तब बताइए। अभी कुछ नहीं लिखा। | Okay, tell me when {name} actually pays. Nothing recorded yet. |
| someone | ಗ್ರಾಹಕರು | ग्राहक | the customer |
| negation | ಸರಿ, ಏನೂ ಬರೆದಿಲ್ಲ. | ठीक है, कुछ नहीं लिखा। | Okay, nothing recorded. |
| reminder_no_optin | {name} ಅವರು ನೆನಪಿನ ಸಂದೇಶಕ್ಕೆ ಒಪ್ಪಿಗೆ ಕೊಟ್ಟಿಲ್ಲ, ಹಾಗಾಗಿ ನಾನು ಕಳಿಸುವುದಿಲ್ಲ. | {name} ने याद-संदेश के लिए हाँ नहीं कहा है, इसलिए मैं नहीं भेजूँगा। | {name} hasn't agreed to reminders, so I won't send one. |
| reminder_ready | {name} ಅವರಿಗೆ ಒಂದು ವಿನಯದ ನೆನಪಿನ ಸಂದೇಶ ಸಿದ್ಧ. ಕಳಿಸುವ ಬಟನ್ ಸ್ಕ್ರೀನ್ ಮೇಲೆ ಇದೆ. | {name} के लिए एक विनम्र याद-संदेश तैयार है। भेजने का बटन स्क्रीन पर है। | A polite reminder for {name} is ready. The send button is on screen. |
| reminder_zero | {name} ಅವರದು ಏನೂ ಬಾಕಿ ಇಲ್ಲ, ನೆನಪಿನ ಸಂದೇಶ ಬೇಕಿಲ್ಲ. | {name} का कोई बाकी नहीं है, याद-संदेश की ज़रूरत नहीं। | {name} owes nothing, no reminder needed. |
| refuse_lending | ಕ್ಷಮಿಸಿ, ನಾನು ಬಡ್ಡಿ ಅಥವಾ ಸಾಲದ ಲೆಕ್ಕ ಇಡುವುದಿಲ್ಲ. ಸಾಮಾನಿನ ಉದ್ರಿ ಮತ್ತು ಜಮಾ ಮಾತ್ರ ಬರೆಯುತ್ತೇನೆ. | माफ़ कीजिए, मैं ब्याज या लोन का हिसाब नहीं रखता। सिर्फ़ सामान का उधार और जमा लिखता हूँ। | Sorry, I don't handle interest or loans. I only record goods on credit and payments. |
| refuse_pressure | ಕ್ಷಮಿಸಿ, ನಾನು ಬೆದರಿಕೆ ಅಥವಾ ಒತ್ತಡದ ಸಂದೇಶ ಕಳಿಸುವುದಿಲ್ಲ. ಬೇಕಾದರೆ ವಿನಯದ ನೆನಪಿನ ಸಂದೇಶ ಮಾಡಬಹುದು. | माफ़ कीजिए, मैं धमकी या दबाव वाला संदेश नहीं भेजता। चाहें तो एक विनम्र याद-संदेश बना सकता हूँ। | Sorry, I don't send threatening or pressuring messages. I can prepare a polite reminder instead. |
| kept_pending_dropped | ಹಿಂದಿನ ಪ್ರಶ್ನೆ ಬಿಟ್ಟೆ.  | पिछला सवाल छोड़ दिया।  | Dropped the earlier question.  |
| new_customer_created | ಹೊಸ ಖಾತೆ: {name}.  | नया खाता बना: {name}।  | New account: {name}.  |
| undo_done | {name} ಅವರ {a} {kind} ಎಂಟ್ರಿ ತೆಗೆದೆ.  | {name} की {a} {kind} वाली एंट्री हटा दी।  | Removed {name}'s {a} {kind} entry.  |
| balance_pos | {name} ಒಟ್ಟು ಬಾಕಿ {a}. | {name} का कुल बाकी {a} है। | {name} owes {a} in total. |
| balance_zero | {name} ಏನೂ ಬಾಕಿ ಇಲ್ಲ. | {name} का कोई बाकी नहीं है। | {name} owes nothing. |
| balance_neg | {name} ಅವರದು {a} ಮುಂಗಡ ಇದೆ. | {name} का {a} एडवांस जमा है। | {name} has {a} in advance. |
| last_payment | {name} ಕೊನೆಯದಾಗಿ {d} {a} ಕೊಟ್ಟಿದ್ದಾರೆ. | {name} ने आख़िरी बार {d} {a} दिए थे। | {name} last paid {a} on {d}. |
| last_credit | {name} ಕೊನೆಯ ಉದ್ರಿ {d} {a}. | {name} का आख़िरी उधार {d} {a} था। | {name} last took credit of {a} on {d}. |
| no_entries | {name} ಅವರ ಯಾವುದೇ ಎಂಟ್ರಿ ಇಲ್ಲ. | {name} की कोई एंट्री नहीं है। | No entries for {name}. |
| period_credit | {p} {a} ಉದ್ರಿ ಹೋಗಿದೆ, {n} ಎಂಟ್ರಿ. | {p} {a} उधार गया, {n} एंट्री। | {p}: {a} given on credit, {n} entries. |
| period_payment | {p} {a} ಜಮಾ ಆಗಿದೆ, {n} ಎಂಟ್ರಿ. | {p} {a} जमा हुए, {n} एंट्री। | {p}: {a} received, {n} entries. |
| period_none | {p} ಯಾವುದೇ {kind} ಎಂಟ್ರಿ ಇಲ್ಲ. | {p} कोई {kind} एंट्री नहीं हुई। | {p}: no {kind} entries. |
| period_summary | {p} {a} ಉದ್ರಿ ಹೋಗಿದೆ, {b} ಜಮಾ ಆಗಿದೆ. | {p} {a} उधार गया और {b} जमा हुए। | {p}: {a} on credit, {b} received. |
| outstanding | ಒಟ್ಟು {a} ಮಾರ್ಕೆಟ್‌ನಲ್ಲಿ ಬಾಕಿ ಇದೆ, {n} ಗ್ರಾಹಕರ ಮೇಲೆ. | कुल {a} बाज़ार में बाकी है, {n} ग्राहकों पर। | Total {a} is pending with {n} customers. |
| top_none | ಯಾರ ಮೇಲೂ ಉದ್ರಿ ಬಾಕಿ ಇಲ್ಲ. | किसी पर उधार बाकी नहीं है। | Nobody owes anything. |
| top_one | ಅತಿ ಹೆಚ್ಚು ಉದ್ರಿ {name} ಮೇಲೆ, {a}. | सबसे ज़्यादा उधार {name} पर है, {a}। | {name} owes the most, {a}. |
| top_many | ಅತಿ ಹೆಚ್ಚು ಉದ್ರಿ:  | सबसे ज़्यादा उधार:  | Top dues:  |
| customer_count | ನಿಮಗೆ {n} ಗ್ರಾಹಕರು ಇದ್ದಾರೆ, ಅವರಲ್ಲಿ {m} ಜನರ ಮೇಲೆ ಉದ್ರಿ ಬಾಕಿ ಇದೆ. | आपके {n} ग्राहक हैं, जिनमें से {m} पर उधार बाकी है। | You have {n} customers; {m} of them owe money. |
