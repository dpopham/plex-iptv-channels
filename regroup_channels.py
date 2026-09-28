#!/usr/bin/env python3
"""
regroup_channels.py

Reads a Plex Live TV channels.m3u (all group-title="Plex") and an optional
epg.xml, then rewrites the M3U with more useful group-title values:

  News, Sports, Spanish, Movies, Crime, Music, Kids, Reality, Comedy,
  Sci-Fi / Fantasy, Drama, Lifestyle, Food, Documentary, Shopping,
  Anime, Western, Gaming, Religion, Weather, Classic TV, Wrestling, Other

Classification is primarily keyword-based on the channel name, with optional
hints from EPG programme data when available.

Usage
-----
    python regroup_channels.py channels.m3u epg.xml -o channels_grouped.m3u
    python regroup_channels.py channels.m3u -o channels_grouped.m3u
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

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


def load_epg_genres(epg_path: Path | None) -> dict[str, Counter]:
    """Optional map channel-id -> Counter of soft genre signals from EPG."""
    if not epg_path or not epg_path.is_file():
        return {}

    genres: dict[str, Counter] = defaultdict(Counter)
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
            elem.clear()
    except ET.ParseError as exc:
        print(f"  [warn] Could not fully parse EPG: {exc}", file=sys.stderr)
    return genres


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


def classify_with_epg(title: str, channel_id: str, epg_genres: dict[str, Counter]) -> str:
    cat = classify_name(title)
    if cat != "Other":
        return cat
    counts = epg_genres.get(channel_id)
    if not counts:
        return "Other"
    best_cat, best_n = None, 0
    for genre, n in counts.most_common():
        mapped = _EPG_GENRE_MAP.get(genre.lower())
        if mapped and n > best_n:
            best_cat, best_n = mapped, n
    return best_cat or "Other"


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


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("m3u", type=Path, help="Input channels.m3u")
    ap.add_argument("epg", type=Path, nargs="?", default=None, help="Optional epg.xml")
    ap.add_argument(
        "-o", "--output", type=Path, default=Path("channels_grouped.m3u"),
        help="Output M3U path (default: channels_grouped.m3u)",
    )
    args = ap.parse_args()

    if not args.m3u.is_file():
        sys.exit(f"M3U not found: {args.m3u}")

    print(f"Reading {args.m3u} ...")
    header, entries = parse_m3u(args.m3u)
    print(f"  {len(entries)} channels")

    epg_genres: dict[str, Counter] = {}
    if args.epg:
        print(f"Scanning {args.epg} for genre hints ...")
        epg_genres = load_epg_genres(args.epg)
        print(f"  genre data for {len(epg_genres)} channels")

    counts: Counter = Counter()
    out_lines = [header if header.startswith("#EXTM3U") else "#EXTM3U"]

    for e in entries:
        title = e["title"]
        id_m = re.search(r'tvg-id="([^"]*)"', e["attrs"])
        channel_id = id_m.group(1) if id_m else ""
        group = classify_with_epg(title, channel_id, epg_genres)
        counts[group] += 1
        out_lines.append(rewrite_extinf(e["attrs"], title, group))
        out_lines.append(e["url"])

    args.output.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(entries)} channels to {args.output}")

    print("\nCategory breakdown:", file=sys.stderr)
    for cat, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {n:4d}  {cat}", file=sys.stderr)


if __name__ == "__main__":
    main()
