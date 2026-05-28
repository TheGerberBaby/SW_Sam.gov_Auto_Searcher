"""Ad-hoc filter for quote-back / reseller RFQs - commercial-item buys where
you source from a distributor, add markup, and submit. Not part of the project.
"""
import sqlite3, re, sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path(__file__).resolve().parent.parent / "data" / "contracts.db"
TODAY = date(2026, 5, 27)
MIN_DEADLINE = TODAY + timedelta(days=4)   # need time to source + quote
MAX_DEADLINE = TODAY + timedelta(days=45)  # easy kills are short-fuse

# Product-leaning NAICS - reseller territory. Grouped by category for ranking.
NAICS_TIERS = {
    "IT/VTC products": (
        "423430",  # computer/peripheral wholesale
        "334111",  # computer hardware
        "334118",  # computer peripherals
        "334210",  # telephone apparatus
        "334220",  # radio/TV broadcasting equipment
        "334290",  # other communications equipment
        "334310",  # audio/video equipment
        "334413",  # semiconductors
        "334417",  # connectors
        "334419",  # other electronic components
        "511210",  # software publishers (commercial software resale)
        "423410",  # photographic equipment
    ),
    "Tech-adjacent products": (
        "335311",  # transformers
        "335312",  # motors/generators
        "335931",  # current-carrying wiring devices
        "335999",  # other electrical equipment
        "333316",  # photographic equipment mfg
        "334512",  # automatic environmental controls
        "334513",  # industrial process controls
        "334515",  # measuring instruments
        "334516",  # analytical lab instruments
        "334519",  # other measuring instruments
    ),
    "Other commodities": (
        "423120",  # motor vehicle supplies
        "423610",  # electrical apparatus wholesale
        "423620",  # household appliances wholesale
        "423690",  # other electronic parts wholesale
        "423840",  # industrial supplies wholesale
        "423850",  # service establishment equipment
        "423860",  # transportation equipment wholesale
        "424690",  # other chemical wholesale (lab reagents excluded later)
        "337127",  # institutional furniture
        "337215",  # showcase / locker / shelving
        "339113",  # surgical appliances (medical excluded later)
        "315990",  # apparel accessories
        "316210",  # footwear
    ),
}

def naics_tier(naics: str) -> str | None:
    for tier, prefixes in NAICS_TIERS.items():
        if any(naics.startswith(p) for p in prefixes):
            return tier
    return None

# Language that signals quote-back work
QUOTE_RE = re.compile(
    r"\b(brand[\s-]name|or[\s-]equal|or[\s-]equivalent|request\s+for\s+quot|"
    r"\brfq\b|commercial\s+off[\s-]the[\s-]shelf|\bcots\b|manufacturer|"
    r"\boem\b|reseller|distributor|authorized\s+(dealer|reseller|partner)|"
    r"part\s+number|model\s+(number|no\.)|sole\s+source|notice\s+of\s+intent|"
    r"line\s+item|clin\s+\d|quantit(y|ies)\s+of)\b",
    re.IGNORECASE,
)

# Service-heavy language that disqualifies (when not paired with a product spec)
SERVICE_KILL = re.compile(
    r"\b(sustainment\s+support|\bseta\b|a&as|advisory\s+and\s+assistance|"
    r"managed\s+services|professional\s+services|engineering\s+support|"
    r"systems\s+engineering|technical\s+support\s+services|staff\s+augment|"
    r"on-?site\s+(personnel|staff|operations)|24/7\s+(coverage|support|"
    r"operations))\b",
    re.IGNORECASE,
)

# Hard title kills - things you cannot quote-back or that are dead-ends
TITLE_KILL = re.compile(
    r"\b(reagent|test\s+kit|medical\s+supplies?|pharmaceutical|"
    r"food\s+(supply|service)|catering|janitorial|grounds|landscape|"
    r"snow\s+removal|pest|custodial|fuel\s+delivery|asbestos|abatement|"
    r"new\s+construction|demolition|paving|roofing\s+(installation|"
    r"replacement|repair)|hvac\s+(installation|replacement|repair)|"
    r"language\s+(course|instructor)|foreign\s+language|"
    r"counseling|substance\s+abuse|employee\s+assistance)\b",
    re.IGNORECASE,
)

# NAICS to never accept regardless
NAICS_BLOCK = ("23",         # construction
               "311", "312", "31499",  # food
               "325413",     # medical reagents
               "325412",     # pharma
               "541330",     # engineering services (large)
               )

SQL = """
SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
       type, set_aside, response_deadline, naics_code, pop_city, pop_state,
       link, description
FROM opportunities
WHERE active = 'Yes'
  AND posted_date >= '2026-04-15'
  AND (type LIKE '%Combined%' OR type = 'Solicitation' OR type LIKE '%Presolicit%')
"""

def parse_deadline(s):
    if not s: return None
    s = s.strip().replace("Z", "+00:00")
    try: return datetime.fromisoformat(s).date()
    except ValueError:
        try: return date.fromisoformat(s[:10])
        except ValueError: return None

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(SQL).fetchall()

hits = []
for r in rows:
    title = r["title"] or ""
    desc = r["description"] or ""
    naics = (r["naics_code"] or "").strip()
    if any(naics.startswith(p) for p in NAICS_BLOCK): continue
    if TITLE_KILL.search(title): continue
    tier = naics_tier(naics)
    if tier is None: continue
    text = title + "\n" + desc
    # Quote-back signal: at least one match, and not dominated by service language
    quote_matches = list({m.group(0).lower() for m in QUOTE_RE.finditer(text)})
    if not quote_matches: continue
    service_matches = SERVICE_KILL.findall(text)
    if len(service_matches) >= 2 and len(quote_matches) < 3: continue
    dl = parse_deadline(r["response_deadline"])
    if dl is None: continue
    if dl < MIN_DEADLINE or dl > MAX_DEADLINE: continue
    deadline_state = dl.isoformat()
    dl_days = (dl - TODAY).days
    sa = (r["set_aside"] or "").lower()
    is_sba = ("total small business" in sa or sa.startswith("sba")
              or "small business set-aside (far 19.5)" in sa)
    is_sb_any = (is_sba or "small business" in sa or "8(a)" in sa
                 or "wosb" in sa or "veteran-owned" in sa or "hubzone" in sa)
    # Must have set-aside to count as "easy kill" - else big primes crowd you out
    if not is_sb_any: continue
    hits.append({
        "title": title, "dept": r["department"] or "",
        "sub": r["sub_tier"] or "", "posted": (r["posted_date"] or "")[:10],
        "deadline": deadline_state, "dl_days": dl_days,
        "type": r["type"] or "", "set_aside": r["set_aside"] or "",
        "is_sba": is_sba, "naics": naics, "tier": tier,
        "pop": f'{r["pop_city"] or ""} {r["pop_state"] or ""}'.strip(),
        "quote_matches": quote_matches[:5], "link": r["link"] or "",
        "notice_id": r["notice_id"] or "",
        "sol_number": r["sol_number"] or "",
        "desc_snip": desc[:380].replace("\n", " "),
    })

TIER_RANK = {"IT/VTC products": 3, "Tech-adjacent products": 2, "Other commodities": 1}

def rank(h):
    s = 0
    s += TIER_RANK.get(h["tier"], 0) * 2
    if h["is_sba"]: s += 4
    else: s += 2
    if 5 <= h["dl_days"] <= 21: s += 3
    elif 22 <= h["dl_days"] <= 35: s += 2
    else: s += 1
    s += min(len(h["quote_matches"]), 3)
    t = h["type"].lower()
    if "combined" in t: s += 1
    return -s

hits.sort(key=rank)

print(f"# Quote-back candidates: {len(hits)}\n")
for i, h in enumerate(hits[:35], 1):
    flag = "*SBA*" if h["is_sba"] else "*SB *"
    print(f"{i:2}. {flag} [{h['tier']}] [{h['naics']}] {h['title']}")
    print(f"      {h['dept']} / {h['sub']}")
    print(f"      type: {h['type']} | set-aside: {h['set_aside']}")
    print(f"      sol#: {h['sol_number']} | POP: {h['pop']}")
    print(f"      posted {h['posted']} | deadline {h['deadline']} ({h['dl_days']}d)")
    print(f"      quote-signals: {', '.join(h['quote_matches'])}")
    print(f"      {h['link']}")
    print(f"      > {h['desc_snip']}")
    print()
