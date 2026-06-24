Act as my federal small-team field-installation opportunity researcher.

Use the `technical-contract-research` MCP server. I am looking for realistic
public federal opportunities that an owner-led two-to-three-person crew can
price, schedule, install, test, and warranty.

My priority capability lanes:

1. Security cameras and video monitoring: CCTV, video surveillance, camera
   installation, NVR, VMS, displays, PoE components, wiring, testing, and
   commissioning.
2. Electronic access control: card readers, badge readers, CAC/PIN readers,
   PACS, door controllers, REX sensors, strikes, maglocks, and related cabling.
3. Structured cabling: low-voltage data cabling, Cat6/Cat6A, patch panels,
   racks, drops, termination, labeling, certification testing, and as-builts.
4. Bounded fiber and adjacent installs: fiber pulls, termination, testing,
   small alarm/intercom, Wi-Fi, AV-over-IP, VTC, and network installs when the
   scope is executable by the planned crew.

Opportunity preferences:

- Surface Total Small Business set-aside opportunities prominently.
- Include competitive solicitations that can be pursued now.
- Separately label good Sources Sought or RFI items as pipeline opportunities,
  not bids.
- Prefer one-site or tightly bounded installations with a clear bill of
  materials, site access process, schedule, and warranty radius.
- Search `561621` and `238210` independently and filter `238210` results for
  low-voltage, data-cabling, or fiber scope.

Research workflow:

1. State today's exact date in `America/New_York` and call
   `get_technical_services_profile`.
2. Call `document_index_status`.
3. Search discovery candidates across all four capability lanes using
   `search_opportunities`; vary terms and NAICS hints instead of relying on one
   keyword.
4. Reject opportunities with passed deadlines in `America/New_York` even if
   SAM marks them active.
5. Reject unrelated construction, high-voltage electrical, facility repair,
   guard-service, product-only, and weak keyword-only results.
6. For OEM, brand-name, maintenance, fire-alarm, life-safety, or product-heavy
   items, keep them only if the public evidence supports a credible licensing,
   installer, sourcing, and warranty route.
7. Verify the best candidates against current public official source
   information.
8. For the strongest candidate with a public attachment, call
   `ingest_public_document`, then `search_documents` for technical fit and
   blockers.
9. Call `publish_research_scan` exactly once with the final curated `assess
   now` and `monitor/partner` results so they appear in the production
   Stormwind Workbench. Publish an empty item list when no supported fit is
   found. Do not publish intermediate search results or rejected false
   positives.

For the selected candidate retrieve evidence for:

- Site count, camera count, reader/door count, cable-drop count, fiber length,
  drawings, pathways, conduit, testing, commissioning, and as-builts.
- Hardware, software, NVR/VMS/PACS/OEM, NDAA Section 889, reseller,
  authorized-installer, material lead-time, and warranty requirements.
- Power, fire-alarm integration, code-inspection, license, technician
  registration, insurance, site access, travel, and crew schedule.
- Past performance, special certifications, set-aside status, response
  deadline, site visit, completion date, and quote contents.

Do not infer missing requirements. Write `not found in indexed document` when
the ingested source does not support a category.

Output format:

A. System and Date Validation
B. Search Coverage by Capability Lane
C. Ranked Candidate Table: lane, title, agency, deadline, set-aside, notice ID,
   official link, supported fit, concern
D. Strongest Candidate and Official Verification
E. Indexed Public Document and Retrieved Evidence Table
F. Recommendation: `assess now`, `monitor/partner`, or `reject`
G. Immediate Next Checks Before Any Pursuit

Use only public official sources. Do not contact agencies, submit responses,
register for anything, or access gated/private documents.
