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
    "hygiene": """burnos lupu kauke samp dantu pasta dezodor muil dusas dusu kosmet veido plauk losjon skust higien
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
    # "kremas" alone is food as often as cosmetics (varškės kremas, šokoladinis kremas): only these are cosmetics
    "veido krem": "hygiene", "ranku krem": "hygiene", "kuno krem": "hygiene", "akiu krem": "hygiene",
    "pedu krem": "hygiene", "dienos krem": "hygiene", "nakties krem": "hygiene", "saules krem": "hygiene",
    "apsauginis krem": "hygiene", "kremas rank": "hygiene", "kremas veid": "hygiene", "kremas kun": "hygiene",
    "kremas ped": "hygiene", "skalbimo kaps": "household", "indaplov": "household",
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


# ------------------------------------------------------------------ learning from similar names
# Maxima and Rimi put every offer in a category of their own, and the user corrects some by hand. Those products
# are "examples"; a new name gets the category most of its most similar examples have. Similar = sharing
# informative word stems (rare stems count more), so "Varškės kremas su vanile" lands next to Maxima's dairy
# desserts, not next to hand cream. Nothing about products is written here: it all comes from the database.
STOP = set("""su ir be ar is i per po nuo iki uz ant del prie kaip tik su g kg ml l cl vnt pak but ind dez rit lap
    rusiu rus rusies vnt proc rieb s m a r x pvz kompl dydziu spalvu ivairiu ivairus ivairios skoniu kvapu
    fasuot fasuotas fasuoti fasuota sveriamas sveriama sveriami vakuumuota supakuota pakuoteje pakuote
    naujiena akcija premium mini maxi didele didelis mazas""".split())
STEM = 5          # Lithuanian endings change, the start of the word stays: "kiaulien|a/os/ai"
MIN_SCORE = 0.35  # weighted Dice overlap of the stems of the name and of an example (0..1)
MIN_SUPPORT = 0.9  # summed similarity of the winning category (about two good neighbours)


def stems(name_or_key: str) -> list[str]:
    out = []
    for w in fold(name_or_key).split():
        if len(w) < 3 or w in STOP or not w[0].isalpha() or any(c.isdigit() for c in w):
            continue
        s = w[:STEM]
        if s not in out:
            out.append(s)
    return out


class Similar:
    """Inverted index over example products: stem → [(example, weight)]."""

    def __init__(self, examples: list[tuple[str, str, float]]):  # (name, category, weight)
        import math
        self.ex = []
        self.index: dict[str, list[int]] = {}
        for name, cat, w in examples:
            st = stems(name)
            if not st or cat not in CATEGORIES or cat == "other":
                continue
            i = len(self.ex)
            self.ex.append((set(st), cat, w))  # weights summed below once idf is known
            for s in st:
                self.index.setdefault(s, []).append(i)
        n = max(1, len(self.ex))
        self.idf = {s: math.log(1 + n / len(ids)) for s, ids in self.index.items()}
        self.mass = [sum(self.idf[s] for s in st) for st, _, _ in self.ex]

    def __len__(self):
        return len(self.ex)

    def guess(self, name: str, k: int = 7) -> tuple[str, float] | None:
        """→ (category, confidence 0..1) or None when the examples don't agree or nothing is similar enough."""
        st = [s for s in stems(name) if s in self.idf]
        if not st:
            return None
        # unknown stems still count in the name's mass (as rare words): "Mangas" vs "Mango jogurtas" stays apart
        rare = max(self.idf.values())
        total = sum(self.idf.get(s, rare) for s in stems(name))
        scores: dict[int, float] = {}
        shared: dict[int, int] = {}
        for s in st:
            for i in self.index[s]:
                scores[i] = scores.get(i, 0.0) + self.idf[s]
                shared[i] = shared.get(i, 0) + 1
        # one word in common is not enough ("Mangas" ≠ "Mango jogurtas"): single words are the keyword list's job
        best = sorted(((2 * v / (total + self.mass[i]), i) for i, v in scores.items() if shared[i] >= 2),
                      reverse=True)[:k]
        votes: dict[str, float] = {}
        for sim, i in best:
            if sim >= MIN_SCORE:
                votes[self.ex[i][1]] = votes.get(self.ex[i][1], 0.0) + sim * self.ex[i][2]
        if not votes:
            return None
        cat, v = max(votes.items(), key=lambda x: x[1])
        share = v / sum(votes.values())
        if v < MIN_SUPPORT or share < 0.6:
            return None
        return cat, round(share, 2)


def _examples(conn) -> list[tuple[str, str, float]]:
    """Products whose category a person or the shop decided: user corrections weigh 3, shop categories 1."""
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT name, category, category_source FROM products"
                            " WHERE category_source IN ('user','shop') AND category<>'other'").fetchall()
    except Exception:
        return []
    return [(r[0], r[1], 3.0 if r[2] == "user" else 1.0) for r in rows]


class Classifier:
    """Load the dictionaries once per parse run."""

    def __init__(self, conn=None):
        self.kw = _keywords(conn)
        self.map = _shop_map(conn)
        self.similar = Similar(_examples(conn))

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

    def _match(self, words: list[str], describing: set[int] | None = None, only_user: bool = False) -> str | None:
        """describing: positions of words that only describe the product (genitive plural "česnakų") –
        a keyword found there loses to one found in a naming word."""
        describing = describing or set()
        best = None  # (user keyword, naming word, position of the last matched word, length, category)
        for k, (cat, user) in self.kw.items():
            if only_user and not user:
                continue
            kws = k.split()
            n = len(kws)
            for j in range(len(words) - n, -1, -1):
                if all(words[j + t].startswith(kws[t]) if t == n - 1 else words[j + t] == kws[t] for t in range(n)):
                    cand = (user, (j + n - 1) not in describing, j + n - 1, len(k), cat)
                    if best is None or cand[:4] > best[:4]:
                        best = cand
                    break
        return best[4] if best else None

    def keyword(self, name: str) -> str | None:
        """Printed name (or a plain key) → category from the dictionary, or None."""
        head = re.split(r"\s(?:su|ar|be|įdaryt\w*|pagardint\w*)\s|\s\d", name, maxsplit=1)[0]
        return self._match(*self._words(head)) or self._match(*self._words(name))

    def user_keyword(self, name: str) -> str | None:
        """Only the keywords the user taught ("Įsiminti raktažodį")."""
        return self._match(*self._words(name), only_user=True)

    @staticmethod
    def _words(text: str) -> tuple[list[str], set[int]]:
        """Folded words + positions of genitive-plural words (printed ending -ų/-ių): those describe."""
        words, desc = [], set()
        for raw in re.split(r"[^\w%+]+", text or ""):
            f = fold(raw)
            if not f:
                continue
            for part in f.split():
                if raw.lower().endswith("ų") and len(raw) > 3:
                    desc.add(len(words))
                words.append(part)
        return words, desc

    def classify(self, chain: str, name: str, ext_category: str | None) -> tuple[str, str]:
        """→ (category, source) where source is shop|keyword|similar|shop_weak|none.
        Order: the shop's own category → a keyword the user taught → what similar products (shop- or
        user-categorised) are → the built-in keyword list → the shop's vague category → other."""
        sm = self.shop(chain, ext_category)
        if sm and sm[1] == "strong":
            return sm[0], "shop"
        k = self.user_keyword(name)
        if k:
            return k, "keyword"
        g = self.similar.guess(name)
        if g:
            return g[0], "similar"
        k = self.keyword(name)
        if k:
            return k, "keyword"
        if sm:
            return sm[0], "shop_weak"
        return "other", "none"
