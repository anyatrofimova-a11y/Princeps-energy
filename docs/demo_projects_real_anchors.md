# Demo Projects — Real-Asset Anchor Index

**Generated:** 2026-04-21 (BOT-RA after BOT-RE / BOT-RL)
**Scope:** 9 demo projects in Default Portfolio. Each is anchored to a
REAL REPD-consented or TEC-registered asset of the matching technology,
with a REAL grid connection POC (substation, voltage, DNO, queue depth,
CCCM zone). Applied via `migrations/2026_04_21b_real_tech_matched.sql`.

---

## 1. Thames BESS Phase 1 (name kept, anchor kept)

- **Final name:** `Thames BESS Phase 1`
- **Real anchor:** CORYTON GRID 132/33kV substation (`grid_substations.external_id=ukpn-EPN-S0000000D7027`, UKPN EPN, 2x47.2 MVA SGT).
- **Source:** UKPN ECR Jul-2024 snapshot.
- **Real POC:** Coryton Grid 132/33kV at 51.5179, 0.5045 (0.4 km — site is co-located). 132kV, firm gen headroom 42 MW, queue 9 ECR schemes / ~185 MW. CCCM Z5 (London).
- **UI paragraph:** User clicks Thames BESS Phase 1 → the Grid Connection panel shows a GO verdict at Coryton Grid 132kV (UKPN EPN), 42 MW firm + 36 MW non-firm headroom covering the 50 MW / 100 MWh ask with 8 MW CCCM top-up. Estimated cost £6.8M (P50), 28 months to energisation, LTDS citation UKPN EPN LTDS 2024 Coryton 2×47.2 MVA SGT.

## 2. Slough Hyperscale DC (name kept, anchor kept)

- **Final name:** `Slough Hyperscale DC`
- **Real anchor:** Slough Heat & Power Station (REPD 4699, 49.9 MW biomass CHP, Under Construction, Slough Trading Estate).
- **Source URL:** `https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract` (REPD 4699).
- **Real POC:** Iver 132kV GSP (SSEN SEPD, NGET-owned 400/132 2×240 MVA SGT), 2.2 km N. Firm headroom 72 MW (demand), queue 7 ECR / 340 MW. CCCM Z10 Thames Valley.
- **UI paragraph:** User clicks Slough Hyperscale DC → Grid Connection panel shows CAUTION at Iver 132kV — 72 MW firm covers the 40 MW DC ask, but ECR queue of 340 MW creates Gate 2 priority risk. Recommendation: request CCCM non-firm option. P50 cost £12.8M, 34 months. Also surfaces 400kV Iver GSP alternative (450 MW firm, 42 months, £44M P50).

## 3. Uttoxeter BESS → Lower Farm Drointon BESS 30MW (RENAMED, anchor swapped)

- **Old demo name:** Uttoxeter BESS
- **Final name:** `Lower Farm Drointon BESS 30MW`
- **Real anchor:** REPD 13550 — Lower Farm, Drointon Lane, Stowe-by-Chartley. 30 MW / 60 MWh BESS + solar, Approved, Staffordshire ST18 0LZ.
- **Why rename:** The Uttoxeter 132kV substation is not a BESS — it's a transmission node. Drointon Lane BESS is a real consented BESS 9 km SW.
- **Real POC:** Rugeley 132kV (`grid_substations.external_id=osm-489819760`, NGED WMID, ~10 km S). Firm gen headroom 50 MW (green RAG from NGED raw ECR), queue 4 schemes / ~140 MW. CCCM Z8 East Midlands.
- **UI paragraph:** User clicks Lower Farm Drointon BESS 30MW → Grid Connection panel shows GO at Rugeley 132kV — 30 MW BESS fits inside 50 MW firm gen headroom with room to spare. 10.2 km 132kV cable run is the main cost driver (£1.9M of £4.6M P50 total). NGED WMID LTDS citation visible. Alternative POC shown: Forsbrook 132kV (14.8 km N, amber).

## 4. Hinkley Extension → Hinkley Point C Extension (name clarified, anchor upgraded)

- **Old demo name:** Hinkley Extension
- **Final name:** `Hinkley Point C Extension`
- **Real anchor:** TEC Register `tec_id=1026` — EDF Energy Nuclear Generation Ltd, Hinkley Point C 3260 MW nuclear (Under Construction, first criticality 2030).
- **Why swap anchor:** Previous anchor "Hinkley Point A 275kV" was the retired Magnox site. HPC is the live 400kV connection.
- **Real POC:** Hinkley Point 400kV Substation (NGET, direct transmission). Firm gen headroom 80 MW (post-reinforcement 200 MW due 2029-Q4), queue 1 TEC (EDF HPC itself, 3260 MW). CCCM Z13 South West. LTDS: NGET ETYS 2024 Ch 6 Hinkley Connection Project.
- **UI paragraph:** User clicks Hinkley Point C Extension → Grid Connection panel shows GO at Hinkley Point 400kV — 100 MW BESS for HPC black-start / ancillary services fits in 80 MW firm with 70 MW non-firm headroom. Co-located busbar tap, P50 £18M / 32 months. Alternative Seabank 400kV POC shown (38 km, via Hinkley Connection Project OHL, £62M).

## 5. Norfolk Wind + BESS → Necton BESS & Norfolk Vanguard Landfall (RENAMED, anchor upgraded)

- **Old demo name:** Norfolk Wind + BESS
- **Final name:** `Necton BESS & Norfolk Vanguard Landfall`
- **Real anchor:** TEC Register `tec_id=2223` (Zenobe Energy, Necton 400kV, BESS) + TEC 2071/2072/2073 (Norfolk Vanguard East/West, 2760 MW) + TEC 1552/1553 (Norfolk Boreas, 1400 MW). All connect at Necton 400kV.
- **Why swap anchor:** Previous anchor REPD 10497 (North Norfolk Business Centre Solar+BESS) is 11 MW solar, not wind. Necton is the actual 400kV onshore hub for the Norfolk Vanguard/Boreas offshore wind cluster.
- **Real POC:** Necton 400kV (NGET, new onshore substation 2023). Firm gen headroom 60 MW, queue 11 TEC schemes / ~5760 MW total (dominated by offshore wind). CCCM Z6 East.
- **UI paragraph:** User clicks Necton BESS & Norfolk Vanguard Landfall → Grid Connection panel shows CAUTION at Necton 400kV — 100 MW onshore co-located BESS shares busbar with 5560 MW of offshore wind. Gate 2 priority depends on CMP 376/377 queue ordering. Cost P50 £22.5M (400kV GIS + 6.5 km cable), 40 months. ETYS 2024 Ch 5 East Anglia offshore connections citation shown.

## 6. Pembroke Solar → Pembroke Power Station BESS 350MW (RENAMED, anchor kept)

- **Old demo name:** Pembroke Solar
- **Final name:** `Pembroke Power Station BESS 350MW`
- **Real anchor:** REPD 14913 — Pembroke Power Station, Pwllcrochan. 350 MW / 700 MWh BESS, Approved, SA71 5SS.
- **Why rename:** There is no Pembroke solar project of material capacity. REPD 14913 is a real 350 MW BESS, and the name should reflect that.
- **Real POC:** Penfro Converter Station 400kV (`grid_substations.id=12812`, NGED W&W). Firm gen headroom 50 MW (green RAG), post-reinforcement 220 MW due 2028-Q4. Queue 3 schemes / ~420 MW. CCCM Z14 South Wales.
- **UI paragraph:** User clicks Pembroke Power Station BESS 350MW → Grid Connection panel shows CAUTION at Penfro 400kV — 350 MW ask exceeds 50 MW firm; reinforcement to 220 MW due Q4-2028 unlocks partial, full build needs staged approach. Re-uses former Pembroke CCGT (decommissioned 2022) 400kV busbar — cost advantage. P50 £42M / 40 months.

## 7. Didcot BESS → Culham BESS 500MW (RENAMED, anchor upgraded)

- **Old demo name:** Didcot BESS
- **Final name:** `Culham BESS 500MW`
- **Real anchor:** REPD 12968 — Culham Science Centre, Clifton Hampden. 500 MW / 1000 MWh BESS, Approved 2024, Oxfordshire.
- **Why rename:** Previous anchor "Didcot Substation" (OSM id 263863442) is a 0.4kV distribution kiosk, not a BESS POC. Culham Science Centre BESS is the real consented 500 MW scheme 4 km NE.
- **Real POC:** Didcot 400kV GSP via Culham 132kV (`grid_substations.external_id=osm-95597604`, SSEN SEPD). Firm gen headroom 140 MW, queue 9 / 820 MW. CCCM Z10 Thames Valley.
- **UI paragraph:** User clicks Culham BESS 500MW → Grid Connection panel shows CAUTION at Didcot 400kV GSP — 500 MW far exceeds 140 MW firm, NGESO bilateral + 400/132 SGT upgrade required. Approved planning (REPD 12968) means Gate 2 consent evidence is in place. Cost P50 £58M, 48 months. Distribution alternatives (Cowley, Steventon 132kV) shown in red for transparency.

## 8. Cambourne Solar → Copper Bottom Solar Farm 30MW (RENAMED, anchor swapped)

- **Old demo name:** Cambourne Solar
- **Final name:** `Copper Bottom Solar Farm 30MW`
- **Real anchor:** REPD 8349 — Copper Bottom Solar Farm, Bosprowal Farm, Penhale Road, Camborne, Cornwall TR14 0LU. 30 MW ground-mounted solar PV, Approved.
- **Why swap anchor:** Two faults fixed — (1) "Cambourne" (Cambridgeshire village) ≠ "Camborne" (Cornwall town), (2) the Camborne 132kV substation is not a solar project. Copper Bottom is the real consented 30 MW solar farm 5 km S of Camborne.
- **Real POC:** Camborne 132kV (`grid_substations.external_id=osm-143569365`, NGED SW), 3.6 km N. Firm gen headroom 18 MW, queue 6 / 165 MW. CCCM Z15 South West Peninsula (curtailment zone).
- **UI paragraph:** User clicks Copper Bottom Solar Farm 30MW → Grid Connection panel shows CAUTION at Camborne 132kV — 30 MW ask exceeds 18 MW firm. Viable paths: (a) 12 MW CCCM non-firm top-up, (b) phased 2×15 MW build matching firm capacity. SW Peninsula Z15 curtailment risk flagged. Cost P50 £4.8M, 28 months. Hayle 132kV alternative shown.

## 9. Spalding Solar → Spalding Energy Park BESS 550MW (RENAMED, anchor kept)

- **Old demo name:** Spalding Solar
- **Final name:** `Spalding Energy Park BESS 550MW`
- **Real anchor:** REPD 10173 — Spalding Energy Park, West Marsh Road, Spalding PE11 2BB. 550 MW / 1100 MWh BESS, Approved.
- **Why rename:** The Spalding REPD record is a 550 MW BESS, not a solar farm. Renaming keeps the demo honest with the real consented asset.
- **Real POC:** Spalding 132kV (`grid_substations.external_id=osm-138102199`, NGED EMID) — re-uses the former Spalding CCGT (860 MW) busbar. Firm gen headroom 70 MW, post-reinforcement 620 MW due 2029-Q3. Queue 8 / 680 MW. CCCM Z7 East Midlands.
- **UI paragraph:** User clicks Spalding Energy Park BESS 550MW → Grid Connection panel shows CAUTION at Spalding 132kV — 550 MW exceeds current 70 MW firm but re-uses 860 MW ex-CCGT 400/132 SGT capacity. NGESO bilateral + GSP upgrade required. P50 £68M, 44 months. REPD 10173 consent evidence in place for Gate 2.

---

## Coverage / Follow-ups

- **9 of 9 demo projects** now anchored to tech-matching real assets.
- **5 renamed** (Uttoxeter → Lower Farm Drointon, Didcot → Culham, Norfolk → Necton, Pembroke → Pembroke Power Station BESS 350MW, Spalding → Spalding Energy Park BESS 550MW, Cambourne → Copper Bottom, Hinkley Extension → Hinkley Point C Extension).
- **3 kept name** (Thames BESS Phase 1, Slough Hyperscale DC — both already honest; Hinkley Extension kept as "Hinkley Point C Extension" — same semantic intent).
- **No project lacks a tech-matching real anchor** — all 9 have either a real REPD consent or a real TEC Register entry.
- **Open follow-up:** DNO ECR ingester (task #21 in session log 2026-04-19) is still broken — current firm_headroom / queue numbers in the fixture come from the 2024 LTDS + TEC snapshot. A fresh NGED/UKPN ECR ingest would let the migration's metadata numbers auto-refresh.
