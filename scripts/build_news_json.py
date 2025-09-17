#!/usr/bin/env python3
"""
Builds assets/data/news.json by aggregating RSS from Google News and Yahoo News
for Stephane Angers, his lab, and affiliated biotech stories in a biomedical
context. Pure-stdlib (urllib + xml.etree).
"""
import sys, os, json, re, datetime, email.utils, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlparse, parse_qs

OUT_PATH = os.environ.get("NEWS_JSON_PATH", "assets/data/news.json")

SEARCH_QUERIES = [
    '"Stephane Angers" (biomedical OR Wnt OR Frizzled OR "beta-catenin" OR cancer OR regeneration OR signaling OR "Donnelly Centre" OR Toronto)',
    '"Stéphane Angers" OR "Angers Lab" OR "Angers Laboratory"',
    '"Donnelly Centre" (Toronto OR "University of Toronto" OR researchers)',
    '"University of Toronto" (neurogenesis OR "Parkinson\'s disease" OR dopaminergic OR medulloblastoma OR retinopathy)',
    '"Antlera" OR "AntlerA" OR "Antlera Therapeutics"',
    '"EyeBio" OR (Merck AND EyeBio) OR (Merck AND "eye disease")'
]

FEED_TEMPLATES = [
    # Google News RSS (Canada/English)
    lambda query: f'https://news.google.com/rss/search?q={quote(query)}&hl=en-CA&gl=CA&ceid=CA:en',
    # Yahoo News RSS
    lambda query: f'https://news.search.yahoo.com/rss?p={quote(query)}'
]

TOPIC_KEYWORDS = [
    'wnt','frizzled','β-catenin','beta-catenin','cancer','regeneration','regenerative','glioblastoma',
    'signaling','donnelly','endothelial','barrier','surrogate','agonist',
    'medulloblastoma','radiation','therapeutic','therapy','neurogenesis','parkinson','dopaminergic',
    'dopamine','retinopathy','retina','retinal','ophthalmology','antibody','stem cell','neurons','neural',
    'antlera','eyebio','regor','cdk','biotech','spinout','genentech','roche','eye disease'
]

AFFILIATIONS = [
    'stephane angers','stéphane angers','stephane-angers',
    'angers lab','angers laboratory','angers\' lab','angers’ lab',
    'donnelly centre','donnelly center','temerty','medicine by design',
    'university of toronto','u of t','université de toronto',
    'toronto researchers','antlera','eyebio','regor','centre donnelly'
]

TRUSTED_HOSTS = {
    'temertymedicine.utoronto.ca',
    'utoronto.ca',
    'medicalxpress.com',
    'drugtargetreview.com',
    'prnewswire.com',
    'bioprocessintl.com',
    'fiercebiotech.com',
    'biospace.com',
    'endpoints.news',
    'metroquebec.com'
}

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

def includes_topic_keywords(text):
    t = (text or '').lower()
    return any(k in t for k in TOPIC_KEYWORDS)

def has_affiliation(text, host=''):
    t = (text or '').lower()
    if any(token in t for token in AFFILIATIONS):
        return True
    host_norm = host_from(host)
    return host_norm in TRUSTED_HOSTS if host_norm else False

def host_from(url):
    try:
        net = urlparse(url).netloc.lower()
        net = net[4:] if net.startswith('www.') else net
        return net
    except Exception:
        return ''

def clean_link(url):
    if not url:
        return ''
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    netloc = parsed.netloc.lower()
    if netloc.endswith('news.google.com') or netloc.endswith('news.yahoo.com'):
        qs = parse_qs(parsed.query)
        target = qs.get('url')
        if target:
            return target[0]
    return url

def main():
    all_items = []
    for query in SEARCH_QUERIES:
        for feed_builder in FEED_TEMPLATES:
            url = feed_builder(query)
            try:
                xml = fetch(url)
                items = parse_rss(xml)
                all_items.extend(items)
            except urllib.error.HTTPError as e:
                print(f"[warn] HTTP error {e.code} for {url}", file=sys.stderr)
            except Exception as e:
                print(f"[warn] failed {url}: {e}", file=sys.stderr)

    # Filter for affiliation plus relevant biomedical/biotech keywords
    filtered = []
    seen = set()
    for it in all_items:
        raw_link = (it.get('link','') or '').strip()
        link = clean_link(raw_link)
        source_text = it.get('source','') or ''
        text = ' '.join([it.get('title',''), it.get('description',''), link or raw_link, source_text])
        host = host_from(link or raw_link)
        if not has_affiliation(text, host):
            continue
        if not includes_topic_keywords(text):
            continue
        key = link or (it.get('title') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)

        dt = parse_date(it.get('pubDate',''))
        iso = dt.isoformat() if dt else ''
        source = source_text or host_from(link) or host_from(raw_link)
        filtered.append({
            'title': it.get('title','').strip() or '(untitled)',
            'link': link or raw_link,
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
