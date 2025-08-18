#!/usr/bin/env python3
"""
build_publications_patched.py

Queries PubMed (E-utilities) using terms from a JSON config and updates an existing
`publications.html` by replacing the block between:
  <!-- PUBLIST:START --> ... <!-- PUBLIST:END -->

It also refreshes the "Updated automatically from PubMed: <timestamp>" pill if present.

Config (JSON), example:
{
  "queries": [
    {"term": "Angers S[Author] AND (1999:3000[DP])"}
  ],
  "retmax": 200
}

Usage examples:
  # write only the fragment html
  python3 scripts/build_publications_patched.py --config scripts/pubmed_config.json --mode fragment --output pubs.html

  # inject the fragment into publications.html (recommended)
  python3 scripts/build_publications_patched.py --config scripts/pubmed_config.json --mode inject --target publications.html
"""
import argparse
import json
import sys
import time
import re
from pathlib import Path
import datetime as dt
from urllib.parse import urlencode
from urllib.request import urlopen

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def esearch(term: str, retmax: int = 200) -> list[str]:
    """Return a list of PMIDs (strings) for a given term."""
    params = {
        "db": "pubmed",
        "term": term,
        "retmax": str(retmax),
        "retmode": "json",
        "sort": "pub date",
    }
    url = f"{EUTILS_BASE}/esearch.fcgi?{urlencode(params)}"
    with urlopen(url) as r:
        data = json.loads(r.read().decode("utf-8"))
    ids = data.get("esearchresult", {}).get("idlist", [])
    return [str(x) for x in ids]

def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def esummary(pmids: list[str]) -> list[dict]:
    """Return ESummary records for given PMIDs."""
    out = []
    for batch in chunked(pmids, 200):
        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "json"
        }
        url = f"{EUTILS_BASE}/esummary.fcgi?{urlencode(params)}"
        with urlopen(url) as r:
            data = json.loads(r.read().decode("utf-8"))
        uids = data.get("result", {}).get("uids", [])
        for uid in uids:
            rec = data["result"].get(uid)
            if rec:
                out.append(rec)
        time.sleep(0.34)  # be polite
    return out

def normalize_record(rec: dict) -> dict:
    """Map ESummary -> normalized fields used for rendering & search."""
    title = (rec.get("title") or "").strip().rstrip(".")
    journal = (rec.get("fulljournalname") or rec.get("source") or "").strip()
    pubdate = rec.get("pubdate") or ""
    # Year parsing (pubdate could be "2023 Aug 14" or "2021 Winter" etc.)
    m = re.search(r"(19|20)\d{2}", pubdate)
    year = int(m.group(0)) if m else 0
    authors = []
    for a in rec.get("authors", []):
        name = a.get("name") or ""
        if name:
            authors.append(name)
    doi = ""
    for idobj in rec.get("articleids", []):
        if idobj.get("idtype") == "doi":
            doi = idobj.get("value", "")
            break
    pmid = rec.get("uid") or ""
    # Build search text
    search_text = " ".join([title, journal, pubdate, " ".join(authors), doi, pmid]).lower()
    return {
        "title": title,
        "journal": journal,
        "year": year,
        "pubdate": pubdate,
        "authors": authors,
        "doi": doi,
        "pmid": pmid,
        "search_text": search_text
    }

def group_by_year(records: list[dict]) -> dict[int, list[dict]]:
    by = {}
    for r in records:
        by.setdefault(r["year"], []).append(r)
    # sort records within a year by pubdate desc-ish (fall back to title)
    for y in list(by.keys()):
        by[y].sort(key=lambda r: (r.get("pubdate") or "", r.get("title") or ""), reverse=True)
    return dict(sorted(by.items(), key=lambda kv: kv[0], reverse=True))

def render_fragment(records_by_year: dict[int, list[dict]]) -> str:
    parts = []
    for year, recs in records_by_year.items():
        if year == 0:
            # Put undated at the end
            continue
        parts.append(f'<section class="year-block" data-year="{year}">')
        parts.append(f'  <h2 class="year">{year}</h2>')
        parts.append('  <ol class="pubs">')
        for r in recs:
            authors = ", ".join(r["authors"])
            title = r["title"]
            journal = r["journal"]
            doi_html = f'<a href="https://doi.org/{r["doi"]}" target="_blank" rel="noopener">DOI</a>' if r["doi"] else ""
            pmid_html = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{r["pmid"]}/" target="_blank" rel="noopener">PMID:{r["pmid"]}</a>' if r["pmid"] else ""
            links = " · ".join([x for x in (doi_html, pmid_html) if x])
            parts.append(
                '    <li class="pub" data-search="{search}">'
                '      <div class="meta">{authors}</div>'
                '      <div class="title">{title}</div>'
                '      <div class="journal">{journal}</div>'
                '      <div class="links">{links}</div>'
                '    </li>'.format(
                    search=r["search_text"].replace('"', "&quot;"),
                    authors=authors,
                    title=title,
                    journal=journal,
                    links=links or ""
                )
            )
        parts.append('  </ol>')
        parts.append('</section>')
    # add undated (year == 0) at the end if any
    if any(y == 0 for y in records_by_year.keys()):
        recs = records_by_year.get(0, [])
        if recs:
            parts.append(f'<section class="year-block" data-year="undated">')
            parts.append(f'  <h2 class="year">Undated</h2>')
            parts.append('  <ol class="pubs">')
            for r in recs:
                authors = ", ".join(r["authors"])
                title = r["title"]
                journal = r["journal"]
                pmid_html = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{r["pmid"]}/" target="_blank" rel="noopener">PMID:{r["pmid"]}</a>' if r["pmid"] else ""
                parts.append(
                    '    <li class="pub" data-search="{search}">'
                    '      <div class="meta">{authors}</div>'
                    '      <div class="title">{title}</div>'
                    '      <div class="journal">{journal}</div>'
                    '      <div class="links">{links}</div>'
                    '    </li>'.format(
                        search=r["search_text"].replace('"', "&quot;"),
                        authors=authors,
                        title=title,
                        journal=journal,
                        links=pmid_html or ""
                    )
                )
            parts.append('  </ol>')
            parts.append('</section>')
    return "\n".join(parts)

def inject_into_file(target_path: str, inner_html: str):
    p = Path(target_path)
    if not p.exists():
        raise FileNotFoundError(f"{target_path} not found.")
    html = p.read_text(encoding="utf-8")
    start = "<!-- PUBLIST:START -->"
    end = "<!-- PUBLIST:END -->"
    if start not in html or end not in html:
        raise RuntimeError("Markers <!-- PUBLIST:START --> / <!-- PUBLIST:END --> not found in target HTML.")

    before, mid, after = html.partition(start)
    mid2, end_marker, after2 = after.partition(end)
    out = before + start + "\n" + inner_html + "\n" + end_marker + after2

    # Refresh the Updated pill timestamp (UTC) if present.
    try:
        now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        out = re.sub(r"(Updated automatically from PubMed: )[^<]+", r"\1" + now, out)
    except Exception:
        pass

    p.write_text(out, encoding="utf-8")

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to config JSON.")
    ap.add_argument("--mode", choices=["page", "fragment", "inject"], default="inject")
    ap.add_argument("--output", help="Output path (for page/fragment modes).")
    ap.add_argument("--target", help="Existing HTML file path (for inject mode).")
    args = ap.parse_args()

    cfg = load_config(args.config)
    terms = [q["term"] for q in cfg.get("queries", []) if q.get("term")]
    if not terms:
        print("No queries found in config.", file=sys.stderr)
        sys.exit(2)
    retmax = int(cfg.get("retmax", 200))

    # 1) ESearch across terms, dedupe PMIDs
    pmids = []
    for t in terms:
        ids = esearch(t, retmax=retmax)
        pmids.extend(ids)
    pmids = sorted(set(pmids), key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
    if not pmids:
        print("No PMIDs found.", file=sys.stderr)
        sys.exit(0)

    # 2) ESummary and normalize
    raw = esummary(pmids)
    records = [normalize_record(r) for r in raw]
    # 3) Group
    by_year = group_by_year(records)

    if args.mode == "fragment":
        if not args.output:
            print("--output is required for mode=fragment", file=sys.stderr)
            sys.exit(2)
        frag = render_fragment(by_year)
        Path(args.output).write_text(frag, encoding="utf-8")
        print(f"Wrote fragment to {args.output}.")
    elif args.mode == "page":
        if not args.output:
            print("--output is required for mode=page", file=sys.stderr)
            sys.exit(2)
        # minimal standalone page; mostly for debugging
        frag = render_fragment(by_year)
        page = "<!doctype html><meta charset='utf-8'><title>Publications</title>" + frag
        Path(args.output).write_text(page, encoding="utf-8")
        print(f"Wrote page to {args.output}.")
    else:
        if not args.target:
            print("--target is required for mode=inject", file=sys.stderr)
            sys.exit(2)
        frag = render_fragment(by_year)
        inject_into_file(args.target, frag)
        total = sum(len(v) for v in by_year.values())
        print(f"Injected {total} records into {args.target}.")

if __name__ == "__main__":
    main()
