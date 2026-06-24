# Prime-With-Subcontractor Opportunity Profile

This optional lane finds opportunities where Stormwind would bid as the prime
contractor and source a qualified first-tier small-business subcontractor for
field performance. It is separate from the default owner-led field-installation
profile.

Implemented by:

```powershell
python .\scripts\swcb.py subcontract-leads
```

After selecting an opportunity for review, source performer candidates with:

```powershell
python .\scripts\swcb.py vendors --naics 561720 --place "Alexandria, VA" --due "29 Jun 2026"
```

## Guardrail

This is not a pass-through model. The prime contractor works directly with the
Government, manages subcontractors, and remains responsible for performance.
Before bidding, verify the solicitation, clauses, scope, margin, cash flow,
licenses, insurance, site access, and the proposed subcontractor.

For Total Small Business set-asides, FAR 52.219-14 defines a similarly situated
entity as a first-tier subcontractor that has the same small-business program
status that qualified the prime and is small under the NAICS code assigned to
the subcontract. For a regular small-business set-aside, the subcontractor must
be small under that subcontract NAICS. Special-status set-asides require the
matching special status. The clause limits payments to subcontractors that are
not similarly situated when it applies.

Official references:

- [FAR 52.219-14, Limitations on Subcontracting](https://www.acquisition.gov/far/52.219-14)
- [FAR 19.507(e), clause insertion rules](https://www.acquisition.gov/far/19.507)
- [SBA: Prime and subcontracting](https://www.sba.gov/federal-contracting/contracting-guide/prime-subcontracting)
- [SBA: Set-aside procurement](https://www.sba.gov/partners/contracting-officials/small-business-procurement/set-aside-procurement)

## Search Lanes

The selector uses only NAICS codes that have deterministic vendor-sourcing
profiles in `scripts/source_vendors.py`.

| NAICS | Performer lane | Default posture |
| --- | --- | --- |
| `561720` | Janitorial / custodial | Sourceable recurring service |
| `561730` | Grounds maintenance / landscaping | Sourceable recurring service |
| `561790` | Kitchen hood and exhaust cleaning | Sourceable after certification check |
| `562111` | Solid waste / trash collection | Sourceable after route and safety-plan check |
| `561621` | Security systems / access-control installation | Conditional: license, OEM, warranty, and access review |
| `238210` | Structured cabling / low-voltage installation | Conditional: license, testing, and site-scope review |
| `238220` | HVAC / mechanical service | Conditional: mechanical license, code, and construction-scope review |

## Hard Gates

- Active direct-buy notice: `Combined Synopsis/Solicitation` or `Solicitation`.
- Response deadline has at least three days of runway.
- Domestic place of performance.
- No award record.
- Set-aside is Total Small Business (`SBA`), Partial Small Business (`SBP`),
  unrestricted (`NONE`), or blank. Special-status set-asides are excluded until
  eligibility is confirmed.
- NAICS exists in the deterministic vendor-sourcing table.
- Notice text matches the service vocabulary for that sourcing profile. A broad
  NAICS match alone is rejected because codes such as `561790` and `562111`
  contain unrelated services.

## Manual Review

The selector flags text signals for life safety, construction, OEM systems,
licensing, multi-site work, response SLAs, special access, and hazardous
materials. A missing flag does not prove the requirement is absent. Review the
current notice and attachments before bidding.
