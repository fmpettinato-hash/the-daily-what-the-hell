#!/usr/bin/env python3
"""Free daily feed-based edition of The Daily What the Hell?.

Preserves the approved masthead and CSS from the repository's locked index.html.
Does not use an AI API, a paid service, or fabricate unavailable news/weather.
This is a *separate automated feed edition*, not the ChatGPT-written edition.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

HST = ZoneInfo('Pacific/Honolulu')
UA = 'DailyWhatTheHell/1.0 (public news reader; links to original publishers)'
MAX_BYTES = 1_500_000
TIMEOUT = 12

# Sources are used as pointers to publishers; publication dates and links come from their feeds.
SOURCES = {
    'bigislandnow': ('Big Island Now', 'https://bigislandnow.com/feed/'),
    'bigislandvideo': ('Big Island Video News', 'https://www.bigislandvideonews.com/feed/'),
    'civilbeat': ('Honolulu Civil Beat', 'https://www.civilbeat.org/feed/'),
    'npr_top': ('NPR', 'https://feeds.npr.org/1001/rss.xml'),
    'npr_politics': ('NPR Politics', 'https://feeds.npr.org/1014/rss.xml'),
    'npr_business': ('NPR Business', 'https://feeds.npr.org/1017/rss.xml'),
    'bbc_world': ('BBC World', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
    'bbc_science': ('BBC Science', 'https://feeds.bbci.co.uk/news/science_and_environment/rss.xml'),
    'bbc_tech': ('BBC Technology', 'https://feeds.bbci.co.uk/news/technology/rss.xml'),
    'bbc_culture': ('BBC Culture', 'https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml'),
    'npr_health': ('NPR Health', 'https://feeds.npr.org/1128/rss.xml'),
    'goodnews': ('Good News Network', 'https://www.goodnewsnetwork.org/feed/'),
    'travel': ('Travel news', 'https://news.google.com/rss/search?q=travel%20tourism%20aviation&hl=en-US&gl=US&ceid=US:en'),
}

GROUPS = [
    ('🌺 Big Island & Hawaiʻi', [('🌋 Local news', ['bigislandnow', 'bigislandvideo', 'civilbeat'], 3, 72)]),
    ('🇺🇸 National, Politics & Economy', [
        ('🇺🇸 National', ['npr_top'], 1, 48),
        ('🏛️ Politics', ['npr_politics'], 1, 48),
        ('💰 Economy', ['npr_business'], 1, 48),
    ]),
    ('🌍 World News', [('🌐 International', ['bbc_world'], 2, 48)]),
    ('🔬 Science, Technology & Health', [
        ('🔬 Science & environment', ['bbc_science'], 1, 72),
        ('💻 Technology', ['bbc_tech'], 1, 72),
        ('🩺 Health', ['npr_health'], 1, 72),
    ]),
    ('🎭 Entertainment & Culture', [('🎬 Culture', ['bbc_culture'], 1, 72)]),
    ('💛 A Little Good News', [('🌼 Bright spot', ['goodnews'], 2, 96)]),
]

INTRO = [
    "Big Island first. World nonsense second. Coffee before either one. The facts have sources; the sarcasm is complimentary.",
    "Welcome back to another episode of 'Surely Things Can't Get Weirder.' Spoiler: nobody made that promise.",
    "The planet is still spinning, the coffee is still necessary, and the headlines have once again chosen violence against our attention spans.",
    "Fresh headlines, both islands' weather, and the usual evidence that humanity needs a better project manager.",
    "Your daily serving of news, useful stuff, and side-eye. Please keep your arms and common sense inside the ride.",
]

APOCALYPSE = [
    ('The End Is Apparently Running Late', 'The zombies missed their connecting flight. Civilization remains a questionable but technically functioning operation.', 'Coffee, batteries, water. In that order unless something is actually on fire.'),
    ('Still Here. Against All Odds.', 'The world continues to behave like a group project where nobody read the instructions.', 'Charge the phone before you charge into an argument with the universe.'),
    ('Civilization Has Not Submitted Its Homework', 'The imaginary apocalypse committee is reviewing paperwork and finding exactly zero qualified adults.', 'Keep the flashlight handy; the doom soundtrack is optional.'),
    ('No Zombies, Just Meetings', "Today's fictional disaster report: somebody scheduled another meeting that could have been an email.", 'Make sure the backup power actually works before you need it.'),
    ('The Apocalypse Requests a Rain Check', 'Even the imaginary end of the world looked at the forecast and decided to stay home.', 'Store drinking water where you can find it in the dark.'),
    ('Everything Is Fine, According to the Coffee Mug', 'Reality continues to be managed by a committee of raccoons with clipboards. No offense to raccoons.', 'Keep a written emergency contact list; phones have terrible timing.'),
    ('Survival Status: Caffeinated', 'No confirmed fictional zombies. Plenty of ordinary nonsense. The difference is mostly paperwork.', 'Check the radio and rotate the power bank.'),
]

JAY_TIPS = [
    ('Rainproof is not the same as waterproof', 'Check the actual IP rating before leaving a radio or power bank in farm rain. “Weather-resistant” is marketing, not a diving certificate.', 'https://www.weather.gov/safety/lightning'),
    ('Charge the battery before the clouds roll in', 'A solar panel can top up a battery in good sun, but small built-in panels are slow. A charged power bank is the real backup.', 'https://www.ready.gov/power-outages'),
    ('Hand-crank radios: useful, not magical', 'The crank is an emergency backup for short listening or light use. It is not a practical substitute for charging a modern phone.', 'https://www.weather.gov/nwr/'),
    ('Keep a radio that works when the power does not', 'A battery-operated weather radio and spare batteries are more useful than a fancy gadget that needs the generator first.', 'https://www.weather.gov/nwr/'),
    ('Water first, gadgets second', 'Store clean drinking water in sealed containers. On a farm, keeping electronics dry and water safe are separate jobs.', 'https://www.ready.gov/water'),
    ('Lightning does not care about your playlist', 'When thunder is audible, leave exposed fields and get into a substantial building or hard-topped vehicle.', 'https://www.weather.gov/safety/lightning'),
    ('The dry-bag rule', 'A dry bag or sealed pouch adds protection to gear that lacks a verified water-resistance rating. Keep charging ports dry before connecting cables.', 'https://www.ready.gov/kit'),
]

RECIPES = [
    ('Ginger-Lime Chicken & Rice Bowls', '2', '25 minutes', 'Chicken breast, cooked rice, cucumber, ginger, lime, olive oil and optional cilantro.', 'Cook chicken thoroughly with ginger and a little oil. Serve over rice with cucumber and lime. Skip spicy sauces if your stomach has filed a complaint.'),
    ('Egg & Spinach Breakfast Rice', '2', '15 minutes', 'Cooked rice, eggs, spinach, olive oil and a pinch of salt.', 'Warm the rice, wilt the spinach and scramble in the eggs until fully set. Season simply; breakfast does not need to start a diplomatic incident.'),
    ('Cucumber-Lime Chicken Salad', '2', '20 minutes', 'Cooked skinless chicken, cucumber, lettuce, lime, olive oil and fresh herbs.', 'Slice and combine. Dress lightly with lime and olive oil. Keep portions reasonable and skip ingredients that trigger symptoms.'),
    ('Sweet Potato & Yogurt Bowls', '2', '35 minutes', 'Sweet potatoes, plain unsweetened Greek yogurt, cinnamon and chopped cucumber on the side.', 'Bake sweet potatoes until soft, split and add yogurt and cinnamon. No need to bury the entire thing under sugar.'),
    ('Ginger Tofu & Rice', '2', '20 minutes', 'Firm tofu, cooked rice, grated ginger, carrots and a little low-sodium soy sauce.', 'Brown cubed tofu, soften thin carrot slices, add ginger and serve with rice. Adjust soy sauce for sodium and personal tolerance.'),
    ('Oatmeal with Berries', '2', '10 minutes', 'Rolled oats, water or milk of choice, blueberries, cinnamon and optional pumpkin seeds.', 'Cook oats until creamy, then add berries and cinnamon. Choose a portion that works for your digestion.'),
    ('Lemon Herb Turkey Lettuce Cups', '2', '20 minutes', 'Lean ground turkey, lettuce leaves, lemon, parsley and finely chopped cucumber.', 'Cook turkey thoroughly, season with lemon and parsley, and spoon into lettuce cups. Use rice on the side if you want a fuller meal.'),
]

PISCES = [
    'Your intuition is working overtime. Your patience has requested a day off.',
    'You may be tempted to fix everyone else’s chaos. The stars suggest fixing your coffee first.',
    'Your creative brain has seventeen tabs open. Close at least three before lunch.',
    'An unexpected bit of peace might appear. Do not immediately schedule a project on top of it.',
    'You can care deeply and still decline to join someone else’s circus.',
    'A little quiet time is productive, even when the to-do list disagrees.',
    'Trust your instincts, but maybe check the weather before making a dramatic exit.',
]
GEMINI = [
    'Your curiosity has already started three conversations. Finish one before the next reel.',
    'Today favors good humor and a practical backup plan. The universe respects neither, but try anyway.',
    'A clever idea deserves a test run, not a heroic improvisation in the rain.',
    'Communication is key. A complete sentence would be an excellent start.',
    'Your energy is infectious. Please use it for something more useful than arguing with the radio.',
    'Be flexible today. The weather, apparently, has not read your schedule.',
    'A laugh and a good meal will go further than an elaborate plan.',
]


def http_get(url: str) -> bytes:
    req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/rss+xml, application/xml, application/json, */*'})
    with urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Response exceeds safe size limit')
        return data


def strip_markup(raw: str) -> str:
    raw = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', raw or '', flags=re.I | re.S)
    raw = re.sub(r'<[^>]*>', ' ', raw)
    return re.sub(r'\s+', ' ', unescape(raw)).strip()


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def child_text(el: ET.Element, tag: str) -> str:
    for child in el:
        if child.tag.rsplit('}', 1)[-1].lower() == tag.lower():
            return ''.join(child.itertext()).strip()
    return ''


def parse_feed(data: bytes, publisher: str) -> list[dict]:
    root = ET.fromstring(data)
    out = []
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] not in ('item', 'entry'):
            continue
        title = strip_markup(child_text(node, 'title'))
        desc = strip_markup(child_text(node, 'description') or child_text(node, 'summary'))
        link = child_text(node, 'link')
        if not link:
            for child in node:
                if child.tag.rsplit('}', 1)[-1] == 'link' and child.attrib.get('href'):
                    link = child.attrib['href']; break
        stamp = ''
        for name in ('pubDate', 'published', 'updated', 'date'):
            stamp = child_text(node, name)
            if stamp: break
        dt = parse_timestamp(stamp)
        if not title or not link or not link.startswith('https://') or not dt:
            continue
        if len(title) > 200:
            title = title[:197] + '…'
        # RSS summaries are not fact-checked by the generator; clearly attribute them.
        desc = desc[:230].rstrip(' ,;') + ('…' if len(desc) > 230 else '')
        out.append({'title': title, 'summary': desc, 'url': link, 'time': dt, 'publisher': publisher})
    return sorted(out, key=lambda x: x['time'], reverse=True)


def load_feeds() -> dict[str, list[dict]]:
    feeds = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(http_get, url): key for key, (_, url) in SOURCES.items()}
        for job in as_completed(jobs):
            key = jobs[job]
            try:
                feeds[key] = parse_feed(job.result(), SOURCES[key][0])
            except (ValueError, ET.ParseError, HTTPError, URLError, TimeoutError, OSError) as e:
                print(f'Feed unavailable [{key}]: {e}', file=sys.stderr)
                feeds[key] = []
    return feeds


def card(label: str, item: dict, now: datetime) -> str:
    when = item['time'].astimezone(HST).strftime('%b %-d, %Y')
    summary = item['summary'] or 'Publisher headline; open the source for the full report.'
    return (f'<article class="story"><div class="eyebrow">{escape(label)} • {escape(item["publisher"])} · {escape(when)}</div>'
            f'<h4>{escape(item["title"])}</h4><p>{escape(summary)}</p>'
            f'<a class="source" href="{escape(item["url"], quote=True)}" target="_blank" rel="noopener noreferrer">Read original report ↗</a></article>')


def news_html(feeds: dict[str, list[dict]], now: datetime) -> tuple[str, int]:
    seen = set()
    count = 0
    html = ['<h2 class="banner" id="news">📰 The News &amp; Interesting Stuff</h2>']
    for heading, categories in GROUPS:
        html.append(f'<h3 class="category">{escape(heading)}</h3>')
        for label, source_keys, limit, hours in categories:
            candidates = [x for key in source_keys for x in feeds.get(key, [])
                          if -timedelta(hours=2) <= now.astimezone(timezone.utc) - x['time'] <= timedelta(hours=hours)]
            candidates.sort(key=lambda x: x['time'], reverse=True)
            selected = []
            for item in candidates:
                norm = re.sub(r'\W+', '', item['title'].lower())
                if norm in seen: continue
                seen.add(norm)
                selected.append(item)
                if len(selected) >= limit: break
            for item in selected:
                html.append(card(label, item, now)); count += 1
            if not selected:
                links = ' · '.join(f'<a href="{escape(SOURCES[k][1], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(SOURCES[k][0])}</a>' for k in source_keys)
                html.append(f'<article class="story"><div class="eyebrow">{escape(label)} • Source check</div><h4>No fresh verified feed item available</h4><p>We could not confirm a recent dated item from these feeds. No recycled headline dressed up as breaking news.</p><p class="small">Check publishers: {links}</p></article>')
    return ''.join(html), count


def get_json(url: str) -> dict:
    return json.loads(http_get(url).decode('utf-8'))


def weather_code_label(code: int | None) -> str:
    if code is None: return 'Forecast details unavailable'
    if code in (0, 1): return 'Clear to mostly clear'
    if code in (2, 3): return 'Partly to mostly cloudy'
    if code in (45, 48): return 'Fog or low cloud'
    if code in (51, 53, 55, 56, 57): return 'Drizzle possible'
    if code in (61, 63, 65, 66, 67, 80, 81, 82): return 'Rain or showers possible'
    if code in (95, 96, 99): return 'Thunderstorms possible'
    return 'Variable conditions'


def weather_location(name: str, region: str, lat: float, lon: float, issue_day: date) -> str:
    params = urlencode({'latitude': lat, 'longitude': lon, 'daily': 'temperature_2m_max,precipitation_probability_max,weather_code,wind_speed_10m_max',
                        'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph', 'timezone': 'Pacific/Honolulu', 'forecast_days': 2})
    try:
        data = get_json('https://api.open-meteo.com/v1/forecast?' + params)['daily']
        if data['time'][0] != issue_day.isoformat():
            raise ValueError('Weather API date does not match local issue date')
        high = data['temperature_2m_max'][0]
        pop = data['precipitation_probability_max'][0]
        wind = data['wind_speed_10m_max'][0]
        code = data['weather_code'][0]
        if any(x is None for x in (high, pop, wind)):
            raise ValueError('Incomplete forecast')
        desc = f'{weather_code_label(code)}. Peak wind forecast around {round(wind)} mph.'
        figures = f'<strong>{round(high)}°F</strong><span>{round(pop)}% peak rain chance</span>'
    except (KeyError, ValueError, TypeError, HTTPError, URLError, TimeoutError, OSError) as e:
        print(f'Weather unavailable [{name}]: {e}', file=sys.stderr)
        figures = '<strong>Check NWS</strong>'
        desc = 'Forecast figures could not be verified. Use the official NWS forecast link below.'
    return (f'<div class="weather-location"><div class="weather-place">{escape(name)}<span>{escape(region)}</span></div>'
            f'<div class="weather-figures">{figures}</div><p>{escape(desc)}</p></div>')


def weather_html(issue: datetime) -> str:
    today = issue.date()
    out = ['<h2 class="banner" id="weather">🌤️ Island Weather — Big Island &amp; Oʻahu</h2>']
    for island, title, spots in [
        ('🌋 BIG ISLAND • Hawaiʻi Island', 'Kona &amp; Hilo', [('☀️ Kailua-Kona', 'Leeward', 19.640, -155.996), ('🌦️ Hilo', 'Windward', 19.729, -155.090)]),
        ('🏝️ OʻAHU', 'Honolulu &amp; Kāneʻohe', [('☀️ Honolulu', 'South shore', 21.309, -157.858), ('🌦️ Kāneʻohe', 'Windward', 21.409, -157.800)]),
    ]:
        locations = ''.join(weather_location(*spot, today) for spot in spots)
        out.append(f'<article class="story weather island-forecast"><div class="eyebrow">{escape(island)}</div><h3>{title}</h3>'
                   f'<div class="weather-locations">{locations}</div>'
                   '<p class="weather-explain">Source: Open-Meteo daily model forecast retrieved for this issue. Rain percentage is the <strong>highest forecast hourly precipitation probability</strong> during the local day, not the chance it will rain all day. This is not an official NWS station forecast.</p>'
                   '<a class="source" href="https://www.weather.gov/hfo/" target="_blank" rel="noopener noreferrer">Official NWS Honolulu forecasts and alerts ↗</a></article>')
    out.append('<article class="story weather"><div class="eyebrow">⚠️ Official alert check</div><h3>Hawaiʻi weather alerts</h3>')
    try:
        features = get_json('https://api.weather.gov/alerts/active?area=HI').get('features', [])
        alerts = [x for x in features if x.get('properties', {}).get('status') == 'Actual']
        if alerts:
            for alert in alerts[:4]:
                p = alert['properties']
                url = p.get('@id') or p.get('id') or 'https://www.weather.gov/hfo/'
                if not url.startswith('https://'): url = 'https://www.weather.gov/hfo/'
                out.append(f'<p><strong>{escape(p.get("event") or "Weather alert")}:</strong> {escape((p.get("headline") or p.get("areaDesc") or "See official details")[:240])} '
                           f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">Official alert ↗</a></p>')
        else:
            out.append('<p>No active statewide NWS alert returned by the API at generation time. Conditions can change; always check the official page.</p>')
    except (KeyError, ValueError, TypeError, HTTPError, URLError, TimeoutError, OSError) as e:
        print(f'NWS alert check unavailable: {e}', file=sys.stderr)
        out.append('<p>Live alert retrieval was unavailable. Do not assume conditions are clear; check the official alert page.</p>')
    out.append('<a class="source" href="https://www.weather.gov/hfo/" target="_blank" rel="noopener noreferrer">NWS Honolulu — current alerts ↗</a></article>')
    return ''.join(out)


def original_spotlight(template: str) -> str:
    # Preserve the user's already phone-tested Azores photographs, credits and illustrations.
    pattern = r'(<article class="feature"><div class="eyebrow">Destination spotlight.*?</article>)'
    m = re.search(pattern, template, flags=re.S)
    if not m:
        raise ValueError('Approved travel spotlight missing from locked template; refusing to redesign')
    return m.group(1)


def travel_html(feeds: dict[str, list[dict]], now: datetime, template: str) -> str:
    out = ['<h2 class="banner" id="travel">✈️ Travel Desk &amp; The Azores Escape</h2>']
    recent = [x for x in feeds.get('travel', []) if -timedelta(hours=2) <= now.astimezone(timezone.utc) - x['time'] <= timedelta(hours=72)]
    if recent:
        out.append(card('✈️ Travel news', recent[0], now))
    else:
        out.append('<article class="story"><div class="eyebrow">✈️ Travel desk</div><h3>Travel headlines unavailable</h3><p>No recent dated travel feed item could be verified at publication time. Check official travel advisories before booking.</p><a class="source" href="https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html" target="_blank" rel="noopener noreferrer">U.S. State Department travel advisories ↗</a></article>')
    out.append(original_spotlight(template))
    return ''.join(out)


def food_html(issue: datetime) -> str:
    title, serves, minutes, ingredients, steps = RECIPES[issue.toordinal() % len(RECIPES)]
    return ('<h2 class="banner" id="food">🍽️ Food &amp; Life</h2>'
            '<article class="feature recipe"><div class="eyebrow">From the kitchen • Quick &amp; practical</div>'
            f'<h3>{escape(title)}</h3><p><strong>Serves:</strong> {serves} • <strong>Time:</strong> {escape(minutes)}</p>'
            f'<p><strong>What you need:</strong> {escape(ingredients)}</p><p><strong>How:</strong> {escape(steps)}</p>'
            '<p class="small">Food note: adjust ingredients and portions to individual digestive and dietary needs; this is not a medical diet plan.</p></article>'
            '<article class="story"><div class="eyebrow">🌿 Small life upgrade</div><h3>One practical thing before noon</h3>'
            '<p>Charge the phone, drink some water, and check the forecast before making the weather your personal enemy. The universe is not accepting complaints today.</p></article>')


def events_html() -> str:
    return ('<h2 class="banner" id="events">📅 Big Island: Things to Do</h2>'
            '<article class="story"><div class="eyebrow">🌺 Hawaiʻi Island only • Check current calendars</div>'
            '<h3>Find today’s local events</h3><p>Event dates, times and availability change. This automated edition does not invent a lineup when a live calendar cannot be verified.</p>'
            '<p><a class="source" href="https://www.gohawaii.com/islands/hawaii-big-island/events" target="_blank" rel="noopener noreferrer">Hawaiʻi Island events calendar ↗</a></p>'
            '<p><a class="source" href="https://bigislandnow.com/events/" target="_blank" rel="noopener noreferrer">Big Island Now events ↗</a></p></article>')


def apocalypse_html(issue: datetime) -> str:
    title, report, tip = APOCALYPSE[issue.toordinal() % len(APOCALYPSE)]
    meter = 1 + (issue.toordinal() % 5)
    marks = ''.join(f'<span class="{"on" if n < meter else ""}"></span>' for n in range(5))
    return ('<h2 class="banner" id="apocalypse">☢️ The Apocalypse Update</h2>'
            '<article class="apocalypse-desk" aria-label="Satirical apocalypse update">'
            f'<div class="eyebrow">⚠️ APOCALYPSE DESK • {escape(issue.strftime("%B %-d").upper())} • ENTIRELY UNOFFICIAL</div>'
            f'<h3>{escape(title)}</h3><p><strong>Situation report:</strong> {escape(report)}</p>'
            f'<div class="apocalypse-meter" role="img" aria-label="Fictional, unscientific apocalypse meter {meter} out of 5. Not a real emergency assessment.">'
            f'<div class="meter-label">☢️ THE COMPLETELY UNOFFICIAL APOCALYPSE METER</div><div class="meter-steps" aria-hidden="true">{marks}</div>'
            f'<strong>{meter} / 5 — Purely Fictional Nonsense</strong><div class="meter-note">This is satire, not a threat or disaster forecast.</div></div>'
            f'<p><strong>Felicia’s survival plan:</strong> {escape(tip)}</p>'
            '<p class="tiny-disclaimer">For actual alerts, consult NWS, Hawaiʻi County Civil Defense and other official agencies.</p></article>')


def jay_html(issue: datetime) -> str:
    title, tip, url = JAY_TIPS[issue.toordinal() % len(JAY_TIPS)]
    return ('<h2 class="banner" id="jay">⚡ Jay’s Corner: Farm Survival &amp; Preparedness</h2>'
            '<article class="feature"><div class="eyebrow">Farm life • Practical gear, not marketing magic</div>'
            f'<h3>{escape(title)}</h3><p>{escape(tip)}</p>'
            '<p>Jay’s farm gets rain, sun and unpredictable access to generator power. Gear needs to work in those conditions, not just look impressive in a product photo.</p>'
            f'<a class="source" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">Preparedness reference ↗</a></article>')


def horoscope_html(issue: datetime) -> str:
    i = issue.toordinal() % 7
    return ('<h2 class="banner">🔮 The Stars Have Opinions</h2>'
            '<article class="feature horoscope"><div class="eyebrow">Pisces &amp; Gemini • Just for fun, not a prediction</div>'
            f'<p><strong>♓ Pisces — Felicia:</strong> {escape(PISCES[i])}</p>'
            f'<p><strong>♊ Gemini — Jay:</strong> {escape(GEMINI[i])}</p>'
            '<p class="small">Astrology is entertainment. The only thing we can reliably forecast is another round of nonsense.</p></article>')


def build(template: str, issue: datetime, feeds: dict[str, list[dict]]) -> tuple[str, int]:
    if not re.search(r'<main>.*?</main>', template, flags=re.S):
        raise ValueError('Locked template is missing its main section')
    if template.count('class="approved-mast-art"') != 1:
        raise ValueError('Approved masthead missing or duplicated')
    new_news, count = news_html(feeds, issue)
    intro = INTRO[issue.toordinal() % len(INTRO)]
    generated = issue.strftime('%B %-d, %Y, %-I:%M %p HST')
    main = (f'<main><div class="intro">{escape(intro)}</div>'
            f'<div class="archive-note current-note" role="note"><strong>DAILY WEBSITE EDITION • {escape(issue.strftime("%B %-d, %Y").upper())}.</strong> '
            f'Automatically assembled from dated publisher feeds and forecast sources at {escape(generated)}. '
            'This is a separate, source-linked digest; it may differ from the ChatGPT editorial edition. No comic.</div>'
            '<aside class="editorial-eye-roll" aria-label="Editor’s opening comment"><strong>☕ From the editor’s desk</strong>'
            'The news has been gathered. The coffee is doing its best. We are all making questionable decisions, but at least these headlines have links.</aside>'
            + new_news + weather_html(issue) + travel_html(feeds, issue, template)
            + food_html(issue) + events_html() + apocalypse_html(issue) + jay_html(issue) + horoscope_html(issue)
            + '</main>')
    html = re.sub(r'<main>.*?</main>', lambda m: main, template, count=1, flags=re.S)
    date_full = issue.strftime('%A, %B %-d, %Y')
    date_short = issue.strftime('%b %-d, %Y').upper()
    html = re.sub(r'(<h1 class="sr-only">).*?(</h1>)', lambda m: m.group(1) + 'The Daily What the Hell? — ' + escape(date_full) + m.group(2), html, count=1)
    html = re.sub(r'(<div class="edition-datebar"><span>.*?</span><span>).*?(</span></div>)', lambda m: m.group(1) + escape(date_short) + ' • HAWAIʻI TIME' + m.group(2), html, count=1, flags=re.S)
    html = re.sub(r'<title>.*?</title>', lambda m: '<title>The Daily WHAT THE HELL? | ' + escape(date_full) + ' | Island Phone Edition</title>', html, count=1)
    html = re.sub(r'<footer>.*?</footer>', lambda m: (
        '<footer><p class="edition-disclaimer">Automatically compiled from dated publisher RSS feeds, Open-Meteo forecast data and the NWS alert API. '
        'This digest is not an emergency notification service. Source information may change after publication; always follow original links and official alerts. '
        'The travel spotlight is an evergreen feature; genuine photos load online from Wikimedia Commons. The ChatGPT editorial edition is separate.</p>'
        '<a href="#top">↑ Back to top</a>'
        f'<p>THE DAILY WHAT THE HELL? • {escape(date_full)} • Hawaiʻi time</p>'
        '<p>If you made it to the bottom, congratulations. Civilization survived another issue.</p></footer>'), html, count=1, flags=re.S)
    # Verify the exact locked banner's base64 remains byte-identical to the original template.
    banner_pattern = r'<img[^>]*class="approved-mast-art"[^>]*>'
    a = re.search(banner_pattern, template)
    b = re.search(banner_pattern, html)
    if not a or not b or a.group(0) != b.group(0):
        raise ValueError('LOCK VIOLATION: original masthead changed')
    if 'class="destination-photo"' not in html or 'id="weather"' not in html:
        raise ValueError('Required travel photos or two-island weather section missing')
    return html, count


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--template', default='index.html')
    p.add_argument('--output', default='public/index.html')
    p.add_argument('--test-fixture', default=None, help='Local offline test only; never use for public deployment')
    args = p.parse_args()
    template = Path(args.template).read_text(encoding='utf-8')
    now = datetime.now(HST)
    if args.test_fixture:
        data = json.loads(Path(args.test_fixture).read_text(encoding='utf-8'))
        feeds = {}
        for k, items in data.items():
            feeds[k] = [{**x, 'time': parse_timestamp(x['time'])} for x in items]
    else:
        feeds = load_feeds()
    html, count = build(template, now, feeds)
    if count < 5 and not args.test_fixture:
        raise SystemExit(f'Only {count} recent verified news headlines retrieved. Refusing to replace live website with an incomplete issue.')
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    print(f'Built {out}: {len(html.encode("utf-8"))} bytes; {count} recent news cards; {now.isoformat()}')


if __name__ == '__main__':
    main()
