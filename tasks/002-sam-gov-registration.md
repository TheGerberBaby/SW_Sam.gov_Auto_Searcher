---
id: 002-sam-gov-registration
title: Active SAM.gov entity registration with UEI
status: held
priority: high
effort: M
type: registration
dependencies: [001-entity-formation]
tags: [foundation, sam, federal, prerequisite]
owner: jeremy
created: 2026-05-29
updated: 2026-06-17
---

## Why this matters

- Required prerequisite for VetCert/SDVOSB (see [003-sdvosb-vetcert](003-sdvosb-vetcert.md)).
- Required to be eligible for any federal award.
- The Unique Entity Identifier (UEI) replaces DUNS.

## Confirm with Jeremy

- [x] Entity registered at <https://sam.gov>?
- [x] UEI obtained?
- [x] CAGE code obtained?
- [x] Status `Active` (not `Submitted` / `Work in Progress` / `Inactive`)?
- [x] NAICS codes claimed include 541512?
- [ ] Reps & Certs filled?
- [ ] FAR/DFARS clauses reviewed at registration time?

SAM.gov registrations expire annually — re-verify renewal date if
the status is `done`.

## Authoritative references

- SAM.gov registration: <https://sam.gov/content/entity-registration>
- UEI guide: <https://www.gsa.gov/about-us/organization/federal-acquisition-service/office-of-systems-management/integrated-award-environment-iae/iae-systems-information-kit/uei-update>

## Notes

- Confirmed 2026-05-31: UEI `LE4ZH9KC7BU1`; CAGE `1ZW38`.
- Confirmed 2026-06-17 in SAM.gov Entity Workspace: registration status is
  `Active`, activation date is May 5, 2026, expiration date is Apr 25, 2027,
  purpose of registration is `All Awards`, and SAM public search authorization
  is `Yes`.
- Confirmed 2026-06-17 in SBA Small Business Search public profile endpoint:
  `public_display` is `true` and `public_display_limited` is `false`.
- Capability narrative draft for SAM/SBA public profile:
  Stormwind Contracting is a service-disabled veteran-owned small business
  focused on small-team field installation work for security, access-control,
  and low-voltage environments. Core services include CCTV and video-monitoring
  installation, electronic access-control hardware support, structured Cat6
  cabling, low-voltage data cabling, patch-panel work, bounded fiber runs,
  basic network handoff, site documentation, and closeout support. Near-term
  prime work is targeted at bounded DMV-area projects that a two-to-three-person
  crew can execute with clear site access, licensing, equipment, and warranty
  obligations.
- Suggested public keywords:
  CCTV, security cameras, video surveillance, video monitoring, access control,
  card readers, door access, low voltage, structured cabling, Cat6, data cabling,
  patch panels, fiber, network installation, site survey, DMV, SDVOSB.
- Follow-up cleanup: paste and verify the capability narrative/keywords in the
  SBA/SAM public profile, and update the registered NAICS set from the current
  IT-focused codes (`541511`, `541512`, `541519`, `541690`) toward the current
  field-installation profile's target NAICS set.
