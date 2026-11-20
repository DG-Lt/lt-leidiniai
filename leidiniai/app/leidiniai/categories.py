"""Product categories: English ids in code and DB, Lithuanian labels in the panel.

Order of decisions for one product:
  1. a category the user set in the panel (products.category_locked)
  2. the shop's own category through `category_map` — 'strong' entries decide alone
  3. the keyword dictionary on the plain-letter key of the name's first phrase (up to ' su ', ' ar ',
     ' be ', 'įdarytas …' or a number). Lithuanian puts the head noun last ('kiaulienos dešra' is a sausage), so the
     rightmost matching word wins (a keyword the user taught always beats the seeds); then the longer keyword
  4. a 'weak' shop map entry (broad shop sections such as Rimi SH-9 'meat, fish, ready meals')
  5. 'other'
Seeds live here; the DB tables `category_keywords` and `category_map` hold the user's additions and
override seeds with the same key. Multilingual-e5-small is a later step (docs/findings.md).
"""
from __future__ import annotations

import re

from .textutil import fold

CATEGORIES: dict[str, str] = {
    "fruit_veg": "Vaisiai ir daržovės",
    "meat": "Mėsa ir paukštiena",
    "meat_products": "Mėsos gaminiai",
    "fish": "Žuvis ir jūros gėrybės",
    "dairy": "Pieno produktai ir kiaušiniai",
    "bakery": "Duona ir kepiniai",
    "ready_meals": "Kulinarija",
    "frozen": "Šaldytas maistas",
    "pantry": "Bakalėja",
    "sweets": "Saldumynai ir užkandžiai",
    "coffee_tea": "Kava ir arbata",
    "drinks": "Gėrimai",
    "alcohol": "Alkoholiniai gėrimai",
    "baby": "Kūdikiams ir vaikams",
    "pets": "Gyvūnams",
    "household": "Namų priežiūra",
    "hygiene": "Kosmetika ir higiena",
    "home": "Namai ir laisvalaikis",
    "plants": "Gėlės ir augalai",
    "other": "Kita",
}

# (chain, shop category) → (category, strength). Rimi codes are matched by prefix (SH-9-1-8 → SH-9-1 → SH-9);
# their meaning was inferred from product names in the 2026-11 lookups.
SHOP_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("maxima", "Vaisiai ir daržovės"): ("fruit_veg", "strong"),
    ("maxima", "Mėsa ir mėsos gaminiai"): ("meat", "weak"),
    ("maxima", "Pieno gaminiai ir kiaušiniai"): ("dairy", "strong"),
    ("maxima", "Žuvis ir žuvies produktai"): ("fish", "strong"),
    ("maxima", "Kulinarija"): ("ready_meals", "strong"),
    ("maxima", "Duonos gaminiai"): ("bakery", "strong"),
    ("maxima", "Šaldytas maistas"): ("frozen", "strong"),
    ("maxima", "Saldumynai"): ("sweets", "strong"),
    ("maxima", "Bakalėja"): ("pantry", "weak"),
    ("maxima", "Konservuotas maistas"): ("pantry", "strong"),
    ("maxima", "Kava, kakava, arbata"): ("coffee_tea", "strong"),
    ("maxima", "Gėrimai"): ("drinks", "weak"),
    ("maxima", "Kūdikių ir vaikų prekės"): ("baby", "strong"),
    ("maxima", "Kosmetika ir higiena"): ("hygiene", "strong"),
    ("maxima", "Pramonės prekės"): ("home", "weak"),
    ("maxima", "Augalai ir jų priežiūros prekės"): ("plants", "strong"),
    ("maxima", "Buitinė chemija"): ("household", "strong"),
    ("maxima", "Prekės gyvūnams"): ("pets", "strong"),
    ("maxima", "Konditerija"): ("bakery", "weak"),
    ("rimi", "SH-1"): ("alcohol", "weak"),
    ("rimi", "SH-2"): ("pantry", "weak"),
    ("rimi", "SH-3"): ("bakery", "strong"),
    ("rimi", "SH-4"): ("drinks", "weak"),
    ("rimi", "SH-5"): ("pets", "strong"),
    ("rimi", "SH-6"): ("hygiene", "weak"),
    ("rimi", "SH-7"): ("baby", "strong"),
    ("rimi", "SH-8"): ("plants", "weak"),
    ("rimi", "SH-9"): ("meat", "weak"),
    ("rimi", "SH-10"): ("household", "strong"),
    ("rimi", "SH-11"): ("dairy", "strong"),
    ("rimi", "SH-12"): ("sweets", "strong"),
    ("rimi", "SH-13"): ("frozen", "strong"),
    ("rimi", "SH-14"): ("home", "strong"),
    ("rimi", "SH-15"): ("fruit_veg", "strong"),
    ("rimi", "SH-19"): ("pantry", "weak"),
    ("rimi", "SH-20"): ("sweets", "strong"),
    ("rimi", "SH-77"): ("dairy", "weak"),
}

# Plain-letter stems, matched at the start of a word of the folded name (multi-word stems as a phrase).
_KW = {
    "fruit_veg": """silauog meliug abrikos figos datul razin chrizant obuol kriaus banan mandarin apelsin citrin greipfrut granat avokad mang persimon kivi vynuog
        slyv brask melion arbuz ananas ger mel sauleg agurk pomidor bulv morkos morku svogun cesnak kopust
        paprik salot spinat ridikel salier pievagryb grybai grybu baravyk cukinij moliug burok krap petrazol
        porai poru brokol ziedinis daržov darzov vaisi uogos citrus""",
    "meat": """saslyk kiaulien jautien versien aviena aviens kalakut viscuk visciuk broiler antien antis anciuk zasien
        faras farsas farsa sonkaul kepsn sprand mentes nugarin kumpio kepsnys filė file sparnel blauzdel
        ketvirc kiaulienos jautienos""",
    "meat_products": """desr desrel saliam kumpis kumpiui kumpio desra rukyt vytint sonine skiland fuet kabanos
        sardel parsel lasinuk pastet vynutin zasies kepenel""",
    "fish": """zuv lasis lasisa lasis lasisu silk menk skumbr tunas tun krevet midij kalmar upetak karpis karp
        lydek sprot ikrai jur gerybes zuvies surimi""",
    "dairy": """margarin pienas pieno sviest grietin grietinel jogurt kefyr varsk surelis surel suris surio mocarel
        parmez cedar kiausin kiausiniai pasukos ayran skyr fermentin mascarpone""",
    "bakery": """duon batonas baton bandel kepal ragelis rageliai pyrag keksas kekso bagete croissant kruasan
        sumustin tortilij lavas pita spurgos spurga""",
    "ready_meals": """salotos su picos pica cepelin koldun virtin blyn lietin kotlet kibin sriuba sriubos
        paruost kulinar""",
    "frozen": """saldyt uzsaldyt ledai ledu greitai uzsaldytos""",
    "pantry": """sirup dziuvesel dziuvesel migdol dziovint uztepel misrain panko miltai milt cukrus cukr druska ryziai ryzi makaron spaget grikiai kruop avizin dribsn
        aliejus aliej padaz kecup majonez garstyc actas prieskon konserv pupel zirneliai kukuruz alyvuog
        medus uogien dzem sultinys sultinio kruopos riesut seklos sekl""",
    "sweets": """hematogen ledinuk trapuc krekeri pyragel sokolad saldain sausain vafl batonel trasku traskuc cipsai cips zelė zele guminuk marmelad
        tortas tort zefyr chalva kramtom zele popkorn spragin breceli lazdeles advento""",
    "coffee_tea": """kava kavos kapsul arbat kakava espresso""",
    "drinks": """gira giros vanduo vandens sultys sulciu gaivus gazuot negazuot limonad energin izotonin nektar glotnut
        kokteil nealk nealkohol gerimas gerimai kola cola""",
    "alcohol": """alus alaus vynas vyno putojant degtin brendis viskis konjak romas dzinas likeris sidras
        trauktin sampan prosecco""",
    "baby": """kudik vaik sauskel tyrele tyrel misinys misinio pieno misin konstrukt lego zaisl""",
    "pets": """sun sunims sunu kac kacu katems kat kraikas edal pasar gyvun""",
    "household": """skalb plovikl indu valikl valymo tualet popier ranksluost servetel siuksl maisai
        maisu kempin oro gaiviklis minkstikl balikl""",
    "hygiene": """burnos lupu kauke samp dantu pasta dezodor muil dusas dusu kosmet krem veido plauk losjon skust higien
        paketai tamponai vatos""",
    "home": """sluota matavimo pele siurbl pustuv kabel lygintuv virdul sildytuv lemput kilimel kuprin apatin pirstin flomaster akumuliator elektrin rankin lekst puodel puod keptuv peilis rankšl antklod pagalv patalyn slepet kojin rubai marskin
        lempa baterij langu skystis irankiai irank zvak dekor kaledin eglut""",
    "plants": """chrizantem rozes roziu eleboras skintos gel puoked puoks orchid augal vazon zeme trasos""",
}
# a few stems above are deliberately short ("sun", "kat", "gel"): they only match at a word start
SEED_KEYWORDS: dict[str, str] = {}
for cat, words in _KW.items():
    for w in words.split():
        SEED_KEYWORDS.setdefault(fold(w), cat)
# phrases that must beat single words
SEED_KEYWORDS.update({
    "pieno misin": "baby", "sokoladinis pienas": "dairy", "zieminis langu": "home",
    "ledu kava": "coffee_tea", "saldytos uogos": "frozen", "saldytos darzoves": "frozen",
    "langu skystis": "home", "alaus kokt": "drinks", "nealk alaus": "drinks",
})


def label(cat: str | None) -> str:
    return CATEGORIES.get(cat or "other", CATEGORIES["other"])


def _keywords(conn) -> dict[str, tuple[str, int]]:
    kw = {k: (v, 0) for k, v in SEED_KEYWORDS.items()}
    if conn is not None:
        for r in conn.execute("SELECT keyword_key, category FROM category_keywords"):
            kw[r[0]] = (r[1], 1)
    return kw


def _shop_map(conn) -> dict[tuple[str, str], tuple[str, str]]:
    m = dict(SHOP_MAP)
    if conn is not None:
        for r in conn.execute("SELECT chain, ext_category, category, strength FROM category_map"):
            m[(r[0], r[1])] = (r[2], r[3])
    return m


class Classifier:
    """Load the dictionaries once per parse run."""

    def __init__(self, conn=None):
        self.kw = _keywords(conn)
        self.map = _shop_map(conn)

    def shop(self, chain: str, ext: str | None) -> tuple[str, str] | None:
        if not ext:
            return None
        if (chain, ext) in self.map:
            return self.map[(chain, ext)]
        parts = ext.split("-")
        for n in range(len(parts) - 1, 1, -1):  # SH-9-1-8 → SH-9-1 → SH-9
            k = "-".join(parts[:n])
            if (chain, k) in self.map:
                return self.map[(chain, k)]
        return None

    def _match(self, words: list[str]) -> str | None:
        best = None  # (user keyword, position of the last matched word, length, category)
        for k, (cat, user) in self.kw.items():
            kws = k.split()
            n = len(kws)
            for j in range(len(words) - n, -1, -1):
                if all(words[j + t].startswith(kws[t]) if t == n - 1 else words[j + t] == kws[t] for t in range(n)):
                    cand = (user, j + n - 1, len(k), cat)
                    if best is None or cand[:3] > best[:3]:
                        best = cand
                    break
        return best[3] if best else None

    def keyword(self, name: str) -> str | None:
        """Printed name (or a plain key) → category from the dictionary, or None."""
        head = re.split(r"\s(?:su|ar|be|įdaryt\w*|pagardint\w*)\s|\s\d", name, maxsplit=1)[0]
        return self._match(fold(head).split()) or self._match(fold(name).split())

    def classify(self, chain: str, name: str, ext_category: str | None) -> tuple[str, str]:
        """→ (category, source) where source is shop|keyword|shop_weak|none."""
        sm = self.shop(chain, ext_category)
        if sm and sm[1] == "strong":
            return sm[0], "shop"
        k = self.keyword(name)
        if k:
            return k, "keyword"
        if sm:
            return sm[0], "shop_weak"
        return "other", "none"
