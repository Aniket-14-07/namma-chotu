"""Keyword lexicon for khata speech (Hinglish + romanised Hindi + English).

Words are compared by phonetic key (`pkey`) so udhaar/udhar/उधार all match.
"""
from __future__ import annotations

from .romanize import pkey


def _keys(words: str) -> frozenset[str]:
    return frozenset(pkey(w) for w in words.split())


CREDIT_STRONG = _keys("udhaar udhar udhaari udhari udhaarr baaki baki bakaya credit due dues "
                      "khata khate khaate udri udhri udhaara saala")
CREDIT_WEAK = _keys("likh likho likhna likhdo likhiye likhe likha daal daalo dal dalo daaldo add jod jodo "
                    "jodna joddo chadha chadhao chadhana charge saaman saman samaan "
                    "maal kharida kharide khareeda kharidi bari bariri bareyiri barko barkoli barkolli haaku haaki haakbidi haakri seri serisi")
TAKE_VERB = _keys("liya liye li le lena lekar liyaa took taken tagondru togondru tegedukondru tagondu togondu tagondidaare togondidaare kondru kondukondru tagonda togonda")
PAYMENT_STRONG = _keys("jama payment paid pay paying received receive recieved recive mila mile mili "
                       "chukaya chukaye chukayi chuka chukta wapas vapas lautaya lautaye lautayi bhara bhare "
                       "bhari upi gpay phonepe paytm online aaya aaye aayi aya aye kattidru kattidaare kattida kattidaru kattiddare")
PAYMENT_VERB = _keys("diya diye di de dediya dedia diyaa dete gave given kotru kottru kottaru kotta kotte kottidru kottidaare kottidaane kottiddare kottide kottiddaare kottidare")
FUTURE = _keys("dega degi denge dunga dungi doonga karega karegi karenge bhejega bhejegi lautayega "
               "chukayega chukayegi will tomorrow baadmein kodtaare kodtaane kodtini kodthare kodthane kodtare kodbahudu naale kodtivi kodthaare kodtaale")
NEG = _keys("nahi nahin nai nahee nahiin no not mat illa ill beda bedi alla")
CORRECTION = _keys("galat wrong sorry matlab actually change badlo badal correction galti tappu")
UNDO = _keys("cancel undo hatao hata hatado hataa mitao mita mitado delete remove radd tegi tegedu tegedubidi tegdbidi")
YES = _keys("haan han haa haanji haji yes yeah yep yup sahi theek thik ok okay correct bilkul right "
            "done hanji kardo houdu haudu howdu sari aaythu aitu")
QUERY = _keys("kitna kitne kitni kya total balance hisaab hisab batao bata bataiye bolo dikhao how "
              "what kaun kis kisne kiska kiske kiski sabse top list kab when status show tell eshtu estu yeshtu ottu yaaru yaaradu yaarige helu heli torisu yaavaga")
LAST = _keys("last aakhri akhri pichhla pichhli pichle pichhle latest previous kone koneya")
WHEN = _keys("kab when yaavaga")
MOST = _keys("zyada jyada jada adhik most highest maximum sabse jaasti hechchu")
TOP = _keys("top")
CUSTOMERS = _keys("customer customers grahak graahak log logon giraaki giraakigalu grahakaru")
OUTSTANDING = _keys("market bazaar bazar pending kul outstanding baahar bahar")
ALL = _keys("sab sabka saare sare saara sara all total kul")
WHO_LIST = _keys("kaun kis")
SUMMARY = _keys("business dhanda dhandha bikri sale sales summary hisaab hisab report vyapaara vyaapaara lekka")
REMINDER = _keys("reminder remind yaad yaaddilao message msg sms whatsapp")
GREETING = _keys("hello namaste namaskar hey")
CONNECTOR_SPLIT = frozenset({"aur", "and", "phir", "fir", "then", "uske", "baad"})
ORDINALS = {pkey("pehla"): 0, pkey("pehle"): 0, pkey("pahla"): 0, pkey("pehli"): 0, pkey("first"): 0,
            pkey("doosra"): 1, pkey("dusra"): 1, pkey("doosre"): 1, pkey("dusre"): 1, pkey("second"): 1,
            pkey("teesra"): 2, pkey("tisra"): 2, pkey("third"): 2}

# time words
TODAY = _keys("aaj aj today abhi ivattu ivathu indu ivattina")
KAL = _keys("kal yesterday ninne")  # "kal" is resolved to yesterday for ledger entries (past tense)
PARSO = _keys("parso parson parsun parsoon monne")
DAY_BEFORE = frozenset()  # "day before yesterday" handled as phrase
DIN = _keys("din days day")
PEHLE = _keys("pehle pahle ago before")
WEEK = _keys("hafte hafta hapta hapte week vaara")
MONTH = _keys("mahine mahina month tingalu tingala")
THIS = _keys("is iss this ee")
PREV = _keys("pichhle pichle last previous hoda")
RAAT = _keys("raat night")
WEEKDAYS = {
    **{pkey(w): 0 for w in ("somvar", "somwar", "monday", "som")},
    **{pkey(w): 1 for w in ("mangalvar", "mangalwar", "mangal", "tuesday")},
    **{pkey(w): 2 for w in ("budhvar", "budhwar", "budh", "wednesday")},
    **{pkey(w): 3 for w in ("guruvar", "guruwar", "brihaspativar", "veervar", "thursday")},
    **{pkey(w): 4 for w in ("shukravar", "shukrawar", "shukra", "friday")},
    **{pkey(w): 5 for w in ("shanivar", "shaniwar", "shani", "saturday")},
    **{pkey(w): 6 for w in ("ravivar", "raviwar", "itvar", "itwar", "sunday")},
}

PARTICLES = _keys("ka ki ke ne ko se wala wale wali waale ji jee avaru avru avara avra avrige avarige avrinda avarinda ge")
KO = pkey("ko")
NE = pkey("ne")
SE = pkey("se")
KA = pkey("ka")
KO_SET = _keys("ko ge ige kke avrige avarige")          # dative: goods given TO the customer -> credit
SE_SET = _keys("se inda avrinda avarinda")             # from: money taken FROM the customer -> payment

# Kannada case endings glued to names: rameshge (to Ramesh), rameshinda (from), rameshavru (Ramesh, subject)
NAME_SUFFIXES = [
    ("avarinda", SE), ("avrinda", SE), ("avarige", KO), ("avrige", KO), ("anige", KO), ("avaru", NE), ("avara", KA),
    ("avru", NE), ("avra", KA), ("inda", SE), ("ninda", SE), ("ige", KO), ("kke", KO), ("ana", KA), ("ge", KO),
    ("an", KA), ("na", KA), ("ru", NE),
]

# Guardrails
LENDING = _keys("byaaj byaj biyaj interest sood soodh loan baddi badi emi karza karz")
THREAT = _keys("police dhamki warna varna court legal maarunga marunga beizzati bezzati insult jail thana "
               "bedarike")
WAKE = _keys("chotu chhotu chotuu chhotuu chottu")

# Words that can never be part of a customer name.
STOP = frozenset().union(
    CREDIT_STRONG, CREDIT_WEAK, TAKE_VERB, PAYMENT_STRONG, PAYMENT_VERB, FUTURE, NEG, CORRECTION, UNDO, YES, QUERY,
    LAST, MOST, TOP, CUSTOMERS, OUTSTANDING, ALL, SUMMARY, REMINDER, GREETING, TODAY, KAL, PARSO, DIN,
    PEHLE, WEEK, MONTH, THIS, PREV, RAAT, PARTICLES, frozenset(WEEKDAYS),
    _keys("me mein mai main hai hain tha thi the ho hua hue hui raha rahe rahi bhai sahab saab aap tum "
          "mera mere meri apna apne is us ye yeh vo woh wo aur and a an of to for in on was please plz "
          "kar karo kardo karna kariye karke do dena dijiye account naam name entry rupaye rupees rs paise "
          "paisa rupay ab abhi bhi to toh tak par pe se liye vala hisaab ek baar kuch sirf only total "
          "the is it its my he she they paisa paise rupiya rupaya rupaiya uska uski uske unka unki inka "
          "naya new customer add aaya gaya gaye gayi le lo diya fir phir aur jo jab tab ok haan nahi "
          "maadi madi maadu beku ide ittu aagide aaytu hoytu nimma nanna ella swalpa alli inda kke ige "
          "rupaayi rupayi chotu chhotu chotuu hogide aagi"),
    frozenset(ORDINALS),
)
