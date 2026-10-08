// Shared keyboard-friendly navigation and an optional, user-controlled slideshow.
document.addEventListener('DOMContentLoaded', () => {
  const year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
  const button = document.querySelector('.menu-btn');
  const menu = document.getElementById('menu');
  if (button && menu) {
    const setMenu = open => {
      menu.classList.toggle('open', open);
      button.setAttribute('aria-expanded', String(open));
      button.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      document.body.classList.toggle('no-scroll', open);
    };
    // Replace older per-page handlers so all pages share the same behavior.
    button.removeAttribute('onclick');
    button.addEventListener('click', () => setMenu(!menu.classList.contains('open')));
    menu.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setMenu(false)));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu.classList.contains('open')) {
        setMenu(false);
        button.focus();
      }
    });
    document.addEventListener('click', event => {
      if (!event.target.closest('header')) setMenu(false);
    });
    window.addEventListener('resize', () => { if (innerWidth > 860) setMenu(false); });
    setMenu(false);
  }
  const slides = [...document.querySelectorAll('.gallery-slide')];
  if (!slides.length) return;
  document.querySelector('.gallery-controls').hidden = false;
  const play = document.getElementById('gallery-play');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let index = 0, timer = null;
  const show = next => {
    index = (next + slides.length) % slides.length;
    slides.forEach((slide, i) => { slide.hidden = i !== index; });
    document.getElementById('gallery-count').textContent = `${index + 1} / ${slides.length}`;
  };
  const pause = () => {
    clearInterval(timer); timer = null;
    play.textContent = 'Play slideshow';
    play.setAttribute('aria-pressed', 'false');
  };
  document.getElementById('gallery-prev').addEventListener('click', () => { pause(); show(index - 1); });
  document.getElementById('gallery-next').addEventListener('click', () => { pause(); show(index + 1); });
  play.addEventListener('click', () => {
    if (timer) return pause();
    timer = setInterval(() => show(index + 1), 6000);
    play.textContent = 'Pause slideshow';
    play.setAttribute('aria-pressed', 'true');
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) pause(); });
  show(0); // Never start motion automatically, including for reduced-motion users.
});

// Refresh homepage news from the same local feed used by the News page.
// Keep the static cards as a useful fallback when JavaScript or fetching fails.
document.addEventListener('DOMContentLoaded', async () => {
  const container = document.getElementById('home-news');
  if (!container) return;
  try {
    const response = await fetch('assets/data/news.json');
    if (!response.ok) return;
    const items = await response.json();
    if (!Array.isArray(items)) return;
    const cards = items.filter(item => {
      try { return ['https:', 'http:'].includes(new URL(item.link).protocol); }
      catch { return false; }
    }).sort((a,b) => (Date.parse(b.pubDate) || 0) - (Date.parse(a.pubDate) || 0)).slice(0,3).map(item => {
      const card = document.createElement('article'); card.className = 'card';
      const source = document.createElement('p'); source.className = 'sub'; source.textContent = item.source || 'News';
      const title = document.createElement('h3');
      const link = document.createElement('a'); link.href = item.link; link.textContent = item.title || 'Read article'; title.append(link);
      const date = document.createElement('p'); date.className = 'sub';
      const parsed = new Date(item.pubDate);
      date.textContent = Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleDateString('en-CA', {year:'numeric',month:'short',day:'numeric',timeZone:'UTC'});
      card.append(source,title,date); return card;
    });
    if (cards.length) container.replaceChildren(...cards);
  } catch { /* The static cards remain available. */ }
});
