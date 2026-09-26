"""Build the PUBLIC prior-art retrieval eval set (Q39) from Google Patents.

Why this exists
---------------
The old eval (data/eval/retrieval_eval_set.json) indexed 7 demo patents and
asked queries paraphrased FROM those patents — circular: a gibberish query
scored higher recall than a real one on the mock embedder. This builder makes
a set whose ground truth nobody on the team wrote:

    query     = claim 1 of a granted US patent (the "application under exam")
    relevant  = the references the USPTO EXAMINER cited against it
                (Google Patents marks them "* Cited by examiner")
    corpus    = every examiner-cited reference of every query  +  the other
                same-topic search results (hard negatives from the same field)

So each query competes against hundreds of same-field documents, most of which
are some OTHER query's prior art. Examiner citations are incomplete (an
un-cited but relevant document counts as a miss), so absolute numbers are a
lower bound — but they are comparable across backends, which is what the
A/B (Q9) needs.

Source / licence: public patent documents fetched from patents.google.com
(no API key). Only bibliographic data, abstract and the first claim are kept.

Usage::

    python scripts/build_public_eval_set.py            # fetch + write
    python scripts/build_public_eval_set.py --max-per-topic 6 --sleep 0.5

Output (committed, so CI never needs network):
    data/eval/public_prior_art/corpus.jsonl
    data/eval/public_prior_art/queries.json
    data/eval/public_prior_art/PROVENANCE.md
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "eval" / "public_prior_art"
UA = "Mozilla/5.0 (PatentMind eval-set builder; research use)"

# Topic clusters: several queries per field so the corpus is full of
# same-field hard negatives (other queries' prior art).
TOPICS: dict[str, str] = {
    "battery_cooling": '"battery module" cooling plate coolant channel',
    "ev_charging": "electric vehicle charging station connector cable",
    "heat_sink": "heat sink fins power semiconductor module",
    "fmcw_lidar": "frequency modulated continuous wave lidar",
    "touch_sensor": "capacitive touch panel sensing electrode",
    "wireless_power": "wireless power transfer coil resonant",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(fragment: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", fragment))).strip()


class Fetcher:
    def __init__(self, cache_dir: Path, sleep: float):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sleep = sleep

    @staticmethod
    def _fetch(url: str) -> str:
        """One GET. Prefers the curl binary: some patent sites reset Python's
        TLS client far more often than curl's. Raises HTTPError / OSError."""
        curl = shutil.which("curl")
        if curl:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [curl, "-s", "-m", "40", "-A", UA, "-w", "\n%{http_code}", url],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0:
                raise OSError(f"curl exit {proc.returncode}")
            raw, _, code = proc.stdout.rpartition(b"\n")
            status = int(code or 0)
            if status != 200:
                raise urllib.error.HTTPError(url, status, "HTTP error", None, None)
            return raw.decode("utf-8", errors="replace")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")

    def get(self, url: str) -> str | None:
        key = re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:]
        path = self.cache_dir / key
        if path.exists():
            return path.read_text(encoding="utf-8")
        for attempt in range(6):
            try:
                body = self._fetch(url)
                path.write_text(body, encoding="utf-8")
                time.sleep(self.sleep)
                return body
            except urllib.error.HTTPError as exc:
                print(f"  HTTP {exc.code} ({attempt + 1}/6) {url}", file=sys.stderr, flush=True)
                if exc.code in (429, 503):
                    # Throttled (Google's "Sorry…" page): back off hard.
                    time.sleep(30 * 2 ** min(attempt, 3))
                elif exc.code == 404:
                    return None
                else:
                    time.sleep(3)
            except Exception as exc:  # noqa: BLE001 — connection reset / timeout
                print(f"  fetch failed ({attempt + 1}/6) {url}: {exc}", file=sys.stderr, flush=True)
                time.sleep(2 + attempt * 2)
        return None


def search(fetcher: Fetcher, q: str, n: int = 40) -> list[str]:
    inner = urllib.parse.urlencode(
        {"q": q, "country": "US", "type": "PATENT", "before": "priority:20160101", "num": n},
        safe=":",
    )
    url = "https://patents.google.com/xhr/query?" + urllib.parse.urlencode(
        {"url": inner, "exp": ""}
    )
    body = fetcher.get(url)
    if not body:
        return []
    data = json.loads(body)
    out = []
    for cluster in data.get("results", {}).get("cluster", []):
        for r in cluster.get("result", []):
            pn = r.get("patent", {}).get("publication_number")
            if pn:
                out.append(pn)
    return out


def parse_patent(page: str, pub_no: str) -> dict | None:
    m = re.search(r'<meta name="DC\.title" content="([^"]*)"', page)
    title = html.unescape(m.group(1)).strip() if m else ""
    m = re.search(r"<abstract[^>]*>(.*?)</abstract>", page, re.S)
    abstract = _clean(m.group(1)) if m else ""
    # First claim: Google wraps each claim in <div class="claim" ...>.
    m = re.search(r'<div[^>]*class="claim"[^>]*>(.*?)</div>\s*</div>', page, re.S)
    claim1 = _clean(m.group(1)) if m else ""
    claim1 = re.sub(r"^1\s*\.\s*", "", claim1)
    m = re.search(r'<meta name="DC\.date" content="([^"]*)"', page)
    pub_date = m.group(1)[:10] if m else ""
    if not (title and (abstract or claim1)):
        return None
    return {
        "patent_no": pub_no,
        "title": title,
        "abstract": abstract,
        "claim1": claim1[:4000],
        "pub_date": pub_date,
    }


def examiner_cited(page: str) -> list[str]:
    """US publication numbers the examiner cited (backward references with '*')."""
    out = []
    for row in re.findall(r'<tr itemprop="backwardReferences".*?</tr>', page, re.S):
        if 'itemprop="examinerCited">*' not in row:
            continue
        m = re.search(r'itemprop="publicationNumber">([^<]+)<', row)
        if m and m.group(1).startswith("US"):
            out.append(m.group(1).strip())
    return out


def page_url(pub_no: str) -> str:
    return f"https://patents.google.com/patent/{pub_no}/en"


class GoogleSource:
    """patents.google.com — examiner-cited flag available ('*')."""

    name = "google"
    ground_truth = "USPTO examiner-cited references (Google Patents '* Cited by examiner')"

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher

    def search(self, q: str) -> list[str]:
        return search(self.f, q)

    def page(self, pub_no: str) -> str | None:
        return self.f.get(page_url(pub_no))

    parse = staticmethod(parse_patent)
    cited = staticmethod(examiner_cited)
    url = staticmethod(page_url)


# --- FreePatentsOnline fallback (Google throttles scrapers with a "Sorry…"
# page). FPO lists the "References Cited" printed on the patent's face — the
# art the examiner CONSIDERED (examiner-cited + applicant IDS), without the
# per-reference examiner flag. Still examiner-side ground truth nobody on the
# team wrote, but a looser one; PROVENANCE.md records which source was used.
_FPO = "https://www.freepatentsonline.com"


def _fpo_id_to_path(pub_no: str) -> str:
    num = pub_no[2:]
    if len(num) == 11:  # pre-grant publication yyyynnnnnnn
        return f"/y{num[:4]}/{num[4:]}.html"
    return f"/{num}.html"


def _fpo_block(page: str, label: str) -> str:
    m = re.search(
        r'<div class="disp_elm_title">' + re.escape(label) + r"</div>\s*"
        r'<div class="disp_elm_text"[^>]*>(.*?)</div>\s*</div>',
        page,
        re.S,
    )
    return m.group(1) if m else ""


class FpoSource:
    name = "freepatentsonline"
    ground_truth = (
        "References Cited on the face of the granted US patent (considered by the "
        "USPTO examiner: examiner-cited + applicant IDS), via FreePatentsOnline"
    )

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher

    def search(self, q: str) -> list[str]:
        url = f"{_FPO}/result.html?" + urllib.parse.urlencode(
            {"sort": "relevance", "srch": "top", "query_txt": q, "submit": "", "patents_us": "on"}
        )
        body = self.f.get(url) or ""
        out = []
        for num in re.findall(r'href="/(\d{7,8})\.html"', body):
            # Granted before ~2018 so the examiner's citations are settled.
            if 6_000_000 <= int(num) <= 10_000_000 and f"US{num}" not in out:
                out.append(f"US{num}")
        return out

    def page(self, pub_no: str) -> str | None:
        return self.f.get(_FPO + _fpo_id_to_path(pub_no))

    @staticmethod
    def url(pub_no: str) -> str:
        return _FPO + _fpo_id_to_path(pub_no)

    @staticmethod
    def parse(page: str, pub_no: str) -> dict | None:
        title = _clean(_fpo_block(page, "Title:"))
        abstract = _clean(_fpo_block(page, "Abstract:"))
        claims_html = _fpo_block(page, "Claims:")
        m = re.search(r"<claim-text>(.*?)</claim-text>", claims_html, re.S)
        claim1 = _clean(m.group(1)) if m else ""
        if not claim1:
            txt = _clean(claims_html)
            m = re.search(r"(?:^|\s)1\s*\.\s*(.*?)(?:\s2\s*\.\s|$)", txt)
            claim1 = m.group(1) if m else ""
        pub = _clean(_fpo_block(page, "Publication Date:"))
        mm = re.match(r"(\d{2})/(\d{2})/(\d{4})", pub)
        pub_date = f"{mm.group(3)}-{mm.group(1)}-{mm.group(2)}" if mm else ""
        if not (title and (abstract or claim1)):
            return None
        return {
            "patent_no": pub_no,
            "title": title,
            "abstract": abstract,
            "claim1": claim1[:4000],
            "pub_date": pub_date,
        }

    @staticmethod
    def cited(page: str) -> list[str]:
        block = _fpo_block(page, "US Patent References:")
        out = []
        for num in re.findall(r"<tr><td>(\d{7,11})</td>", block):
            out.append(f"US{num}")
        return out


def build(max_per_topic: int, sleep: float, cache_dir: Path, source: str = "google") -> None:
    f = Fetcher(cache_dir, sleep)
    src = GoogleSource(f) if source == "google" else FpoSource(f)
    corpus: dict[str, dict] = {}
    queries: list[dict] = []
    negatives: dict[str, list[str]] = {}

    for topic, q in TOPICS.items():
        print(f"[{topic}] search: {q}")
        results = src.search(q)
        negatives[topic] = []
        n_targets = 0
        for pn in results:
            if n_targets >= max_per_topic:
                negatives[topic].append(pn)
                continue
            page = src.page(pn)
            if not page:
                continue
            doc = src.parse(page, pn)
            cited = src.cited(page)
            if not doc or not doc["claim1"] or len(cited) < 2:
                negatives[topic].append(pn)
                continue
            found = []
            for ref in cited[:12]:
                if ref not in corpus:
                    rpage = src.page(ref)
                    rdoc = src.parse(rpage, ref) if rpage else None
                    if not rdoc:
                        continue
                    rdoc["topic"] = topic
                    corpus[ref] = rdoc
                found.append(ref)
            if len(found) < 2:
                negatives[topic].append(pn)
                continue
            n_targets += 1
            queries.append(
                {
                    "id": f"{topic}-{pn}",
                    "topic": topic,
                    "target_patent_no": pn,
                    "target_title": doc["title"],
                    "query": doc["claim1"],
                    "relevant": found,
                    "source": src.url(pn),
                }
            )
            print(f"  + {pn}: {len(found)} cited refs", flush=True)

    targets = {qq["target_patent_no"] for qq in queries}
    target_titles = {qq["target_title"].lower() for qq in queries}
    for topic, pns in negatives.items():
        for pn in pns:
            if pn in corpus or pn in targets:
                continue
            page = src.page(pn)
            doc = src.parse(page, pn) if page else None
            # Drop likely family members of a target (same title) — they would
            # be "relevant but unlabeled" and unfairly punish every backend.
            if not doc or doc["title"].lower() in target_titles:
                continue
            doc["topic"] = topic
            corpus[pn] = doc

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "corpus.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for pn in sorted(corpus):
            fh.write(json.dumps(corpus[pn], ensure_ascii=False) + "\n")
    (OUT_DIR / "queries.json").write_text(
        json.dumps(
            {
                "_README": (
                    "query = claim 1 of a granted US patent; relevant = "
                    f"{src.ground_truth}. See PROVENANCE.md."
                ),
                "source": src.name,
                "ground_truth": src.ground_truth,
                "built": date.today().isoformat(),
                "queries": queries,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    topics = ", ".join(f"`{t}` ({q!r})" for t, q in TOPICS.items())
    n_rel = sum(len(qq["relevant"]) for qq in queries)
    (OUT_DIR / "PROVENANCE.md").write_text(
        f"""# Public prior-art retrieval eval set (Q39)

Built {date.today().isoformat()} by `scripts/build_public_eval_set.py --source {src.name}`.

| | |
|---|---|
| queries | {len(queries)} (claim 1 of a granted US patent, priority before 2016) |
| relevant labels | {n_rel} — {src.ground_truth} |
| corpus | {len(corpus)} documents (title + abstract + claim 1) |
| topics | {topics} |

## How it was built
1. For each topic, a public full-text search returns ~40 granted US patents.
2. A result becomes a **query** when it has at least 2 cited US references we
   could fetch; its claim 1 is the query text and those references are the
   relevant set. Up to {max_per_topic} queries per topic.
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
""",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(queries)} queries, {len(corpus)} corpus docs → {OUT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-per-topic", type=int, default=6)
    ap.add_argument("--source", choices=["google", "fpo"], default="google")
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "patentmind-eval-cache",
        help="raw HTML cache (re-runs are offline once warm)",
    )
    a = ap.parse_args()
    build(a.max_per_topic, a.sleep, a.cache_dir, a.source)


if __name__ == "__main__":
    main()
