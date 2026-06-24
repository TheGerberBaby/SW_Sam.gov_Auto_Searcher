# Vendor Sourcing Profile

Fit and method rules for the **fulfillment lane**: sourcing local
subcontractors/vendors to perform an opportunity you intend to prime. This is
downstream of opportunity discovery and scoring. Implemented by
`scripts/source_vendors.py`.

## When to use this lane

Use it **after** you have decided an opportunity is worth priming and you need
performers, not to decide whether to bid. Inputs: the opportunity's NAICS, its
place of performance, the response deadline, and optionally a free-text service
description.

## Method

1. Resolve a sourcing profile from the NAICS table below. Unknown NAICS falls
   back to a generic profile driven by the free-text service.
2. Run each profile search term against Google Places API (New), scoped to the
   place of performance.
3. Exclude closed businesses, deduplicate by name and phone, and return name,
   phone, address, website, and rating.
4. Emit a cold-call script and an email ask-list.

## NAICS sourcing table

| NAICS | Performer type | Primary qualifier to confirm |
| --- | --- | --- |
| 561621 | Security systems / access-control installation | Camera, access-control, low-voltage, licensing, and OEM route |
| 238210 | Structured cabling / low-voltage installation | Cat6 and fiber installation, testing, and required licensing |
| 561790 | Kitchen hood and exhaust cleaning | IKECA certified with CECS on site |
| 562111 | Solid waste / trash collection | Runs a recurring route; spill and safety plan |
| 561720 | Janitorial / custodial | Recurring crew; background checks / badging |
| 561730 | Grounds maintenance / landscaping | Full scope on schedule; licensed and insured |
| 238220 | HVAC / mechanical | State-licensed mechanical contractor |

Add new rows in `VENDOR_PROFILES` in `scripts/source_vendors.py` and mirror them
here.

## Judgement rules

- This is a fulfillment tool, not a reason to pursue work outside the operator's
  capability profile. Use unrelated service profiles only after an opportunity
  is intentionally selected for a subcontracting route.
- Confirm coverage of the actual place or places of performance before trusting
  a local result. Multi-site or wide-geography requirements may need several
  regional subcontractors or a regional firm.
- Prefer performers under the NAICS small-business size standard. Their work may
  count differently toward Limitations on Subcontracting compliance depending
  on the procurement and similarly-situated-entity rules.
- Verify whether certifications, licenses, clearances, or OEM requirements must
  be held by the prime, the subcontractor, or both. Do not assume.
- Never claim a vendor holds a certification, license, clearance, size status,
  or submission eligibility without confirming it from source evidence.

## Output

For each call: vendor name, phone, website, and rating; one cold-call script;
and the email ask-list for scope quote, qualifications, references, payment
terms, and size status.
