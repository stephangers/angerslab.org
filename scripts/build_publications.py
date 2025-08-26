#!/usr/bin/env python3
"""
build_publications.py
Pulls publications from PubMed using eUtils and either prints HTML or injects into publications.html.

Usage:
  python build_publications.py --config scripts/pubmed_config.json --mode inject --target publications.html
  python build_publications.py --config scripts/pubmed_config.json --mode print

No third‑party deps (urllib + xml.etree). Compatible with GitHub Actions runners.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Iterable

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

def _http_get(url: str, params: Dict[str, Any], retries: int = 3, sleep=0.4) -> bytes:
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    last_err = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(full, timeout=30) as r:
                return r.read()
        except Exception as e:
            last_err = e
            time.sleep(sleep * (i + 1))
    raise RuntimeError(f"HTTP GET failed for {url}: {last_err}")

def esearch_ids(term: str, retmax: int = 200, api_key: str | None = None, email: str | None = None) -> List[str]:
    params = {"db": "pubmed", "term": term, "retmax": retmax, "retmode": "xml", "sort": "pub+date"}
    if api_key: params["api_key"] = api_key
    if email:   params["email"]   = email
    data = _http_get(ESEARCH, params)
    root = ET.fromstring(data)
    return [e.text for e in root.findall(".//IdList/Id") if e.text]

def efetch_records(pmids: Iterable[str], api_key: str | None = None, email: str | None = None) -> List[Dict[str, Any]]:
    pmids = [p for p in pmids if p]
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if api_key: params["api_key"] = api_key
    if email:   params["email"]   = email
    xml_bytes = _http_get(EFETCH, params)
    root = ET.fromstring(xml_bytes)
    out: List[Dict[str, Any]] = []
    for art in root.findall(".//PubmedArticle"):
        med = art.find("./MedlineCitation")
        pmid = (med.findtext("./PMID") or "").strip()
        artinfo = med.find("./Article")
        journal = (artinfo.findtext("./Journal/Title") or "").strip()
        art_title = "".join(artinfo.findtext("./ArticleTitle") or "").strip()
        # Authors
        authors = []
        for a in artinfo.findall("./AuthorList/Author"):
            last = (a.findtext("LastName") or "").strip()
            fore = (a.findtext("ForeName") or "").strip()
            coll = (a.findtext("CollectiveName") or "").strip()
            if coll:
                authors.append(coll)
            else:
                nm = " ".join(x for x in [last, fore] if x).strip()
                if nm: authors.append(nm)
        # DOI
        doi = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = aid.text or ""
                break
        # Year
        year = ""
        # Try ArticleDate first, then Journal pub date, then PubDate Year
        year_candidates = [
            artinfo.findtext("./ArticleDate/Year"),
            artinfo.findtext("./Journal/JournalIssue/PubDate/Year"),
            med.findtext("./DateCompleted/Year"),
            med.findtext("./DateCreated/Year"),
        ]
        for y in year_candidates:
            if y and re.fullmatch(r"\d{4}", y):
                year = y
                break
        if not year:
            year = "Unknown"
        # Month/day string for sorting/tooltip
        month = artinfo.findtext("./ArticleDate/Month") or artinfo.findtext("./Journal/JournalIssue/PubDate/Month") or ""
        day   = artinfo.findtext("./ArticleDate/Day") or artinfo.findtext("./Journal/JournalIssue/PubDate/Day") or ""
        # Compose record
        out.append({
            "pmid": pmid,
            "title": art_title,
            "journal": journal,
            "authors": authors,
            "doi": doi,
            "year": year,
            "month": month,
            "day": day,
        })
    return out

def render_html(records: List[Dict[str, Any]]) -> str:
    # Sort by year (desc) then by pmid desc (rough proxy for recency)
    records = sorted(records, key=lambda r: (r.get("year",""), r.get("pmid","")), reverse=True)
    by_year = collections.OrderedDict()
    for r in records:
        by_year.setdefault(r["year"], []).append(r)

    def esc(x: str) -> str: return html.escape(x or "")

    lines: List[str] = []
    lines.append("<!-- PUBLIST:START -->")
    for year, items in by_year.items():
        lines.append(f'<section class="year-block" data-year="{esc(year)}">')
        lines.append(f'  <h2 class="year">{esc(year)}</h2>')
        lines.append('  <ol class="pubs">')
        for it in items:
            meta = esc(", ".join(it["authors"]))
            title = esc(it["title"])
            journal = esc(it["journal"])
            pmid = esc(it["pmid"])
            doi = esc(it["doi"])
            data_search = f"{title} {journal} {it.get('year','')} {meta} {doi} {pmid}".lower()
            links = []
            if doi:
                links.append(f'<a href="https://doi.org/{doi}" target="_blank" rel="noopener">DOI</a>')
            if pmid:
                links.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank" rel="noopener">PMID:{pmid}</a>')
            links_html = " · ".join(links) if links else ""
            lines.append(
                f'    <li class="pub" data-search="{html.escape(data_search)}">'
                f'      <div class="meta">{meta}</div>'
                f'      <div class="title">{title}</div>'
                f'      <div class="journal">{journal}</div>'
                f'      <div class="links">{links_html}</div>'
                f'    </li>'
            )
        lines.append("  </ol>")
        lines.append("</section>")
    lines.append("<!-- PUBLIST:END -->")
    return "\n".join(lines)

def inject_into_html(target_path: str, new_block: str, updated_iso_utc: str) -> None:
    with open(target_path, "r", encoding="utf-8") as f:
        html_in = f.read()

    # Replace block between PUBLIST markers
    if "<!-- PUBLIST:START -->" in html_in and "<!-- PUBLIST:END -->" in html_in:
        html_out = re.sub(
            r"<!-- PUBLIST:START -->.*?<!-- PUBLIST:END -->",
            new_block,
            html_in,
            flags=re.S,
        )
    else:
        # If markers missing, append near end of <main>
        html_out = re.sub(r"(</main>)", new_block + r"\n\1", html_in, count=1)

    # Replace __UPDATED_AT__ token and/or BUILD_UTC comment
    html_out = html_out.replace("__UPDATED_AT__", updated_iso_utc)
    if "BUILD_UTC:" not in html_out:
        html_out = re.sub(r"(</head>)", f"<!-- BUILD_UTC: {updated_iso_utc} -->\\n\\1", html_out, count=1)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(html_out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to pubmed_config.json")
    ap.add_argument("--mode", choices=["print","inject"], default="print")
    ap.add_argument("--target", default="publications.html", help="Target HTML file when mode=inject")
    ap.add_argument("--api-key", dest="api_key", default=None, help="Optional NCBI API key")
    ap.add_argument("--email", dest="email", default=None, help="Optional contact email for NCBI")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    queries = [q.get("term","") for q in cfg.get("queries", []) if q.get("term")]
    retmax  = int(cfg.get("retmax", 200))
    if not queries:
        print("No queries found in config.", file=sys.stderr)
        sys.exit(2)

    pmid_list: List[str] = []
    for term in queries:
        ids = esearch_ids(term, retmax=retmax, api_key=args.api_key, email=args.email)
        pmid_list.extend(ids)
        time.sleep(0.34)  # polite pacing

    # de-duplicate but keep order (latest first from esearch)
    seen = set()
    pmid_list_uniq = []
    for p in pmid_list:
        if p not in seen:
            seen.add(p)
            pmid_list_uniq.append(p)

    # fetch
    records = []
    # chunk efetch in batches of 200
    B = 200
    for i in range(0, len(pmid_list_uniq), B):
        chunk = pmid_list_uniq[i:i+B]
        records.extend(efetch_records(chunk, api_key=args.api_key, email=args.email))
        time.sleep(0.34)

    html_block = render_html(records)
    updated_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    if args.mode == "print":
        print(html_block)
    else:
        inject_into_html(args.target, html_block, updated_iso)
        print(f"Injected {len(records)} records into {args.target} at {updated_iso}")

if __name__ == "__main__":
    main()
