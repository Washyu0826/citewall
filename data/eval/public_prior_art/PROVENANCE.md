# Public prior-art retrieval eval set (Q39)

Built 2026-09-25 by `scripts/build_public_eval_set.py --source freepatentsonline`.

| | |
|---|---|
| queries | 36 (claim 1 of a granted US patent, priority before 2016) |
| relevant labels | 354 — References Cited on the face of the granted US patent (considered by the USPTO examiner: examiner-cited + applicant IDS), via FreePatentsOnline |
| corpus | 340 documents (title + abstract + claim 1) |
| topics | `battery_cooling` ('"battery module" cooling plate coolant channel'), `ev_charging` ('electric vehicle charging station connector cable'), `heat_sink` ('heat sink fins power semiconductor module'), `fmcw_lidar` ('frequency modulated continuous wave lidar'), `touch_sensor` ('capacitive touch panel sensing electrode'), `wireless_power` ('wireless power transfer coil resonant') |

## How it was built
1. For each topic, a public full-text search returns ~40 granted US patents.
2. A result becomes a **query** when it has at least 2 cited US references we
   could fetch; its claim 1 is the query text and those references are the
   relevant set. Up to 8 queries per topic.
3. The **corpus** is every query's cited references plus the other same-topic
   search results (hard negatives; likely family members of a query — same
   title — are dropped). The query patent itself is never in the corpus.

## Caveats
- Ground truth is what the examiner cited/considered, which is incomplete:
  a relevant but un-cited document counts as a miss, so absolute scores are a
  lower bound. Use the set to COMPARE configurations (scripts/eval_retrieval_ab.py).
- English-only (US). A zh-TW set needs TIPO data with examiner citations
  (not available through a public API as of this build).
- Public patent documents; only bibliographic data, abstract and claim 1 are
  stored. No personal data beyond inventor/assignee names printed on patents
  (not stored here).
