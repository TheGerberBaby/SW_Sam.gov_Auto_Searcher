"""Ad-hoc filter for small-team IT/VTC opportunities. Not part of the project."""
import sqlite3, re, sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = Path(__file__).resolve().parents[2]
DB = PROJECT_DIR / "data" / "contracts.db"
TODAY = date(2026, 5, 27)
MIN_DEADLINE = TODAY + timedelta(days=2)

IT_NAICS = (
    "5415", "51821", "5182", "51741", "517919", "51811",
    "541612", "541618", "541690", "611420", "611430",
)
ALLOW_IF_STRONG_IT_NAICS = ("811210", "238210", "517810", "334111", "334118")

STRONG_RE = re.compile(
    r"\b(it\s+support|help\s*desk|service\s+desk|desktop\s+support|"
    r"system\s+administrator|sysadmin|network\s+(engineer|administrat|design|"
    r"refresh|modernization|upgrade|integration|switch|support)|"
    r"vtc|svtc|video\s+teleconfer|audio[\s-]?visual\s+(install|integration|"
    r"engineering|support|maintenance)|av[\s/-]vtc|"
    r"unified\s+communications?|cisco|microsoft\s+365|m365|office\s+365|"
    r"sharepoint|microsoft\s+teams|webex|zoom\s+rooms|crestron|polycom|"
    r"workflow\s+automation|power\s+(automate|apps|bi)|"
    r"cybersecurity\s+(assessment|engineering|services|support|analyst|"
    r"professional|specialist)|"
    r"vulnerability\s+(assessment|scan|management)|penetration\s+test|"
    r"risk\s+management\s+framework|\brmf\b|\bato\b\s+(support|package|"
    r"documentation)|\bfedramp\b|\bnist\b\s+(800|csf)|"
    r"\bsiem\b|splunk|elastic\s+(stack|search|agent|security)|elasticsearch|"
    r"opensearch|kibana|logstash|observability|log\s+(analytics|management)|"
    r"cloud\s+(migration|engineer|architect|integration|computing)|"
    r"\baws\b|\bazure\b|\bgcp\b|kubernetes|docker|"
    r"data\s+(labeling|engineering|integration|pipeline|warehous|migration|"
    r"analytics)|"
    r"machine\s+learning|generative\s+ai|\bllm\b|"
    r"retrieval\s+augmented|vector\s+(search|database)|semantic\s+search|"
    r"knowledge\s+(management|graph)|"
    r"software\s+(development|engineering|sustainment|modernization)|"
    r"application\s+(development|modernization|sustainment)|"
    r"web\s+(development|application)|api\s+(development|integration)|"
    r"server\s+(replacement|refresh|migration|consolidation)|"
    r"virtual\s+desktop|\bvdi\b|citrix|"
    r"it\s+training|cybersecurity\s+training|"
    r"managed\s+(it|services|security)|noc/soc)\b",
    re.IGNORECASE,
)

TITLE_KILL = re.compile(
    r"\b(siemens|reagent|feeder|roof|hvac|janitor|paving|asphalt|boiler|"
    r"elevator|fire\s+alarm|plumbing|strap|hose|valve|gasket|bearing|bushing|"
    r"tire|brake|lubricant|paint|carpet|fence|chinking|backflow|"
    r"forklift|boom\s+lift|crane|sterntube|propeller|aircraft\s+(part|"
    r"component|engine)|fabrication\s+of|missile|munition|"
    r"furniture|uniform|food|catering|laundry|grounds|landscape|snow|pest|"
    r"custodial|fuel\s+delivery|interior\s+repair|exterior\s+repair|"
    r"window\s+replace|asbestos|abatement|chiller|water\s+heater|"
    r"award\s+devices?|medal|coin|plaque|trophy|"
    r"pipe|screws?|fittings?|socket|bolt|nut|"
    r"vehicle|truck|trailer|generator\s+(repair|replac|maintenance)|"
    r"shaft\s+assembly|tube\s+shaft|electric\s+motor|"
    r"emp(loyee)?\s+assistance|substance\s+abuse|counseling|"
    r"language\s+(course|instructor)|foreign\s+language)\b",
    re.IGNORECASE,
)

EXCLUDE_TYPES = {"award notice", "justification"}

SQL = """
SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
       type, set_aside, response_deadline, naics_code, pop_city, pop_state,
       link, description
FROM opportunities
WHERE active = 'Yes'
  AND posted_date >= '2026-04-01'
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
    ntype = (r["type"] or "").lower()
    if ntype in EXCLUDE_TYPES: continue
    if TITLE_KILL.search(title): continue
    text = title + "\n" + desc
    naics_primary = any(naics.startswith(p) for p in IT_NAICS)
    naics_conditional = any(naics.startswith(p) for p in ALLOW_IF_STRONG_IT_NAICS)
    strong = list({m.group(0).lower() for m in STRONG_RE.finditer(text)})
    if naics_primary:
        if not strong and not re.search(
            r"\b(it|cyber|cloud|software|network|data|database|web|app|server|"
            r"technical|sustain|modern|integration|engineering)\b",
            title, re.IGNORECASE):
            continue
    elif naics_conditional:
        if len(strong) < 2:
            continue
    else:
        continue
    dl = parse_deadline(r["response_deadline"])
    if dl is None:
        deadline_state, dl_days = "unknown", None
    elif dl < MIN_DEADLINE:
        continue
    else:
        deadline_state = dl.isoformat()
        dl_days = (dl - TODAY).days
    sa = (r["set_aside"] or "").lower()
    is_sba = ("total small business" in sa or sa.startswith("sba")
              or "small business set-aside (far 19.5)" in sa)
    is_sb_any = (is_sba or "small business" in sa or "8(a)" in sa
                 or "wosb" in sa or "veteran-owned" in sa or "hubzone" in sa)
    hits.append({
        "title": title, "dept": r["department"] or "", "sub": r["sub_tier"] or "",
        "posted": (r["posted_date"] or "")[:10], "deadline": deadline_state,
        "dl_days": dl_days, "type": r["type"] or "",
        "set_aside": r["set_aside"] or "",
        "is_sba": is_sba, "is_sb_any": is_sb_any, "naics": naics,
        "pop": f'{r["pop_city"] or ""} {r["pop_state"] or ""}'.strip(),
        "matches": strong[:5], "link": r["link"] or "",
        "desc_snip": desc[:340].replace("\n", " "),
    })

def rank(h):
    s = 0
    if h["is_sba"]: s += 5
    elif h["is_sb_any"]: s += 3
    if any(h["naics"].startswith(p) for p in ("541512", "541519", "5181", "5182")):
        s += 2
    elif h["naics"].startswith("5415"):
        s += 1
    t = h["type"].lower()
    if "sources sought" in t or "rfi" in t: s += 1
    elif "combined" in t or t == "solicitation": s += 2
    elif "presolicit" in t: s += 1
    if h["dl_days"] is not None:
        if 5 <= h["dl_days"] <= 45: s += 2
        elif 46 <= h["dl_days"] <= 90: s += 1
    s += min(len(h["matches"]), 3)
    return -s

hits.sort(key=rank)

print(f"# Filtered hits: {len(hits)}\n")
for i, h in enumerate(hits[:30], 1):
    flag = "*SBA*" if h["is_sba"] else ("*SB*" if h["is_sb_any"] else "    ")
    dl_str = (f"{h['deadline']} ({h['dl_days']}d)" if h["dl_days"] is not None
              else "unknown")
    print(f"{i:2}. {flag} [{h['naics']}] {h['title']}")
    print(f"      {h['dept']} / {h['sub']}")
    print(f"      type: {h['type']} | set-aside: {h['set_aside'] or '(none)'}")
    print(f"      POP: {h['pop']} | posted {h['posted']} | deadline {dl_str}")
    print(f"      matches: {', '.join(h['matches']) or '(naics-only)'}")
    print(f"      {h['link']}")
    print(f"      > {h['desc_snip']}")
    print()
