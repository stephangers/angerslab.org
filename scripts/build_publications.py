#!/usr/bin/env python3
"""
build_publications.py
Query PubMed (E-utilities) with one or more search queries and render a static publications.html.
- Deduplicates by PMID
- Groups by year (desc)
- Includes journal, authors, title, DOI/PMID links
Usage:
  python scripts/build_publications.py --config scripts/pubmed_config.json --output publications.html
"""
import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
import time
import requests

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS = {"User-Agent": "AngersLab-PubMed-AutoUpdater/1.0 (contact: none)"}


def esearch(term, retmax=200):
    """Return PMIDs list for a given term."""
    params = {
        "db": "pubmed",
        "retmode": "json",
        "retmax": retmax,
        "sort": "pub+date",
        "term": term,
    }
    r = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("esearchresult", {}).get("idlist", [])


def esummary(pmids):
    """Return details dict keyed by PMID using esummary (JSON)."""
    if not pmids:
        return {}
    out = {}
    chunk_size = 200
    for i in range(0, len(pmids), chunk_size):
        chunk = pmids[i:i+chunk_size]
        params = {
            "db": "pubmed",
            "retmode": "json",
            "id": ",".join(chunk)
        }
        r = requests.get(f"{EUTILS_BASE}/esummary.fcgi", params=params, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        out.update(data.get("result", {}))
        time.sleep(0.34)  # be polite to NCBI
    out.pop("uids", None)
    return out


def normalize_record(pmrec):
    """Convert esummary record to a minimal schema."""
    uid = str(pmrec.get("uid", ""))
    title = pmrec.get("title", "").rstrip(".")
    journal = (pmrec.get("fulljournalname") or pmrec.get("source") or "").strip()
    pubdate = pmrec.get("pubdate", "")
    year = ""
    for token in pubdate.split():
        if token.isdigit() and len(token) == 4:
            year = token
            break
    if not year:
        year = str(pmrec.get("epubdate", "")[:4]) if pmrec.get("epubdate") else ""
    authors_list = pmrec.get("authors", [])
    authors = ", ".join([a.get("name", "") for a in authors_list if a.get("name")])
    doi = ""
    eloc = pmrec.get("elocationid", "")
    articleids = pmrec.get("articleids", [])
    for it in articleids:
        if it.get("idtype") == "doi":
            doi = it.get("value", "")
            break
    if not doi and "doi:" in eloc.lower():
        try:
            doi = eloc.lower().split("doi:")[1].strip().split()[0]
        except Exception:
            pass
    return {
        "pmid": uid,
        "title": title,
        "journal": journal,
        "year": year or "In press",
        "authors": authors,
        "doi": doi
    }


def render_html(records_by_year, page_title="Publications"):
    """Render a simple, readable HTML page with groups by year."""
    style = """
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 24px; line-height: 1.5; color: #111; }
      h1 { font-size: 28px; margin-bottom: 8px; }
      .updated { color: #666; font-size: 14px; margin-bottom: 24px; }
      h2 { font-size: 22px; margin-top: 28px; border-bottom: 1px solid #eee; padding-bottom: 4px; }
      ol { padding-left: 18px; }
      li { margin: 10px 0; }
      .jrnl { font-style: italic; }
      .meta { color: #555; }
      a { text-decoration: none; }
      a:hover { text-decoration: underline; }
    </style>
    """
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{page_title}</title>{style}</head><body>"]
    parts.append(f"<h1>{page_title}</h1>")
    parts.append(f"<div class='updated'>Updated automatically from PubMed: {now}</div>")
    def year_key(y):
        return (9999 if y == 'In press' else int(y))
    for year in sorted(records_by_year.keys(), key=year_key, reverse=True):
        parts.append(f"<h2>{year}</h2>")
        parts.append("<ol>")
        for rec in records_by_year[year]:
            title = rec['title']
            authors = rec['authors']
            jrnl = rec['journal']
            pmid = rec['pmid']
            doi = rec['doi']
            links = [f"<a href='https://pubmed.ncbi.nlm.nih.gov/{pmid}/'>PMID:{pmid}</a>"]
            if doi:
                links.append(f"<a href='https://doi.org/{doi}'>DOI</a>")
            line = f"<li><span class='meta'>{authors}</span>. <strong>{title}</strong>. <span class='jrnl'>{jrnl}</span>. {' | '.join(links)}</li>"
            parts.append(line)
        parts.append("</ol>")
    parts.append("</body></html>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to pubmed_config.json")
    ap.add_argument("--output", required=True, help="Output HTML file (publications.html)")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = json.load(f)

    queries = cfg.get("queries", [])
    retmax = int(cfg.get("retmax", 300))
    if not queries:
        print("No queries found in config.", file=sys.stderr)
        sys.exit(1)

    all_pmids = []
    for q in queries:
        pmids = esearch(q, retmax=retmax)
        all_pmids.extend(pmids)

    seen = set()
    deduped = []
    for p in all_pmids:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    summaries = esummary(deduped)
    by_year = defaultdict(list)
    for pmid in deduped:
        rec = summaries.get(pmid)
        if not rec:
            continue
        norm = normalize_record(rec)
        by_year[norm["year"]].append(norm)

    html = render_html(by_year, page_title=cfg.get("page_title", "Publications"))
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {args.output} with {sum(len(v) for v in by_year.values())} records.")


if __name__ == "__main__":
    main()
