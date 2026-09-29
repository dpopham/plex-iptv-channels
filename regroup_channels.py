#!/usr/bin/env python3
"""
regroup_channels.py

Reads a Plex Live TV channels.m3u (all group-title="Plex") and an optional
epg.xml, then rewrites the M3U with more useful group-title values:

  News, Sports, Spanish, Movies, Crime, Music, Kids, Reality, Comedy,
  Sci-Fi / Fantasy, Drama, Lifestyle, Food, Documentary, Shopping,
  Anime, Western, Gaming, Religion, Weather, Classic TV, Wrestling, Other

plus language groups detected from the EPG text (see below):

  Spanish, Portuguese, French, German, Italian, Korean, Japanese, Chinese,
  Russian, Arabic, Hindi, Thai, Hebrew, Greek, International

Classification
--------------
1. Non-English EPG language (if an EPG is given). Programme titles,
   sub-titles and descriptions are scanned for non-English content, using
   the XMLTV lang="xx" attribute when present, otherwise script detection
   (Hangul, Cyrillic, ...) and stop-word matching (Spanish, Portuguese,
   French, German, Italian). If enough of a channel's programmes are in
   one non-English language, the channel gets that language as its group.
   (--lang-priority fallback makes this apply only after the name rules.)
2. Keyword rules on the channel name (the RULES table below).
3. Soft genre hints from the EPG <category> tags.

Removing categories
-------------------
Use --remove-category (repeatable, or comma-separated) and/or
--remove-file to drop every channel whose final group matches. Those
channels are removed from the output M3U, and their <channel> and
<programme> entries are removed from a filtered copy of the EPG. The
output M3U's header (url-tvg / x-tvg-url) is updated to point at that
filtered EPG file name.

Usage
-----
    python regroup_channels.py channels.m3u epg.xml -o channels_grouped.m3u
    python regroup_channels.py channels.m3u -o channels_grouped.m3u

    # drop Shopping and Religion from both files
    python regroup_channels.py channels.m3u epg.xml \\
        -r Shopping -r Religion \\
        -o channels_grouped.m3u --epg-output epg_filtered.xml

    # same, with the list in a file (one per line, '#' comments allowed)
    python regroup_channels.py channels.m3u epg.xml --remove-file remove.txt
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import quoteattr

# ---------------------------------------------------------------------------
# Category rules — first match wins. Patterns are case-insensitive.
# ---------------------------------------------------------------------------

RULES: list[tuple[str, list[str]]] = [
    (
        "Spanish",
        [
            r"\bespañol\b", r"\bespanol\b", r"\blatin[oa]x?\b", r"\bnuevo latino\b",
            r"\bsiempre latino\b", r"\bnovelas?\b", r"\bnovelisima\b",
            r"\btelemundo\b", r"\bunivision\b", r"\bazteca\b", r"\bwapa\b",
            r"\bteleonce\b", r"\bcanela\.?tv\b", r"\bestrella\b", r"\bentravision\b",
            r"\bcine en español\b", r"\bcine romántico\b", r"\bcine de horror\b",
            r"\bcine estrella\b", r"\btodo (cine|crimen|drama|novelas)\b",
            r"\badn noticias\b", r"\bc4 en alerta\b", r"\bcaso cerrado\b",
            r"\bcorazón\b", r"\bcheaters en español\b", r"\bcops en español\b",
            r"\bamc en español\b", r"\bwalking dead espanol\b",
            r"\bwestern bound español\b", r"\bbein sports xtra en español\b",
            r"\bbillboard español\b", r"\bautopista al cielo\b", r"\bbuen viaje\b",
            r"\bzonas? investigación\b", r"\bvive kanal\b", r"\bwedotv\b",
            r"\béxitos del momento\b", r"\bú[nñ] tv\b", r"\btarima tv\b", r"\bclic\b",
            r"\bel señor de los cielos\b", r"\bel conflicto\b", r"\bel rey rebel\b",
            r"\bemoción\b", r"\bfreetv\b", r"\bgata salvaje\b", r"\bgrjngo\b",
            r"\bideas en 5 minutos\b", r"\bitv deportes\b", r"\bla fiebre del jade\b",
            r"\blatv\b", r"\blos asesinatos\b", r"\bmera mera\b", r"\bmi casa\b",
            r"\bmisterios sin resolver\b", r"\bnaturaleza\b", r"\bnosey escándalos\b",
            r"\bpelimex\b", r"\brcn\b", r"\brevry latinx\b", r"\btrace (brazuca|latina)\b",
            r"\bspark tv luz\b", r"\bdelito\b",
        ],
    ),
    (
        "News",
        [
            r"\bnews\b", r"\bcnn\b", r"\bcbs news\b", r"\bbc news\b", r"\bcbc news\b",
            r"\bbloomberg\b", r"\breuters\b", r"\busa today\b", r"\byahoo finance\b",
            r"\bcheddar\b", r"\bwftv\b", r"\bvery (orlando|south florida|tampa)\b",
            r"\bheadline\b", r"\beuronews\b", r"\bfrance 24\b", r"\bnewsmax\b",
            r"\blivenow\b", r"\btoday all day\b", r"\btmz\b", r"\b60 minutes\b",
            r"\b48 hours\b", r"\blocal now\b",
        ],
    ),
    (
        "Weather",
        [r"\bweather\b", r"\baccuweather\b", r"\bweatherspy\b"],
    ),
    (
        "Sports",
        [
            r"\bsports?\b", r"\bnba\b", r"\bnfl\b", r"\bmlb\b", r"\bnhl\b", r"\bufc\b",
            r"\bwwe\b", r"\bnxt\b", r"\btennis\b", r"\bgolf\b", r"\bpoker\b",
            r"\bbilliard\b", r"\bbowling\b", r"\bcricket\b", r"\bsurf\b",
            r"\bbassmaster\b", r"\bfishing\b", r"\bfish\b", r"\boutdoor\b",
            r"\bwildearth\b", r"\bwired2fish\b", r"\bwaypoint\b", r"\bcornhole\b",
            r"\bgladiators\b", r"\bdazn\b", r"\bbein\b", r"\bwillow\b",
            r"\bdp world tour\b", r"\bworld poker\b", r"\bpokergo\b", r"\bringside\b",
            r"\bunbeaten\b", r"\byahoo!?\s*sports\b", r"\bcowboy\+?\s*sports\b",
            r"\bwomen'?s sports\b", r"\bjim rome\b", r"\btorque\b",
            r"\bxtreme outdoor\b", r"\bax men\b", r"\bwicked tuna\b",
            r"\bf1 channel\b", r"\bfifa\b", r"\bfuel tv\b", r"\bfight network\b",
            r"\bglory kickboxing\b", r"\bgame & fish\b", r"\bgolfpass\b",
            r"\bhbo boxing\b", r"\bhard knocks\b", r"\bmonster jam\b",
            r"\bmotogp\b", r"\bmsg sportszone\b", r"\bnesn\b", r"\bnhra\b",
            r"\bone championship\b", r"\bpac-?12\b", r"\bpfl mma\b", r"\bpga tour\b",
            r"\bpickle(ball)?tv\b", r"\bracer\b", r"\bracing america\b",
            r"\bspeedvision\b", r"\bstadium\b", r"\bstrongman\b", r"\bswerve combat\b",
            r"\bsurfer tv\b", r"\btop gear\b", r"\bfifth gear\b", r"\bdiscovery turbo\b",
            r"\bice pilots\b", r"\bice road truckers\b", r"\bhighway thru hell\b",
            r"\bpowernation\b", r"\bpursuitup\b", r"\boutside\b", r"\bgo wild\b",
            r"\breal wild\b", r"\bslopes\b", r"\bswac tv\b",
        ],
    ),
    (
        "Wrestling",
        [r"\bwwe\b", r"\bnxt\b", r"\bwrestling\b", r"\blucha\b"],
    ),
    (
        "Crime",
        [
            r"\bcrime\b", r"\btrue crime\b", r"\bcourt tv\b", r"\bdateline\b",
            r"\bfirst 48\b", r"\bcold case\b", r"\bunsolved\b", r"\bdetectives?\b",
            r"\binvestigat\b", r"\bmurder\b", r"\bkiller\b", r"\bforensic\b",
            r"\bfbi\b", r"\bcops\b", r"\blive pd\b", r"\balaska state troopers\b",
            r"\bwomen behind bars\b", r"\bbloodline\b", r"\bnancy grace\b",
            r"\bconfess\b", r"\bchaos on cam\b", r"\btrublu\b", r"\bwanted:? dead\b",
            r"\bamerican crimes\b", r"\bcrimes cults\b", r"\bcrime thrill\b",
            r"\bcrime scene\b", r"\bcrime beat\b", r"\bcrime & justice\b",
            r"\bone crime\b", r"\btodo crimen\b", r"\bunspeakable\b",
            r"\buntold stories of the er\b", r"\bon patrol\b", r"\bjail\b",
            r"\bdog the bounty hunter\b", r"\bdr\.?\s*g:? medical\b", r"\breelz\b",
            r"\bworld'?s most evil\b", r"\blawless\b", r"\bsheriffs?\b",
            r"\boperation repo\b", r"\breal emergency\b", r"\bi shouldn'?t be alive\b",
            r"\bmayday\b", r"\bsurvive or die\b", r"\bliving with evil\b",
            r"\bprime suspect\b", r"\bsilent witness\b", r"\bmidsomer\b",
            r"\bmurdoch mysteries\b", r"\bion mystery\b",
        ],
    ),
    (
        "Movies",
        [
            r"\bmovies?\b", r"\bcinema\b", r"\bcine\b", r"\bhorror\b", r"\bfilm\b",
            r"\btrailers from hell\b", r"\b24 hour free movies\b",
            r"\baction hollywood\b", r"\bat the movies\b", r"\bclassic cinema\b",
            r"\bcinelife\b", r"\bwatch it scream\b", r"\bthe asylum\b",
            r"\bwu tang collection\b", r"\bdark matter tv\b", r"\bdread tv\b",
            r"\btribeca\b", r"\bvr\+\b", r"\b50 cent action\b", r"\bamc thrillers\b",
            r"\bfilmrise\b", r"\bfrightflix\b", r"\bgrit\b", r"\bhi-yah\b",
            r"\bhong kong fight\b", r"\bifc films\b", r"\bmidnight pulp\b",
            r"\bmoviesphere\b", r"\bmovieitaly\b", r"\bmgm presents\b",
            r"\boutlaw\b", r"\bpam grier\b", r"\bscream\b", r"\bshudder\b",
            r"\bscreambox\b", r"\bstories by amc\b", r"\bcamp spoopy\b",
            r"\bhorror stories\b", r"\bhorror by alter\b", r"\bscares by\b",
        ],
    ),
    (
        "Music",
        [
            r"\bmusic\b", r"\bxite\b", r"\bhip-?hop\b", r"\brap\b", r"\breggae\b",
            r"\bgospel\b", r"\bcountry\b", r"\brock\b", r"\bmetal\b", r"\br&b\b",
            r"\bk-?pop\b", r"\bbillboard\b", r"\bhits\b", r"\bgroove\b",
            r"\bflashback\b", r"\bthrowback\b", r"\bchristian hits\b",
            r"\bjust chill\b", r"\béxitos\b", r"\balternative\b",
            r"\bclassic rock\b", r"\bcircle country\b", r"\beasy listening\b",
            r"\bgrowing up hip hop\b", r"\bnon-stop '?90s\b", r"\bnothin' but 90s\b",
            r"\bremember the.80s\b", r"\bsmooth jazz\b", r"\bstingray\b",
            r"\bqello concert\b", r"\bqwest tv\b", r"\btrace urban\b",
            r"\bthe black effect\b",
        ],
    ),
    (
        "Kids",
        [
            r"\bkids?\b", r"\bchildren\b", r"\bbaby\b", r"\bshark\b", r"\bwiggles\b",
            r"\bteletubbies\b", r"\btoon\b", r"\banimation\b", r"\btransformers\b",
            r"\bbeyblade\b", r"\byu-?gi-?oh\b", r"\bpocket\.watch\b", r"\bbrat tv\b",
            r"\bbaby einstein\b", r"\b123go\b", r"\bpet collective\b",
            r"\bcesar'?s pack\b", r"\bkidsflix\b", r"\bmy little pony\b",
            r"\bpink panther\b", r"\bpitufo\b", r"\bpower rangers\b",
            r"\bryan and friends\b", r"\bsonic\b", r"\bstrawberry shortcake\b",
            r"\btg junior\b", r"\beddie'?s wonderland\b", r"\bdungeons & dragons\b",
            r"\bhasbro legends\b", r"\bmrbeast\b", r"\bryan trahan\b",
        ],
    ),
    (
        "Anime",
        [r"\banime\b", r"\bhidive\b", r"\byu-?gi-?oh\b", r"\bbeyblade\b", r"\bretrocrush\b"],
    ),
    (
        "Comedy",
        [
            r"\bcomedy\b", r"\bfunny\b", r"\bsitcom\b", r"\bcarol burnett\b",
            r"\bgraham norton\b", r"\bkids in the hall\b", r"\balways funny\b",
            r"\bbbc comedy\b", r"\bcomedy dynamics\b", r"\btrailer park boys\b",
            r"\bwipeout\b", r"\bamerica'?s funniest\b", r"\bbet x tyler perry comedy\b",
            r"\bfailarmy\b", r"\bfluffy\b", r"\bjust for laughs\b", r"\blaff\b",
            r"\blol!\b", r"\bmr\.?\s*bean\b", r"\bmst3k\b", r"\bnational lampoon\b",
            r"\bportlandia\b", r"\bsnl vault\b", r"\bslightly off\b",
            r"\bjohnny carson\b", r"\bdick van dyke\b", r"\bhit sitcoms\b",
            r"\bcorner gas\b", r"\bare we there yet\b", r"\bgreen acres\b",
            r"\bkim'?s convenience\b",
        ],
    ),
    (
        "Sci-Fi / Fantasy",
        [
            r"\bsci-?fi\b", r"\bscience fiction\b", r"\bfantasy\b", r"\bouter limits\b",
            r"\bdoctor who\b", r"\bandromeda\b", r"\bcontinuum\b", r"\bz nation\b",
            r"\balien nation\b", r"\bdust\b", r"\bcosmic\b", r"\bunidentified\b",
            r"\bunxplained\b", r"\bbeyond paranormal\b", r"\bbeyond belief\b",
            r"\bancient aliens\b", r"\bthe outpost\b", r"\blibrarians\b",
            r"\bwalking dead\b", r"\bfarscape\b", r"\bstargate\b", r"\bspace & beyond\b",
            r"\bghost\b", r"\bparanormal\b", r"\bmonsters are real\b",
            r"\bmysterious worlds\b", r"\bmysteria\b", r"\bmythbusters\b",
            r"\brobot wars\b", r"\bstartalk\b", r"\binwonder\b", r"\boutersphere\b",
        ],
    ),
    (
        "Western",
        [
            r"\bwestern\b", r"\bwild west\b", r"\brifleman\b", r"\bbonanza\b",
            r"\bwanted:? dead or alive\b", r"\bwestern bound\b", r"\bdeath valley\b",
            r"\blone star\b", r"\bgrjngo\b", r"\bmgm presents: westerns\b",
        ],
    ),
    (
        "Reality",
        [
            r"\breality\b", r"\breal housewives\b", r"\bbachelor\b", r"\blove island\b",
            r"\bdance moms\b", r"\bbiggest loser\b", r"\bcheaters\b", r"\bbondi rescue\b",
            r"\ball reality\b", r"\ball weddings\b", r"\bosbournes\b", r"\bwendy williams\b",
            r"\btony robbins\b", r"\bcome dine with me\b", r"\bdeal or no deal\b",
            r"\bprice is right\b", r"\bgame shows?\b", r"\bbuzzr\b",
            r"\bcelebrity name game\b", r"\bcaught in providence\b",
            r"\bdon'?t tell the bride\b", r"\bduck dynasty\b", r"\be! keeping up\b",
            r"\bfamily feud\b", r"\bfamily unscripted\b", r"\bfear factor\b",
            r"\bfour in a bed\b", r"\bhot bench\b", r"\bhot ones\b", r"\bjudge\b",
            r"\blove (&|and) marriage\b", r"\blove after lockup\b", r"\blove thy neighbor\b",
            r"\bmatched married\b", r"\bmillion dollar listing\b", r"\bnosey\b",
            r"\bpaternity court\b", r"\bpenn & teller\b", r"\bproperty brothers\b",
            r"\bsay yes to the dress\b", r"\bso\.\.\. real\b", r"\bstorage wars\b",
            r"\bsupermarket sweep\b", r"\bimpossible - quiz\b", r"\bgrowthday\b",
            r"\bperform by lifetime\b",
        ],
    ),
    (
        "Food",
        [
            r"\bfood\b", r"\bcook\b", r"\bchef\b", r"\bbaking\b", r"\bemeril\b",
            r"\bjamie oliver\b", r"\btastemade\b", r"\bbizarre foods\b", r"\bbbc food\b",
            r"\bgreat british baking\b", r"\bgreat british menu\b", r"\bhell'?s kitchen\b",
            r"\bgustotv\b", r"\bnew kfood\b", r"\bno reservations\b", r"\bso yummy\b",
            r"\bconcursos de cocina\b",
        ],
    ),
    (
        "Lifestyle",
        [
            r"\blifestyle\b", r"\bhome\b", r"\bgarden\b", r"\bdesign\b",
            r"\bmartha stewart\b", r"\bbob ross\b", r"\brepair shop\b",
            r"\bthis old house\b", r"\btiny house\b", r"\bcraftsy\b",
            r"\b5-minute crafts\b", r"\bfamily handyman\b", r"\bchip & jo\b",
            r"\bwelcome home\b", r"\bthe spa\b", r"\bzenlife\b", r"\bbbc home\b",
            r"\bbbc travel\b", r"\btravel escapes\b", r"\bantiques\b", r"\bdeal zone\b",
            r"\bfashiontv\b", r"\bgotraveler\b", r"\bhow to\b", r"\bjourny\b",
            r"\bmade it myself\b", r"\bnomad travel\b", r"\bpbs (genealogy|travel)\b",
            r"\bplaces & spaces\b", r"\bsweet escapes\b", r"\bdove\b",
            r"\blove nature\b", r"\blove pets\b", r"\bpaws & claws\b",
            r"\bdog whisperer\b", r"\bmagellantv\b",
        ],
    ),
    (
        "Documentary",
        [
            r"\bdocu\b", r"\bhistory\b", r"\btrue history\b", r"\bbbc earth\b",
            r"\bcuriosity\b", r"\bvice\b", r"\bwonder\b", r"\bcombat war\b",
            r"\bunique lives\b", r"\bprof g\b", r"\bthe doctors\b", r"\bearthxtra\b",
            r"\bget\.factual\b", r"\bjade fever\b", r"\bmedical incredible\b",
            r"\bmythical\b", r"\bpbs nature\b", r"\bpopular science\b",
            r"\bdocumentary\+\b", r"\bdr\.?\s*phil\b",
        ],
    ),
    (
        "Drama",
        [
            r"\bdrama\b", r"\bsoap\b", r"\bbold and the beautiful\b",
            r"\btyler perry drama\b", r"\bteen wolf\b", r"\bweeds\b",
            r"\bnurse jackie\b", r"\bthe conners\b", r"\bthat girl\b",
            r"\b21 jump street\b", r"\bbaywatch\b", r"\banger management\b",
            r"\bacorn tv\b", r"\bbritbox\b", r"\btouch of frost\b", r"\bdoctor blake\b",
            r"\bsherlock\b", r"\bcw forever\b", r"\bcw gold\b", r"\basian drama\b",
            r"\btvb pearl\b", r"\ballblk\b", r"\b365blk\b", r"\bafroland\b",
            r"\bblackpix\b", r"\bthe grio\b", r"\btvone\b", r"\basiancrush\b",
            r"\bdegrassi\b", r"\bdesignated survivor\b", r"\bebony tv\b",
            r"\bfilmrise black\b", r"\bfilmrise british\b", r"\bfilmrise series\b",
            r"\bheartland\b", r"\bhersphere\b", r"\bin the heat of the night\b",
            r"\blionsgate\b", r"\bmcleod\b", r"\bmhz mysteries\b", r"\bmi-5\b",
            r"\bnash bridges\b", r"\bnashville\b", r"\bnikita\b", r"\bnip/?tuck\b",
            r"\bnolly africa\b", r"\bpbs retro\b", r"\brakuten viki\b",
            r"\brookie blue\b", r"\bscandal\b", r"\bshades of black\b",
            r"\bshemaroo\b", r"\bhunter\b", r"\blegacy\b", r"\bmore u\b",
            r"\bprimetime soaps\b", r"\bhighway to heaven\b",
        ],
    ),
    (
        "Classic TV",
        [
            r"\bclassic\b", r"\b80'?s sitcom\b", r"\bed sullivan\b", r"\balf\b",
            r"\baddams family\b", r"\by2k\b", r"\bcw presents\b", r"\bbravo vault\b",
            r"\bion\b", r"\bshout!\b",
        ],
    ),
    (
        "Shopping",
        [
            r"\bshop\b", r"\bshopping\b", r"\bauction\b", r"\bdeal zone\b",
            r"\bclassic car auctions\b",
        ],
    ),
    (
        "Gaming",
        [
            r"\bgaming\b", r"\bgame-?on\b", r"\besports?\b", r"\bgametvgo\b",
            r"\bestrella games\b", r"\bboot\b",
        ],
    ),
    (
        "Religion",
        [
            r"\bchristian\b", r"\bgospel\b", r"\bfaith\b", r"\bchurch\b",
            r"\breligion\b", r"\bspark tv light\b",
        ],
    ),
]

_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (cat, [re.compile(p, re.IGNORECASE) for p in pats]) for cat, pats in RULES
]


def classify_name(title: str) -> str:
    for cat, patterns in _COMPILED:
        for pat in patterns:
            if pat.search(title):
                return cat
    return "Other"


# ---------------------------------------------------------------------------
# Non-English language detection (from EPG text)
# ---------------------------------------------------------------------------

# Group name used for each detected language code. "Spanish" is the same
# group the name-based rules already produce. Any other detected language
# that is not listed here goes to INTERNATIONAL_CATEGORY.
LANGUAGE_CATEGORIES: dict[str, str] = {
    "es": "Spanish", "pt": "Portuguese", "fr": "French", "de": "German",
    "it": "Italian", "ko": "Korean", "ja": "Japanese", "zh": "Chinese",
    "ru": "Russian", "ar": "Arabic", "hi": "Hindi", "th": "Thai",
    "he": "Hebrew", "el": "Greek",
}
INTERNATIONAL_CATEGORY = "International"

_LANG_ALIASES = {
    "spa": "es", "spanish": "es", "español": "es", "espanol": "es",
    "fra": "fr", "fre": "fr", "french": "fr",
    "por": "pt", "portuguese": "pt",
    "deu": "de", "ger": "de", "german": "de",
    "ita": "it", "italian": "it",
    "kor": "ko", "korean": "ko", "jpn": "ja", "japanese": "ja",
    "zho": "zh", "chi": "zh", "chinese": "zh",
    "rus": "ru", "russian": "ru", "ara": "ar", "arabic": "ar",
    "hin": "hi", "hindi": "hi", "tha": "th", "thai": "th",
    "heb": "he", "hebrew": "he", "ell": "el", "gre": "el", "greek": "el",
    "eng": "en", "english": "en",
}
_UNDETERMINED_LANGS = {"und", "zxx", "mul", "mis"}


def normalize_lang(code: str | None) -> str | None:
    """'es-MX' / 'spa' / 'Spanish' -> 'es'. Returns None if unknown/empty."""
    if not code:
        return None
    c = code.strip().lower().replace("_", "-").split("-")[0]
    if not c or c in _UNDETERMINED_LANGS:
        return None
    return _LANG_ALIASES.get(c, c)


def language_category(code: str) -> str:
    return LANGUAGE_CATEGORIES.get(code, INTERNATIONAL_CATEGORY)


# Stop-word lists for the Latin-script languages. Words that are also common
# English words (no, son, sin, come, die, do, com, plus, ...) are left out on
# purpose to keep false positives down.
_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the and of to is with for his her their this that from are be by at "
        "after when who what into it its were has have not but they he she "
        "you your our new one two out up about over more while where which "
        "there been than then back".split()
    ),
    "es": frozenset(
        "el los las una unos unas del por para con que pero como más muy su "
        "sus es está están se lo al este esta esto hay sobre entre cuando "
        "donde también sino desde hasta cada todos todas ser tiene tienen "
        "mientras después antes nuevo nueva vida amor familia historia "
        "temporada capítulo programa noticias película hoy día año años "
        "señor".split()
    ),
    "pt": frozenset(
        "os as um uma uns umas não você vocês para por que mas mais muito "
        "seu sua seus suas dos das da na nas nos em são está estão também "
        "ele ela eles elas quando onde sobre entre temporada episódio ainda "
        "já nós até depois antes novo nova vida amor família história "
        "programa notícias filme hoje dia ano anos".split()
    ),
    "fr": frozenset(
        "le les une des du et est sont dans pour avec sur pas qui que mais "
        "très ce cette ces ses au aux il nous vous ils être où saison "
        "épisode émission ne se sa leur leurs aussi comme fait après avant "
        "nouveau nouvelle vie amour famille histoire".split()
    ),
    "de": frozenset(
        "der das und ist nicht ein eine einen einem mit von für auf den dem "
        "des sich auch wie wird sind aber nach bei über staffel folge "
        "sendung zum zur ihr ihre sein seine noch nur oder wenn dass als "
        "vom im am aus".split()
    ),
    "it": frozenset(
        "il lo gli le un uno una di del della dei delle che con per non "
        "sono più anche questo questa nel nella stagione episodio puntata "
        "trasmissione tra fra sul sulla suo sua loro ma se già oggi vita "
        "amore famiglia storia".split()
    ),
}

_TOKEN_RE = re.compile(r"[^\W\d_]{2,}")
_MAX_TEXT_CHARS = 800

# (language code, [(first, last) code point ranges])
_SCRIPT_RANGES: list[tuple[str, list[tuple[int, int]]]] = [
    ("ko", [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)]),  # Hangul
    ("ja", [(0x3040, 0x30FF)]),                                       # Kana
    ("zh", [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)]),                     # Han
    ("ru", [(0x0400, 0x04FF)]),                                       # Cyrillic
    ("ar", [(0x0600, 0x06FF), (0x0750, 0x077F)]),                     # Arabic
    ("hi", [(0x0900, 0x097F)]),                                       # Devanagari
    ("th", [(0x0E00, 0x0E7F)]),                                       # Thai
    ("he", [(0x0590, 0x05FF)]),                                       # Hebrew
    ("el", [(0x0370, 0x03FF)]),                                       # Greek
]


def _detect_script(text: str) -> str | None:
    letters = 0
    counts: Counter = Counter()
    for ch in text:
        if not ch.isalpha():
            continue
        letters += 1
        o = ord(ch)
        if o < 0x0370:  # Latin and friends: cheap early exit
            continue
        for lang, ranges in _SCRIPT_RANGES:
            if any(lo <= o <= hi for lo, hi in ranges):
                counts[lang] += 1
                break
    if not letters or not counts:
        return None
    if counts["ja"]:  # Japanese mixes kana with Han characters
        counts["ja"] += counts.pop("zh", 0)
    lang, n = counts.most_common(1)[0]
    return lang if n / letters >= 0.3 else None


def detect_text_language(text: str) -> str | None:
    """Best-effort language of a snippet: 'en', a non-English code, or None
    when there is not enough text to tell."""
    text = text[:_MAX_TEXT_CHARS]
    script = _detect_script(text)
    if script:
        return script

    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < 3:
        return None

    scores = {
        lang: sum(1 for t in tokens if t in words)
        for lang, words in _STOPWORDS.items()
    }
    # Extra Spanish / Portuguese signals
    scores["es"] += 2 * (text.count("¿") + text.count("¡"))
    scores["es"] += sum(1 for t in tokens if "ñ" in t)
    scores["pt"] += sum(1 for t in tokens if t.endswith(("ção", "ções", "ões")))

    english = scores.pop("en")
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 >= 2 and s1 > english and s1 > s2:
        return best
    if english >= 2 and english >= s1:
        return "en"
    return None


def _programme_language(elem: ET.Element) -> str | None:
    """Language vote for one <programme>. An explicit non-English lang="xx"
    attribute wins; otherwise the text itself is analysed. (lang="en" is not
    trusted on its own, since some feeds stamp it on everything.)"""
    texts: list[str] = []
    for tag in ("title", "sub-title", "desc"):
        for el in elem.findall(tag):
            code = normalize_lang(el.get("lang"))
            if code and code != "en":
                return code
            if el.text and el.text.strip():
                texts.append(el.text.strip())
    return detect_text_language(" ".join(texts)) if texts else None


def language_category_for_channel(
    counts: Counter | None, min_programmes: int, threshold: float
) -> str | None:
    """Group name if enough of the channel's programmes are non-English in
    one language (or language family bucket), else None."""
    if not counts:
        return None
    by_category: Counter = Counter()
    for code, n in counts.items():
        if code != "en":
            by_category[language_category(code)] += n
    if not by_category:
        return None
    category, n = by_category.most_common(1)[0]
    decided = sum(counts.values())
    if n < min_programmes or n / decided < threshold:
        return None
    return category


# ---------------------------------------------------------------------------
# EPG scan
# ---------------------------------------------------------------------------

def scan_epg(
    epg_path: Path | None, detect_language: bool = True
) -> tuple[dict[str, Counter], dict[str, Counter]]:
    """One streaming pass over the EPG.

    Returns (genres, langs):
      genres: channel-id -> Counter of soft genre signals
      langs:  channel-id -> Counter of language code -> programme count
              ('en' counts English programmes, so ratios can be computed)
    """
    if not epg_path or not epg_path.is_file():
        return {}, {}

    genres: dict[str, Counter] = defaultdict(Counter)
    langs: dict[str, Counter] = defaultdict(Counter)
    try:
        for _event, elem in ET.iterparse(epg_path, events=("end",)):
            if elem.tag != "programme":
                continue
            ch = elem.get("channel")
            if not ch:
                elem.clear()
                continue
            for g in elem.findall("category"):
                if g.text:
                    genres[ch][g.text.strip()] += 1
            title_el = elem.find("title")
            if title_el is not None and title_el.text:
                t = title_el.text.lower()
                if any(w in t for w in ("news", "headline", "breaking")):
                    genres[ch]["News"] += 1
                if any(w in t for w in ("sport", "match", "game", "nfl", "nba")):
                    genres[ch]["Sports"] += 1
            if detect_language:
                lang = _programme_language(elem)
                if lang:
                    langs[ch][lang] += 1
            elem.clear()
    except ET.ParseError as exc:
        print(f"  [warn] Could not fully parse EPG: {exc}", file=sys.stderr)
    return genres, langs


def load_epg_genres(epg_path: Path | None) -> dict[str, Counter]:
    """Optional map channel-id -> Counter of soft genre signals from EPG."""
    return scan_epg(epg_path, detect_language=False)[0]


_EPG_GENRE_MAP = {
    "news": "News", "sports": "Sports", "sport": "Sports",
    "movie": "Movies", "movies": "Movies", "film": "Movies",
    "music": "Music", "kids": "Kids", "children": "Kids",
    "comedy": "Comedy", "crime": "Crime", "documentary": "Documentary",
    "drama": "Drama", "reality": "Reality", "food": "Food",
    "travel": "Lifestyle", "lifestyle": "Lifestyle",
    "sci-fi": "Sci-Fi / Fantasy", "science fiction": "Sci-Fi / Fantasy",
    "fantasy": "Sci-Fi / Fantasy", "western": "Western", "anime": "Anime",
    "shopping": "Shopping", "religion": "Religion", "weather": "Weather",
}


def genre_from_epg(channel_id: str, epg_genres: dict[str, Counter]) -> str:
    counts = epg_genres.get(channel_id)
    if not counts:
        return "Other"
    best_cat, best_n = None, 0
    for genre, n in counts.most_common():
        mapped = _EPG_GENRE_MAP.get(genre.lower())
        if mapped and n > best_n:
            best_cat, best_n = mapped, n
    return best_cat or "Other"


def classify_with_epg(title: str, channel_id: str, epg_genres: dict[str, Counter]) -> str:
    cat = classify_name(title)
    if cat != "Other":
        return cat
    return genre_from_epg(channel_id, epg_genres)


def classify_channel(
    title: str,
    channel_id: str,
    epg_genres: dict[str, Counter],
    epg_langs: dict[str, Counter],
    lang_priority: str = "override",
    min_lang_programmes: int = 3,
    lang_threshold: float = 0.5,
) -> tuple[str, str]:
    """Return (group, source) where source is one of
    'epg-language', 'name', 'epg-genre', 'none'."""
    name_cat = classify_name(title)
    lang_cat = language_category_for_channel(
        epg_langs.get(channel_id), min_lang_programmes, lang_threshold
    )

    if lang_priority == "override":
        if lang_cat:
            return lang_cat, "epg-language"
        if name_cat != "Other":
            return name_cat, "name"
    else:  # fallback: name rules first, language only if nothing matched
        if name_cat != "Other":
            return name_cat, "name"
        if lang_cat:
            return lang_cat, "epg-language"

    genre = genre_from_epg(channel_id, epg_genres)
    return (genre, "epg-genre") if genre != "Other" else ("Other", "none")


def parse_m3u(path: Path) -> tuple[str, list[dict]]:
    header = "#EXTM3U"
    entries: list[dict] = []
    current: dict | None = None

    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n\r")
            if line.startswith("#EXTM3U"):
                header = line
                continue
            if line.startswith("#EXTINF:"):
                m = re.match(r"(#EXTINF:[^,]*)(,(.*))?$", line)
                attrs = m.group(1) if m else line
                title = (m.group(3) or "").strip() if m else ""
                current = {"attrs": attrs, "title": title, "url": ""}
                continue
            if current is not None and line and not line.startswith("#"):
                current["url"] = line
                entries.append(current)
                current = None
    return header, entries


def rewrite_extinf(attrs: str, title: str, new_group: str) -> str:
    if re.search(r'group-title="[^"]*"', attrs):
        attrs = re.sub(r'group-title="[^"]*"', f'group-title="{new_group}"', attrs)
    else:
        attrs = attrs.rstrip() + f' group-title="{new_group}"'
    return f"{attrs},{title}"


def _norm_cat(name: str) -> str:
    return " ".join(name.split()).casefold()


def known_categories() -> list[str]:
    cats = [c for c, _ in RULES]
    cats += list(LANGUAGE_CATEGORIES.values())
    cats += [INTERNATIONAL_CATEGORY, "Other"]
    return list(dict.fromkeys(cats))  # de-dupe, keep order


def collect_remove_categories(
    cli_values: list[str] | None, file_path: Path | None
) -> set[str]:
    """Categories to remove, normalised (case/whitespace-insensitive)."""
    raw: list[str] = []
    for v in cli_values or []:
        raw.extend(v.split(","))
    if file_path:
        with file_path.open(encoding="utf-8") as f:
            for line in f:
                raw.extend(line.split("#", 1)[0].split(","))
    return {_norm_cat(r) for r in raw if r.strip()}


def filter_epg(src: Path, dst: Path, remove_ids: set[str]) -> tuple[int, int]:
    """Stream src -> dst, dropping <channel> and <programme> elements that
    belong to remove_ids. Everything else is copied through unchanged.
    Returns (channels_removed, programmes_removed)."""
    channels_removed = programmes_removed = 0
    depth = 0
    root: ET.Element | None = None
    root_tag = "tv"
    closed = False

    with dst.open("w", encoding="utf-8") as out:
        try:
            for event, elem in ET.iterparse(src, events=("start", "end")):
                if event == "start":
                    depth += 1
                    if depth == 1:
                        root, root_tag = elem, elem.tag
                        attrs = "".join(
                            f" {k}={quoteattr(v)}" for k, v in elem.attrib.items()
                        )
                        out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                        out.write(f"<{root_tag}{attrs}>\n")
                    continue

                # event == "end"
                if depth == 2:  # direct child of the root element
                    if elem.tag == "channel":
                        drop = elem.get("id") in remove_ids
                        channels_removed += drop
                    elif elem.tag == "programme":
                        drop = elem.get("channel") in remove_ids
                        programmes_removed += drop
                    else:
                        drop = False
                    if not drop:
                        elem.tail = "\n"
                        out.write(ET.tostring(elem, encoding="unicode"))
                    if root is not None:
                        root.clear()  # free memory as we go
                depth -= 1
                if depth == 0:
                    out.write(f"</{root_tag}>\n")
                    closed = True
        except ET.ParseError as exc:
            print(f"  [warn] Could not fully parse EPG: {exc}", file=sys.stderr)
        if root is not None and not closed:
            out.write(f"</{root_tag}>\n")  # keep the output well-formed
    return channels_removed, programmes_removed


_EPG_ATTR_RE = re.compile(r'\b(url-tvg|x-tvg-url)="([^"]*)"', re.IGNORECASE)


def _last_component(ref: str) -> str:
    return re.split(r"[/\\]", ref.strip())[-1]


def set_epg_reference(header: str, old_epg: Path | None, new_name: str) -> str:
    """Point the #EXTM3U header's EPG reference (url-tvg / x-tvg-url) at the
    new EPG file name.

    - Any reference whose file name matches the input EPG is renamed; a
      leading folder or URL prefix on it is kept (http://h/epg.xml ->
      http://h/<new_name>).
    - If none match, the attribute value is replaced with new_name.
    - If the header has no EPG attribute at all, url-tvg is added.
    """
    header = header if header.startswith("#EXTM3U") else "#EXTM3U"
    old_name = old_epg.name if old_epg else None

    def rewrite_value(value: str) -> str:
        items = [i.strip() for i in value.split(",") if i.strip()]
        hit = False
        out = []
        for item in items:
            if old_name and _last_component(item) == old_name:
                prefix = item[: len(item) - len(old_name)]
                out.append(prefix + new_name)
                hit = True
            else:
                out.append(item)
        if not hit:
            return new_name
        return ",".join(dict.fromkeys(out))  # de-dupe, keep order

    if _EPG_ATTR_RE.search(header):
        return _EPG_ATTR_RE.sub(
            lambda m: f'{m.group(1)}="{rewrite_value(m.group(2))}"', header
        )
    return f'{header.rstrip()} url-tvg="{new_name}"'


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog="Valid category names: " + ", ".join(known_categories()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("m3u", type=Path, help="Input channels.m3u")
    ap.add_argument("epg", type=Path, nargs="?", default=None, help="Optional epg.xml")
    ap.add_argument(
        "-o", "--output", type=Path, default=Path("channels_grouped.m3u"),
        help="Output M3U path (default: channels_grouped.m3u)",
    )
    ap.add_argument(
        "--epg-output", type=Path, default=None,
        help="Filtered EPG output path, written when categories are removed "
             "(default: <epg name>_filtered.xml next to the input EPG)",
    )
    ap.add_argument(
        "-r", "--remove-category", action="append", metavar="CATEGORY",
        help="Category to remove from the M3U and EPG. Repeatable; "
             "comma-separated values are also accepted. Case-insensitive.",
    )
    ap.add_argument(
        "--remove-file", type=Path, metavar="FILE",
        help="Text file of categories to remove (one per line or "
             "comma-separated; '#' starts a comment)",
    )
    ap.add_argument(
        "--no-epg-language", action="store_true",
        help="Disable non-English language detection from the EPG",
    )
    ap.add_argument(
        "--lang-priority", choices=("override", "fallback"), default="override",
        help="override (default): an EPG-detected language beats the name/genre "
             "rules. fallback: use it only when the name rules found nothing.",
    )
    ap.add_argument(
        "--lang-threshold", type=float, default=0.5, metavar="FRACTION",
        help="Fraction of a channel's classifiable programmes that must be in "
             "one non-English language (default: 0.5)",
    )
    ap.add_argument(
        "--min-lang-programmes", type=int, default=3, metavar="N",
        help="Minimum non-English programmes needed before a channel is "
             "assigned a language group (default: 3)",
    )
    args = ap.parse_args()

    if not args.m3u.is_file():
        sys.exit(f"M3U not found: {args.m3u}")
    if args.remove_file and not args.remove_file.is_file():
        sys.exit(f"Remove-categories file not found: {args.remove_file}")

    remove = collect_remove_categories(args.remove_category, args.remove_file)
    if remove:
        valid = {_norm_cat(c) for c in known_categories()}
        unknown = sorted(r for r in remove if r not in valid)
        if unknown:
            print(
                f"  [warn] Unknown categories (will match nothing unless a "
                f"channel is assigned them): {', '.join(unknown)}\n"
                f"         Valid: {', '.join(known_categories())}",
                file=sys.stderr,
            )

    print(f"Reading {args.m3u} ...")
    header, entries = parse_m3u(args.m3u)
    print(f"  {len(entries)} channels")

    epg_genres: dict[str, Counter] = {}
    epg_langs: dict[str, Counter] = {}
    epg_available = bool(args.epg) and args.epg.is_file()
    if args.epg and not epg_available:
        print(f"  [warn] EPG not found: {args.epg}", file=sys.stderr)
    if epg_available:
        what = "genre hints" if args.no_epg_language else "genre and language hints"
        print(f"Scanning {args.epg} for {what} ...")
        epg_genres, epg_langs = scan_epg(
            args.epg, detect_language=not args.no_epg_language
        )
        print(f"  genre data for {len(epg_genres)} channels")
        if not args.no_epg_language:
            print(f"  language data for {len(epg_langs)} channels")

    counts: Counter = Counter()
    sources: Counter = Counter()
    removed_counts: Counter = Counter()
    kept_ids: set[str] = set()
    dropped_ids: set[str] = set()
    removed_without_id = 0

    # Decide the filtered-EPG path now so the M3U header can reference it.
    epg_out: Path | None = None
    if remove and epg_available:
        epg_out = args.epg_output or args.epg.with_name(
            f"{args.epg.stem}_filtered{args.epg.suffix or '.xml'}"
        )
        if epg_out.resolve() == args.epg.resolve():
            sys.exit("--epg-output must differ from the input EPG path")
        header = set_epg_reference(header, args.epg, epg_out.name)
        print(f"M3U header will reference EPG file: {epg_out.name}")
    out_lines = [header if header.startswith("#EXTM3U") else "#EXTM3U"]

    for e in entries:
        title = e["title"]
        id_m = re.search(r'tvg-id="([^"]*)"', e["attrs"])
        channel_id = id_m.group(1) if id_m else ""
        group, source = classify_channel(
            title, channel_id, epg_genres, epg_langs,
            lang_priority=args.lang_priority,
            min_lang_programmes=args.min_lang_programmes,
            lang_threshold=args.lang_threshold,
        )

        if _norm_cat(group) in remove:
            removed_counts[group] += 1
            if channel_id:
                dropped_ids.add(channel_id)
            else:
                removed_without_id += 1
            continue

        if channel_id:
            kept_ids.add(channel_id)
        counts[group] += 1
        sources[source] += 1
        out_lines.append(rewrite_extinf(e["attrs"], title, group))
        out_lines.append(e["url"])

    args.output.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    kept = sum(counts.values())
    print(f"Wrote {kept} channels to {args.output}")
    if remove:
        print(f"Removed {sum(removed_counts.values())} channels from the M3U")

    # --- EPG: drop removed channels (only ids no kept channel still uses) ---
    if remove:
        if not args.epg:
            print("No EPG given; only the M3U was filtered.")
        elif not epg_available:
            print("EPG file missing; only the M3U was filtered.")
        else:
            remove_ids = dropped_ids - kept_ids
            print(f"Filtering {args.epg} -> {epg_out} ...")
            n_ch, n_prog = filter_epg(args.epg, epg_out, remove_ids)
            print(f"  removed {n_ch} <channel> and {n_prog} <programme> entries")
            if removed_without_id:
                print(
                    f"  [note] {removed_without_id} removed channel(s) had no "
                    f"tvg-id, so their EPG entries could not be matched",
                    file=sys.stderr,
                )

    print("\nCategory breakdown:", file=sys.stderr)
    for cat, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {n:4d}  {cat}", file=sys.stderr)

    print("\nClassified by:", file=sys.stderr)
    for src_name, n in sorted(sources.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {n:4d}  {src_name}", file=sys.stderr)

    if removed_counts:
        print("\nRemoved categories:", file=sys.stderr)
        for cat, n in sorted(removed_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {n:4d}  {cat}", file=sys.stderr)


if __name__ == "__main__":
    main()
