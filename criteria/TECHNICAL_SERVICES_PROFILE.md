# Small-Team Field Installation Lead Profile

## Active Default

The operator's default opportunity research should target bounded field work
that an owner-led two-to-three-person crew can price, schedule, install, test,
and warranty. The first lane is security-camera and access-control
installation. Structured cabling and small fiber jobs are supporting lanes.

Do not treat a matching keyword or NAICS code as proof of fit. Inspect the
public scope, drawings, site-visit rules, licenses, insurance, response SLA,
equipment sourcing, and completion date before recommending a pursuit.

`criteria/ELASTIC_LEAD_PROFILE.md` remains available as a separate legacy
specialist lane. It is not the active default.

## Capability Lanes

### Tier 1 - Direct Field-Installation Fit

- Security-camera, CCTV, and video-surveillance installation, replacement, or
  upgrade work.
- Video-monitoring systems: cameras, NVRs, VMS workstations, displays, PoE
  components, cabling, testing, commissioning, and user handoff.
- Electronic access control: card readers, badge readers, door controllers,
  request-to-exit sensors, strikes, maglocks, small PACS upgrades, and related
  cabling.
- Structured data cabling: low-voltage copper, Cat5e/Cat6/Cat6A, patch panels,
  racks, drops, labeling, termination, certification testing, and as-builts.
- Bounded fiber runs: inside-plant or clearly scoped outside-plant pulls,
  termination, testing, and documentation.

### Tier 2 - Adjacent Fit

- Intrusion detection, alarm, intercom, and small electronic-security upgrades
  when licensing, code, and OEM dependencies are documented and executable.
- Small network, Wi-Fi, AV-over-IP, VTC, or unified-communications installs
  when physical installation, configuration, testing, and handoff are the core
  deliverables.
- Recurring maintenance for systems the operator can support within the
  required response time and geographic radius.

### Conditional Fits

- Fire-alarm, life-safety, electrical-power, and code-inspection work require
  explicit license and code-responsibility review before pursuit.
- Proprietary platforms such as LenelS2, Genetec, AMAG, Gallagher, Milestone,
  and manufacturer-specific alarm systems require documented authorized-
  installer, reseller, training, or partner routes when the notice requires
  them.
- Multi-site and out-of-area work require a realistic crew schedule, travel
  budget, material plan, and warranty-response plan.
- Product-heavy work is viable only when installation is material to the scope
  and sourcing, warranty, margin, and Section 889 restrictions are understood.

### Explicit-Request Home-Office Reseller Lane

When the operator explicitly asks for desk-based product sourcing, scan
commercial-product RFQs separately from the default field-installation digest.
Prefer one or a few standard products that a distributor can fulfill directly.
Verify dealer or reseller authorization, exact specifications, freight,
delivery acceptance, payment timing, cash-flow exposure, Buy American
requirements, and whether the nonmanufacturer rule applies. Do not promote
broad commodity results into the default field-installation scan.

## Discovery Vocabulary

Search lanes independently. Broad terms require document review.

| Lane | Terms |
| --- | --- |
| Cameras / video | `"security camera"`, `CCTV`, `"video surveillance"`, `"video monitoring"`, `camera installation`, `NVR`, `"video management system"`, `VMS` |
| Access control | `"access control"`, `"physical access control"`, `PACS`, `"card reader"`, `"badge reader"`, `CAC`, `PIN`, `REX`, `maglock`, `"door controller"` |
| Cabling | `"structured cabling"`, `"data cabling"`, `"network cabling"`, `"low voltage"`, `Cat6`, `Cat6A`, `"patch panel"`, `termination`, `"cable testing"` |
| Fiber | `"fiber optic"`, `"fiber-optic"`, `"inside plant"`, `ISP`, `"outside plant"`, `OSP`, splicing, OTDR |
| Adjacent systems | `"intrusion detection"`, `"alarm system"`, `intercom`, `Wi-Fi`, `"AV over IP"`, `VTC`, `"unified communications"` |

## NAICS Discovery Hints

NAICS codes are search-expansion hints, never proof of fit.

| NAICS | Candidate category |
| --- | --- |
| `561621` | Security Systems Services (except Locksmiths) |
| `238210` | Electrical contractors and other wiring installation contractors; filter for low-voltage, cabling, and fiber scope |
| `541512` | Computer systems design services; conditional for small integration work |
| `334290` | Other communications equipment manufacturing; discovery hint for equipment-heavy installs only |

## Set-Aside and Pursuit Rules

- Prioritize Total Small Business (`SBA`) opportunities.
- Do not claim eligibility for SDVOSB or another special status until the
  operator confirms certification.
- Treat Sources Sought and RFIs as pipeline/positioning opportunities, not
  current bids.
- Filter response deadlines against today's exact date in
  `America/New_York`; `active=Yes` alone is insufficient.
- Prefer one-site or tightly bounded work with a clear bill of materials,
  scheduled site access, and a realistic warranty radius.

## Default Exclusions

- Large construction programs, high-voltage electrical work, broad facility
  repair, unrelated trades, guard services, nationwide staffing, and 24/7
  operations.
- Closed, awarded, sole-source, notice-of-intent, draft, or inaccessible
  solicitations when searching for work to pursue now.
- Proprietary sustainment work without the required OEM route.
- Product resale without a meaningful installation component.
- Work where licensing, insurance, site access, material lead times, schedule,
  or warranty response cannot be met by the planned crew.

## Ranking

Rank only after checking current official public information and, for serious
candidates, retrieving a public requirements document.

| Score | Evidence |
| --- | --- |
| `+4` | Public notice or document explicitly defines a security-camera, video-monitoring, access-control, structured-cabling, or bounded fiber installation. |
| `+3` | Public document establishes a small adjacent installation, upgrade, testing, commissioning, or maintenance scope. |
| `+2` | Bounded field deliverable: install, terminate, test, commission, train, document, repair, or warranty task. |
| `+1` | Total Small Business set-aside, subject to confirming the bidding entity qualifies. |
| `+1` | Manageable response runway and plausibly executable one-site or tightly bounded scope. |
| `-3` | Product-only buy, proprietary sustainment without an OEM route, broad staffing/operations program, or weak keyword-only match. |
| `-5` | Unrelated construction/trade work, closed deadline, prohibited notice type, or a scope the planned crew cannot execute. |

## Required Evidence Review

For the strongest candidates, ingest a public SOW, PWS, specifications file,
requirements file, or amendment into Elasticsearch and retrieve evidence for:

- Site count, camera count, reader/door count, drop count, fiber length, and
  required drawings or as-builts.
- Hardware, software, VMS/PACS/OEM, sourcing, NDAA Section 889, reseller,
  warranty, and authorized-installer requirements.
- Cabling pathways, conduit, power, fire-alarm integration, code inspection,
  testing, commissioning, and training.
- License, technician registration, insurance, site access, past performance,
  and special certification requirements.
- Site visit, completion date, response deadline, set-aside, quote contents,
  and warranty-response SLA.

For each unproven requirement, write `not found in indexed document`.
