#!/usr/bin/env python3
"""
build_publications.py  — v2
- Updates publications.html between <!-- PUBLIST:START --> ... <!-- PUBLIST:END -->
- Robust timestamp update even if "__UPDATED_AT__" token isn't present
- Optionally bold authors that match names found in People.html

Usage:
  python build_publications.py --config scripts/pubmed_config.json --mode inject --target publications.html [--people people.html]

Notes:
- Stdlib only; uses ESearch + EFetch (XML) for rich/consistent metadata
"""
from __future__ import annotations
import argparse, collections, datetime as dt, html, json, os, re, sys, time, unicodedata
from typing import Any, Dict, Iterable, List, Set
import urllib.parse as up, urllib.request as ur
import xml.etree.ElementTree as ET

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

def _http_get(url: str, params: Dict[str, Any], retries: int = 3, sleep=0.4) -> bytes:
    qs = up.urlencode(params)
    full = f"{url}?{qs}"
    last = None
    for i in range(retries):
        try:
            with ur.urlopen(full, timeout=30) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(sleep * (i+1))
    raise RuntimeError(f"GET failed: {url} {last}")

def esearch_ids(term: str, retmax: int, api_key: str|None, email: str|None) -> List[str]:
    params = {"db":"pubmed","term":term,"retmax":retmax,"retmode":"xml","sort":"pub+date"}
    if api_key: params["api_key"] = api_key
    if email:   params["email"]   = email
    root = ET.fromstring(_http_get(ESEARCH, params))
    return [e.text for e in root.findall(".//IdList/Id") if e.text]

def efetch_records(pmids: Iterable[str], api_key: str|None, email: str|None) -> List[Dict[str,Any]]:
    pmids = [p for p in pmids if p]
    if not pmids: return []
    params = {"db":"pubmed","id":",".join(pmids),"retmode":"xml"}
    if api_key: params["api_key"] = api_key
    if email:   params["email"]   = email
    root = ET.fromstring(_http_get(EFETCH, params))
    out: List[Dict[str,Any]] = []
    for art in root.findall(".//PubmedArticle"):
        med = art.find("./MedlineCitation")
        pmid = (med.findtext("./PMID") or "").strip()
        artinfo = med.find("./Article")
        title = (artinfo.findtext("./ArticleTitle") or "").strip()
        journal = (artinfo.findtext("./Journal/Title") or "").strip()
        # authors
        authors: List[str] = []
        for a in artinfo.findall("./AuthorList/Author"):
            last = (a.findtext("LastName") or "").strip()
            fore = (a.findtext("ForeName") or "").strip()
            coll = (a.findtext("CollectiveName") or "").strip()
            if coll:
                authors.append(coll)
            else:
                nm = " ".join(x for x in [fore, last] if x).strip()
                if nm: authors.append(nm)
        # doi
        doi = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = (aid.text or "").strip()
                break
        # year
        year = ""
        for y in [
            artinfo.findtext("./ArticleDate/Year"),
            artinfo.findtext("./Journal/JournalIssue/PubDate/Year"),
            med.findtext("./DateCompleted/Year"),
            med.findtext("./DateCreated/Year"),
        ]:
            if y and re.fullmatch(r"\d{4}", y):
                year = y; break
        if not year: year = "Unknown"
        out.append({"pmid":pmid,"title":title,"journal":journal,"authors":authors,"doi":doi,"year":year})
    return out

def _name_parts(name: str) -> tuple[str, str]:
    """Return a normalized (given name, surname) pair for conservative matching."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\b(?:phd|md|msc|bsc|dphil|dr)\b", " ", text)
    words = re.findall(r"[a-z]+", text)
    if len(words) < 2:
        return "", ""
    return words[0], words[-1]


def _same_person(author: str, lab_name: str) -> bool:
    """Allow accents and middle names/initials, but require surname + given-name agreement."""
    author_first, author_last = _name_parts(author)
    lab_first, lab_last = _name_parts(lab_name)
    if not author_first or not lab_first or author_last != lab_last:
        return False
    return (
        author_first == lab_first
        or (len(author_first) == 1 and lab_first.startswith(author_first))
        or (len(lab_first) == 1 and author_first.startswith(lab_first))
    )


def _bold_authors(authors: List[str], highlight: Set[str]) -> str:
    aa = []
    for author in authors:
        if any(_same_person(author, lab_name) for lab_name in highlight):
            aa.append(f"<strong>{html.escape(author)}</strong>")
        else:
            aa.append(html.escape(author))
    return ", ".join(aa)


def render_html(records: List[Dict[str,Any]], highlight: Set[str]) -> str:
    records = sorted(records, key=lambda r: (r.get("year",""), r.get("pmid","")), reverse=True)
    by_year: Dict[str, List[Dict[str,Any]]] = collections.OrderedDict()
    for r in records:
        by_year.setdefault(r["year"], []).append(r)
    parts = ["<!-- PUBLIST:START -->"]
    for year, items in by_year.items():
        parts.append(f'<section class="year-block" data-year="{html.escape(year)}">')
        parts.append(f'  <h2 class="year">{html.escape(year)}</h2>')
        parts.append('  <ol class="pubs">')
        for it in items:
            meta = _bold_authors(it["authors"], highlight)
            title = html.escape(it["title"])
            journal = html.escape(it["journal"])
            pmid = html.escape(it["pmid"])
            doi = html.escape(it["doi"])
            data_search = f"{title} {journal} {it.get('year','')} {' '.join(it['authors'])} {doi} {pmid}".lower()
            links = []
            if doi: links.append(f'<a href="https://doi.org/{doi}" target="_blank" rel="noopener">DOI</a>')
            if pmid: links.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank" rel="noopener">PMID:{pmid}</a>')
            parts.append(
                f'    <li class="pub" data-search="{html.escape(data_search)}">'
                f'      <div class="meta">{meta}</div>'
                f'      <div class="title">{title}</div>'
                f'      <div class="journal">{journal}</div>'
                f'      <div class="links">{" · ".join(links)}</div>'
                f'    </li>'
            )
        parts.append('  </ol>')
        parts.append('</section>')
    parts.append("<!-- PUBLIST:END -->")
    return "\n".join(parts)

def inject(target_path: str, html_block: str, updated_iso_utc: str) -> None:
    with open(target_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Replace between markers or append before </main>
    if "<!-- PUBLIST:START -->" in src and "<!-- PUBLIST:END -->" in src:
        out = re.sub(r"<!-- PUBLIST:START -->.*?<!-- PUBLIST:END -->", html_block, src, flags=re.S)
    else:
        out = re.sub(r"(</main>)", html_block + r"\n\1", src, count=1)

    # 1) Token replacement for __UPDATED_AT__
    if "__UPDATED_AT__" in out:
        out = out.replace("__UPDATED_AT__", updated_iso_utc)

    # 2) If there's an element with id="updated" and a data-updated attr, force-update that attribute
    out = re.sub(r'(id=["\']updated["\'][^>]*\bdata-updated=["\'])[^"\']*(["\'])', r'\1' + updated_iso_utc + r'\2', out)

    # 3) If no obvious place, inject a hidden build comment near </head> for debugging
    if "BUILD_UTC:" not in out:
        out = re.sub(r"(</head>)", f"<!-- BUILD_UTC: {updated_iso_utc} -->\\n\\1", out, count=1)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(out)

def harvest_names_from_people(path: str|None) -> Set[str]:
    names: Set[str] = set()
    if not path or not os.path.isfile(path):
        return names
    try:
        txt = open(path, "r", encoding="utf-8").read()
    except Exception:
        return names

    # Read the canonical roster used by the People page.
    data_match = re.search(r"const\s+DATA_URL\s*=\s*['\"]([^'\"]+people\.json)['\"]", txt)
    if data_match:
        data_path = os.path.join(os.path.dirname(path), data_match.group(1))
        try:
            with open(data_path, "r", encoding="utf-8") as data_file:
                people = json.load(data_file)
            for person in people:
                name = str(person.get("name", "")).strip()
                if _name_parts(name)[0]:
                    names.add(name)
        except (OSError, ValueError, TypeError):
            pass

    # Include any names embedded in the HTML fallback data.
    for match in re.finditer(r"\bname\s*:\s*['\"]([^'\"]+)['\"]", txt):
        name = html.unescape(match.group(1)).strip()
        if _name_parts(name)[0]:
            names.add(name)

    names.update({"Stéphane Angers", "Stephane Angers", "S. Angers"})
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--mode", choices=["inject","print"], default="inject")
    ap.add_argument("--target", default="publications.html")
    ap.add_argument("--api-key", dest="api_key", default=None)
    ap.add_argument("--email", dest="email", default=None)
    ap.add_argument("--people", default=None, help="Path to People.html for author highlighting")
    args = ap.parse_args()

    cfg = json.load(open(args.config, "r", encoding="utf-8"))
    terms = [q.get("term","") for q in cfg.get("queries",[]) if q.get("term")]
    retmax = int(cfg.get("retmax", 200))

    pmids: List[str] = []
    for t in terms:
        pmids.extend(esearch_ids(t, retmax, args.api_key, args.email))
        time.sleep(0.34)
    # de-dupe maintain order
    seen = set(); uniq = []
    for p in pmids:
        if p not in seen:
            seen.add(p); uniq.append(p)

    # fetch in batches
    recs: List[Dict[str,Any]] = []
    for i in range(0, len(uniq), 200):
        recs.extend(efetch_records(uniq[i:i+200], args.api_key, args.email))
        time.sleep(0.34)

    names = harvest_names_from_people(args.people)
    block = render_html(recs, names)
    updated_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    if args.mode == "print":
        print(block)
    else:
        inject(args.target, block, updated_iso)
        print(f"Injected {len(recs)} records into {args.target} at {updated_iso}")

if __name__ == "__main__":
    main()
