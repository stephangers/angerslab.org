#!/usr/bin/env python3
"""
Builds assets/data/news.json by aggregating RSS from Google News and Yahoo News
for "Stephane Angers" in a biomedical context. Pure-stdlib (urllib + xml.etree).
"""
import sys, os, json, re, datetime, email.utils, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import quote

OUT_PATH = os.environ.get("NEWS_JSON_PATH", "assets/data/news.json")

QUERY = '"Stephane Angers" (biomedical OR Wnt OR Frizzled OR "beta-catenin" OR cancer OR regeneration OR signaling OR "Donnelly Centre" OR Toronto)'
FEEDS = [
    # Google News RSS (Canada/English)
    f'https://news.google.com/rss/search?q={quote(QUERY)}&hl=en-CA&gl=CA&ceid=CA:en',
    # Yahoo News RSS
    f'https://news.search.yahoo.com/rss?p={quote(QUERY)}'
]

KEYWORDS = [
    'wnt','frizzled','β-catenin','beta-catenin','cancer','regeneration','glioblastoma',
    'signaling','donnelly','university of toronto','endothelial','barrier','surrogate','agonist'
]

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (AngersLab NewsBot)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def parse_rss(xml_bytes):
    # Try to parse items from RSS/Atom-ish feeds
    root = ET.fromstring(xml_bytes)
    items = []
    # Typical namespaces (best-effort)
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'content': 'http://purl.org/rss/1.0/modules/content/'
    }
    # Prefer RSS item
    for it in root.findall('.//item'):
        title = (it.findtext('title') or '').strip()
        link = (it.findtext('link') or '').strip()
        pub = (it.findtext('pubDate') or '').strip() or (it.findtext('dc:date', namespaces=ns) or '').strip()
        source = (it.findtext('source') or '').strip()
        desc = (it.findtext('description') or '').strip()
        items.append({'title': title, 'link': link, 'pubDate': pub, 'source': source, 'description': desc})
    # Atom fallback
    if not items:
        for it in root.findall('.//atom:entry', ns):
            title = (it.findtext('atom:title', default='', namespaces=ns) or '').strip()
            link_el = it.find('atom:link', ns)
            link = link_el.get('href').strip() if link_el is not None else ''
            pub = (it.findtext('atom:updated', default='', namespaces=ns) or it.findtext('atom:published', default='', namespaces=ns) or '').strip()
            source = ''
            desc = (it.findtext('atom:summary', default='', namespaces=ns) or '').strip()
            items.append({'title': title, 'link': link, 'pubDate': pub, 'source': source, 'description': desc})
    return items

def parse_date(dstr):
    if not dstr:
        return None
    # Try RFC 2822 via email.utils
    try:
        dt = email.utils.parsedate_to_datetime(dstr)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        pass
    # Try ISO
    try:
        return datetime.datetime.fromisoformat(dstr)
    except Exception:
        return None

def includes_bio_keywords(text):
    t = (text or '').lower()
    return any(k in t for k in KEYWORDS)

def has_name(text):
    return re.search(r'\bstephane\s+angers\b', (text or ''), flags=re.IGNORECASE) is not None

def host_from(url):
    try:
        from urllib.parse import urlparse
        net = urlparse(url).netloc
        return net[4:] if net.startswith('www.') else net
    except Exception:
        return ''

def main():
    all_items = []
    for url in FEEDS:
        try:
            xml = fetch(url)
            items = parse_rss(xml)
            all_items.extend(items)
        except urllib.error.HTTPError as e:
            print(f"[warn] HTTP error {e.code} for {url}", file=sys.stderr)
        except Exception as e:
            print(f"[warn] failed {url}: {e}", file=sys.stderr)

    # Filter: must mention Stephane Angers and be biomedical-ish
    filtered = []
    seen = set()
    for it in all_items:
        text = ' '.join([it.get('title',''), it.get('description',''), it.get('link','')])
        if not has_name(text):
            continue
        if not includes_bio_keywords(text):
            continue
        key = (it.get('link') or it.get('title') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)

        dt = parse_date(it.get('pubDate',''))
        iso = dt.isoformat() if dt else ''
        source = it.get('source') or host_from(it.get('link',''))
        filtered.append({
            'title': it.get('title','').strip() or '(untitled)',
            'link': it.get('link','').strip(),
            'pubDate': iso,
            'source': source or ''
        })

    # Sort newest first, cap to 40
    filtered.sort(key=lambda x: x['pubDate'] or '', reverse=True)
    filtered = filtered[:40]

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUT_PATH} with {len(filtered)} items.")

if __name__ == "__main__":
    main()
