"""Source local subcontractors/vendors to perform an opportunity.

This is the fulfillment lane: once you decide to prime an opportunity, this
finds local companies that can actually do the work, returns their phone
numbers, and prints a cold-call script plus the email ask-list so you can dial
them one by one.

Loads GOOGLE_PLACES_API_KEY from the project `.env` file. Business discovery
uses the Google Places API (New) Text Search endpoint.

Examples:
  python source_vendors.py --naics 561621 --place "Alexandria, VA"
  python source_vendors.py --naics 238210 --place "Dover, DE" --due "29 Jun 2026"
  python source_vendors.py --naics 562111 --place "St. Croix Falls, WI" --json
  python source_vendors.py --naics 561790 --place "Dover AFB, DE" --script-only
  python source_vendors.py "tree removal" --place "Accokeek, MD" --max 8

NAICS-to-search-term and qualifying-question logic lives in
`criteria/VENDOR_SOURCING_PROFILE.md`; the in-code table below mirrors it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PROJECT_DIR = Path(__file__).resolve().parent.parent
FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
    ]
)


# Deterministic, explainable NAICS -> how to find and qualify performers.
# Keep this table in sync with criteria/VENDOR_SOURCING_PROFILE.md.
VENDOR_PROFILES: dict[str, dict] = {
    "561621": {  # Security Systems Services (except Locksmiths)
        "label": "security systems / access-control installation",
        "terms": [
            "commercial security camera access control installer",
            "low voltage security systems contractor",
        ],
        "qualifiers": [
            "install security cameras and access-control systems",
            "handle low-voltage cabling and testing",
            "confirm any required state license and OEM certifications",
        ],
        "asks": [
            "Can you install and test the required cameras, access-control components, and low-voltage cabling?",
            "Which state licenses, technician registrations, and OEM certifications does your crew hold?",
            "Can you provide a firm quote broken out by equipment, installation labor, and testing?",
            "Two or three references for similar commercial or government work?",
        ],
    },
    "238210": {  # Electrical Contractors and Other Wiring Installation Contractors
        "label": "structured cabling / low-voltage installation",
        "terms": [
            "structured cabling low voltage contractor",
            "Cat6 fiber optic cabling installer",
        ],
        "qualifiers": [
            "install and test Cat6 and bounded fiber runs",
            "provide cable-test results",
            "confirm any required low-voltage license",
        ],
        "asks": [
            "Can you install, terminate, label, and test the required Cat6 and fiber runs?",
            "Can you provide cable-test results and as-built documentation?",
            "Which state licenses or technician registrations does your crew hold for the work?",
            "Can you provide a firm quote broken out by line item or drop?",
            "Two or three references for similar commercial or government work?",
        ],
    },
    "561790": {  # Services to Buildings and Dwellings (kitchen exhaust cleaning)
        "label": "kitchen hood and exhaust cleaning",
        "terms": [
            "commercial kitchen exhaust hood cleaning",
            "NFPA 96 hood cleaning service",
        ],
        "qualifiers": [
            "be IKECA certified with a CECS on site",
            "clean to bare metal per NFPA 96",
        ],
        "asks": [
            "Are you IKECA certified with a Certified Exhaust Cleaning Specialist (CECS) on staff?",
            "Can your crew work the late-night / early-morning cleaning windows?",
            "Can you give a firm quote broken out per system / building?",
            "Two or three references for similar commercial or government work?",
        ],
    },
    "562111": {  # Solid Waste Collection
        "label": "solid waste / trash collection",
        "terms": ["commercial waste collection garbage hauling", "dumpster route service"],
        "qualifiers": [
            "run a regular scheduled route",
            "have a spill plan",
            "have a safety plan",
        ],
        "asks": [
            "Do you run regular scheduled collection routes (not just roll-off / one-time hauls)?",
            "How far out from your base will your trucks run a recurring route?",
            "Do you have a written spill-prevention/response plan and a safety plan?",
            "Can you give a firm quote per pickup location and frequency?",
            "Two or three references for recurring commercial or government accounts?",
        ],
    },
    "561720": {  # Janitorial Services
        "label": "janitorial / custodial",
        "terms": ["commercial janitorial cleaning service", "building custodial services"],
        "qualifiers": [
            "staff a crew on a set schedule",
            "pass background checks for facility access",
        ],
        "asks": [
            "Can you staff a recurring crew at the required frequency?",
            "Are your workers OK with the background checks / badging for facility access?",
            "Do you supply your own equipment and consumables?",
            "Two or three references for similar commercial or government accounts?",
        ],
    },
    "561730": {  # Landscaping Services
        "label": "grounds maintenance / landscaping",
        "terms": [
            "commercial landscaping grounds maintenance",
            "commercial mowing snow removal",
        ],
        "qualifiers": [
            "handle the full grounds scope on a schedule",
            "be licensed and insured",
        ],
        "asks": [
            "Can you cover the full grounds scope (mowing, trimming, seasonal) on schedule?",
            "Licensed and insured for commercial/government work?",
            "Can you give a firm quote per site / per cycle?",
            "Two or three references for similar accounts?",
        ],
    },
    "238220": {  # Plumbing, Heating, and Air-Conditioning Contractors
        "label": "HVAC / mechanical service",
        "terms": ["commercial HVAC service contractor", "commercial mechanical contractor"],
        "qualifiers": [
            "be a licensed mechanical contractor",
            "carry the right insurance",
        ],
        "asks": [
            "Are you a licensed commercial mechanical/HVAC contractor in the state of performance?",
            "Can you meet the response-time / PM-schedule requirements?",
            "Firm quote broken out by unit / task?",
            "Two or three references for similar commercial or government work?",
        ],
    },
}

GENERIC_PROFILE = {
    "label": "the work",
    "terms": [],
    "qualifiers": ["handle the full scope on schedule", "be licensed and insured"],
    "asks": [
        "Can you handle the full scope on the required schedule?",
        "Licensed and insured for commercial/government work?",
        "Can you give a firm quote broken out by line item?",
        "Two or three references for similar work?",
    ],
}


def resolve_profile(naics: str | None, service: str | None) -> dict:
    """Pick a vendor profile from NAICS, falling back to a free-text generic."""
    profile = None
    if naics and naics.strip() in VENDOR_PROFILES:
        profile = dict(VENDOR_PROFILES[naics.strip()])
    if profile is None:
        profile = dict(GENERIC_PROFILE)
        if service:
            profile["label"] = service.strip()
    terms = list(profile.get("terms", []))
    if service and service.strip():
        service = service.strip()
        terms = [service] + [term for term in terms if term.lower() != service.lower()]
    profile["terms"] = terms
    return profile


def _join_casual(items: list[str]) -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def build_call_script(
    operator: str,
    label: str,
    place: str,
    due: str | None,
    qualifiers: list[str],
) -> str:
    """Generate the operator's short first-call script."""
    due_clause = f" due by {due}" if due else ""
    place_clause = f" out by {place}" if place else ""
    quals = _join_casual(qualifiers) or "handle the work on a schedule"
    return f"""\
[OPENER]
"Hey, how's it going -- my name's {operator}, I'm a vet-owned small business and
 I bid on federal contracts. I got one here, it's a {label} contract{place_clause}{due_clause}.
 Basically they need someone who can {quals}, that kind of thing. That something you guys do?"

[IF INTERESTED]
"Ok cool. There's a little more to it -- locations, frequency, the qualifications they want --
 so what I'll do is shoot you an email with all the stuff and you can get me a quote.
 What's a good email to send it to?"

[CLOSE]
"Perfect, appreciate it -- I'll get that right over to you. Talk soon."

[IF THEY'RE BIDDING IT THEMSELVES]
"Oh you're going for it yourself? All good man, appreciate your time."
"""


def build_email_asks(profile: dict) -> list[str]:
    """Return profile questions plus standard subcontracting questions."""
    asks = list(profile.get("asks", []))
    asks.append("Payment terms -- can you work pay-when-paid / net-30+ rather than pay-on-completion?")
    asks.append("Are you under the NAICS small-business size standard? (keeps the teaming clean)")
    return asks


def build_email_draft(
    operator: str,
    label: str,
    place: str,
    due: str | None,
    asks: list[str],
) -> str:
    """Generate a short follow-up email after a vendor expresses interest."""
    due_clause = f" The prime quote is due {due}." if due else ""
    questions = "\n".join(f"{index}. {ask}" for index, ask in enumerate(asks, 1))
    return f"""\
Subject: Subcontract quote request - {label} - {place}

Hi [name],

Thanks for taking my call. I am {operator} with Stormwind Contracting, a
vet-owned small business preparing a federal prime quote for {label} work in
{place}.{due_clause}

Could you review the scope and reply with your quote plus answers to these
questions?

{questions}

Please include any assumptions, exclusions, schedule concerns, and the best
person to contact for follow-up.

Thanks,

{operator}
Stormwind Contracting
"""


def load_project_env() -> None:
    """Load the first available project-local dotenv file."""
    for env_path in [PROJECT_DIR / ".env", Path(__file__).resolve().parent / ".env"]:
        if env_path.exists():
            load_dotenv(env_path)
            return
    load_dotenv()


def get_places_api_key() -> str:
    """Return the configured Places key without exposing it to callers."""
    load_project_env()
    return os.getenv("GOOGLE_PLACES_API_KEY", "").strip()


def generate_vendor_package(
    *,
    naics: str | None = None,
    service: str | None = None,
    place: str,
    due: str | None = None,
    operator: str | None = None,
    max_results: int = 6,
    script_only: bool = False,
    api_key: str | None = None,
    allow_script_fallback: bool = False,
) -> dict:
    """Generate fresh vendor leads plus the matching outreach material."""
    clean_naics = (naics or "").strip() or None
    clean_service = (service or "").strip() or None
    clean_place = (place or "").strip()
    if not clean_place:
        raise ValueError("provide a place of performance")
    if not clean_service and clean_naics not in VENDOR_PROFILES:
        raise ValueError(
            "provide a free-text service, or a --naics with a known profile "
            f"(one of: {', '.join(VENDOR_PROFILES)})"
        )

    profile = resolve_profile(clean_naics, clean_service)
    queries = [f"{term} near {clean_place}" for term in profile["terms"]]
    max_results = max(1, min(int(max_results), 20))
    operator = (operator or os.getenv("OPERATOR_NAME", "Jeremy")).strip() or "Jeremy"

    discovery_error = None
    effective_script_only = bool(script_only)
    places_key = (api_key if api_key is not None else get_places_api_key()).strip()
    if not effective_script_only and not places_key:
        if not allow_script_fallback:
            raise ValueError(f"GOOGLE_PLACES_API_KEY not set. Add it to {PROJECT_DIR / '.env'}")
        effective_script_only = True
        discovery_error = (
            "Fresh lead discovery is unavailable until GOOGLE_PLACES_API_KEY is "
            f"added to {PROJECT_DIR / '.env'}. The outreach material was generated."
        )

    vendors: list[dict] = []
    if not effective_script_only:
        for query in queries:
            vendors.extend(search_places(query, places_key, max_results))
    vendors = dedupe(vendors)[:max_results]

    call_script = build_call_script(
        operator,
        profile["label"],
        clean_place,
        due,
        profile["qualifiers"],
    )
    email_asks = build_email_asks(profile)
    return {
        "naics": clean_naics,
        "service_label": profile["label"],
        "place": clean_place,
        "due": due,
        "queries": queries,
        "vendors": vendors,
        "discovery_requested": not script_only,
        "discovery_skipped": effective_script_only,
        "discovery_error": discovery_error,
        "call_script": call_script,
        "email_asks": email_asks,
        "email_draft": build_email_draft(operator, profile["label"], clean_place, due, email_asks),
    }


def search_places(query: str, api_key: str, max_results: int) -> list[dict]:
    """Search Google Places and return operational businesses only."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {"textQuery": query, "maxResultCount": max(1, min(max_results, 20))}
    try:
        response = requests.post(
            PLACES_URL,
            headers=headers,
            json=body,
            timeout=(10, 60),
        )
    except requests.Timeout:
        sys.exit("Google Places is slow or unresponsive (>60s). Try again shortly.")
    except requests.RequestException as exc:
        sys.exit(f"Network error: {exc}")

    if response.status_code in (401, 403):
        sys.exit(
            f"Auth error ({response.status_code}): check GOOGLE_PLACES_API_KEY. "
            f"Response: {response.text[:300]}"
        )
    if response.status_code == 429:
        sys.exit("Rate limited by Google Places. Wait and retry.")
    if response.status_code != 200:
        sys.exit(f"Places API error {response.status_code}: {response.text[:500]}")

    vendors = []
    for place in response.json().get("places", []):
        status = place.get("businessStatus", "")
        if status and status != "OPERATIONAL":
            continue
        vendors.append(
            {
                "name": (place.get("displayName") or {}).get("text", ""),
                "phone": place.get("nationalPhoneNumber", ""),
                "address": place.get("formattedAddress", ""),
                "website": place.get("websiteUri", ""),
                "rating": place.get("rating"),
                "rating_count": place.get("userRatingCount"),
                "status": status,
            }
        )
    return vendors


def dedupe(vendors: list[dict]) -> list[dict]:
    """Deduplicate discovered vendors by normalized name and phone."""
    seen = set()
    result = []
    for vendor in vendors:
        name = (vendor.get("name") or "").strip()
        key = (name.lower(), (vendor.get("phone") or "").strip())
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(vendor)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Source local subcontractors/vendors for an opportunity + outreach script.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Known NAICS profiles:\n  "
        + "\n  ".join(f"{key}  {value['label']}" for key, value in VENDOR_PROFILES.items()),
    )
    parser.add_argument(
        "service",
        nargs="?",
        help='Free-text service (e.g. "tree removal"). Optional if --naics is a known profile.',
    )
    parser.add_argument("--naics", help="NAICS code (uses a known sourcing profile when available)")
    parser.add_argument(
        "--place",
        required=True,
        help='Place of performance to search near (e.g. "Dover, DE")',
    )
    parser.add_argument("--due", help='Response deadline for the call script (e.g. "19 Jun 2026")')
    parser.add_argument(
        "--operator",
        default=os.getenv("OPERATOR_NAME", "Jeremy"),
        help="Name to use in the call script",
    )
    parser.add_argument("--max", type=int, default=6, help="Max vendors to return (default: 6, cap 20)")
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Skip Places discovery and print the outreach material only",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of formatted text")
    return parser.parse_args()


def main() -> None:
    load_project_env()
    args = parse_args()
    try:
        package = generate_vendor_package(
            naics=args.naics,
            service=args.service,
            place=args.place,
            due=args.due,
            operator=args.operator,
            max_results=args.max,
            script_only=args.script_only,
        )
    except ValueError as exc:
        sys.exit(f"ERROR: {exc}")

    if args.json:
        print(json.dumps(package, indent=2, default=str))
        return

    vendors = package["vendors"]
    print(f"\nVendor sourcing: {package['service_label']}")
    print(f"Near: {args.place}" + (f"   Due: {args.due}" if args.due else ""))
    print(f"Queries: {'; '.join(package['queries'])}")
    if package["discovery_skipped"]:
        print("Discovery skipped: --script-only")
    print(f"Found: {len(vendors)} vendor(s)")
    print("=" * 80)
    if not vendors:
        print("\nNo vendors found. Try a broader --place or a different service term.\n")
    for index, vendor in enumerate(vendors, 1):
        rating = f"{vendor['rating']}* ({vendor['rating_count']})" if vendor.get("rating") else "-"
        print(f"\n[{index}] {vendor['name']}")
        print(f"    Phone:    {vendor.get('phone') or '-'}")
        print(f"    Address:  {vendor.get('address') or '-'}")
        print(f"    Website:  {vendor.get('website') or '-'}")
        print(f"    Rating:   {rating}")

    print("\n" + "=" * 80)
    print("CALL SCRIPT")
    print("=" * 80)
    print(package["call_script"])
    print("=" * 80)
    print("EMAIL ASK-LIST (send after they bite)")
    print("=" * 80)
    for ask in package["email_asks"]:
        print(f"  - {ask}")
    print("\n" + "=" * 80)
    print("FOLLOW-UP EMAIL DRAFT")
    print("=" * 80)
    print(package["email_draft"])
    print()


if __name__ == "__main__":
    main()
