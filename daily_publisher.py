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
UA = 'TheDailyWhatTheHell/1.1 (https://fmpettinato-hash.github.io/the-daily-what-the-hell/; public news and photo attribution)'
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

# Sixty-five DIFFERENT practical gear items, selected by Hawaiʻi-local date.
# This is a category spotlight, NOT an unverified product endorsement or price quote.
# It covers power, radio, rain, lighting, field safety, water and preparedness.
JAY_GEAR_CATALOG = [{'title': 'Hand-crank emergency radio',
  'why': 'Listen for alerts when power is unavailable.',
  'check': 'Check AM/FM reception, NOAA weather-band support, crank output and rain protection.',
  'photo_search': 'emergency crank radio',
  'photo_keywords': ('radio', 'eton'),
  'reference': 'https://www.weather.gov/nwr/'},
 {'title': 'Portable AM/FM radio',
  'why': 'Keep local broadcasts available without using a phone.',
  'check': 'Check reception, replaceable batteries and speaker volume.',
  'photo_search': 'portable radio transistor',
  'photo_keywords': ('radio', 'transistor'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'NOAA weather radio',
  'why': 'Receive official weather broadcasts when cellular service is unreliable.',
  'check': 'Check weather-band coverage, alerts and battery backup.',
  'photo_search': 'weather alert radio',
  'photo_keywords': ('radio', 'weather'),
  'reference': 'https://www.weather.gov/nwr/'},
 {'title': 'USB-C power bank',
  'why': 'Recharge a phone while the generator is off.',
  'check': 'Compare usable watt-hours, output watts, USB-C PD and rain protection.',
  'photo_search': 'portable power bank battery',
  'photo_keywords': ('powerbank', 'power bank', 'anker'),
  'reference': 'https://www.ready.gov/power-outages'},
 {'title': 'Solar power bank',
  'why': 'Add slow solar top-ups to an ordinary phone backup battery.',
  'check': 'Treat tiny built-in panels as emergency trickle chargers, not all-day power.',
  'photo_search': 'solar power bank',
  'photo_keywords': ('solar', 'powerbank'),
  'reference': 'https://www.ready.gov/power-outages'},
 {'title': 'Portable power station',
  'why': 'Run small devices when there is no outlet nearby.',
  'check': 'Check watt-hours, AC output, charging speed and whether it must stay dry.',
  'photo_search': 'Jackery Explorer portable power station',
  'photo_keywords': ('jackery', 'explorer', 'ecoflow'),
  'reference': 'https://www.ready.gov/power-outages'},
 {'title': 'Folding solar panel',
  'why': 'Harvest daylight to charge compatible batteries.',
  'check': 'Verify output, connectors, shade tolerance and water-exposure rating.',
  'photo_search': 'folding portable solar panel',
  'photo_keywords': ('solar', 'panel'),
  'reference': 'https://www.energy.gov/energysaver/solar-energy'},
 {'title': 'Solar charge controller',
  'why': 'Protect a compatible battery while charging from a solar panel.',
  'check': 'Match battery chemistry, voltage, input limits and connector type.',
  'photo_search': 'solar charge controller',
  'photo_keywords': ('controller', 'solar'),
  'reference': 'https://www.energy.gov/energysaver/solar-energy'},
 {'title': 'Waterproof dry bag',
  'why': 'Keep a radio, cables and clothing away from farm rain.',
  'check': 'Check the closure method and actual immersion rating; do not assume all dry bags are submersible.',
  'photo_search': 'waterproof dry bag camping',
  'photo_keywords': ('dry bag', 'drybag'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Waterproof phone pouch',
  'why': 'Protect a phone from rain and splashes.',
  'check': 'Check IP rating, seal quality and whether the screen works through the pouch.',
  'photo_search': 'waterproof phone pouch',
  'photo_keywords': ('phone', 'pouch', 'waterproof'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Waterproof hard case',
  'why': 'Transport delicate electronics in a tougher sealed enclosure.',
  'check': "Check gasket condition, latches and the case's tested IP rating.",
  'photo_search': 'Pelican waterproof case',
  'photo_keywords': ('pelican', 'case'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Backpack rain cover',
  'why': 'Keep a work backpack drier during sudden showers.',
  'check': 'Check pack volume, seam coverage and how securely it attaches.',
  'photo_search': 'backpack rain cover',
  'photo_keywords': ('backpack', 'cover'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Rechargeable headlamp',
  'why': 'Keep both hands free while checking equipment after dark.',
  'check': 'Check runtime at useful brightness, strap comfort and water resistance.',
  'photo_search': 'LED headlamp camping',
  'photo_keywords': ('headlamp', 'headlight'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'LED flashlight',
  'why': 'Provide dependable light when the generator is off.',
  'check': 'Check replaceable batteries, beam modes and water resistance.',
  'photo_search': 'LED flashlight torch',
  'photo_keywords': ('flashlight', 'torch'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Rechargeable camping lantern',
  'why': 'Light a work area without using a phone flashlight.',
  'check': 'Check actual low-mode runtime and charging port protection.',
  'photo_search': 'camping LED lantern',
  'photo_keywords': ('lantern',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Solar camping lantern',
  'why': 'Offer a small area light with daytime charging.',
  'check': "Compare solar recharge time with the battery's usable runtime.",
  'photo_search': 'solar camping lantern',
  'photo_keywords': ('lantern', 'solar'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Magnetic work light',
  'why': 'Stick task lighting to a suitable metal surface for repairs.',
  'check': 'Check magnet strength, runtime and whether the housing tolerates rain.',
  'photo_search': 'magnetic LED work light',
  'photo_keywords': ('work light', 'magnetic'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Rechargeable AA batteries',
  'why': 'Keep compatible radios and flashlights running without disposable cells.',
  'check': 'Check chemistry, device compatibility and proper storage.',
  'photo_search': 'rechargeable AA batteries',
  'photo_keywords': ('battery', 'batteries'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'AA battery charger',
  'why': 'Recharge standard cells when AC or solar power is available.',
  'check': 'Check chemistry support and whether each cell charges independently.',
  'photo_search': 'AA battery charger',
  'photo_keywords': ('charger', 'battery'),
  'reference': 'https://www.ready.gov/power-outages'},
 {'title': 'Battery storage case',
  'why': 'Prevent loose spare batteries from contacting metal objects.',
  'check': 'Use a dedicated case and protect terminals from short circuits.',
  'photo_search': 'battery storage box',
  'photo_keywords': ('battery', 'case'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': '12-volt car USB charger',
  'why': 'Charge a phone from a vehicle when needed.',
  'check': 'Check USB-C PD wattage and whether the vehicle socket is powered with engine off.',
  'photo_search': 'car USB charger',
  'photo_keywords': ('car', 'charger'),
  'reference': 'https://www.ready.gov/power-outages'},
 {'title': 'Portable vehicle jump starter',
  'why': 'Help start a compatible vehicle with a weak battery.',
  'check': "Match engine size and follow the manufacturer's safe connection procedure.",
  'photo_search': 'portable car jump starter',
  'photo_keywords': ('jump', 'starter'),
  'reference': 'https://www.ready.gov/car'},
 {'title': 'Portable tire inflator',
  'why': 'Restore tire pressure without finding an air station.',
  'check': 'Check power source, duty cycle and gauge accuracy.',
  'photo_search': 'portable tire inflator',
  'photo_keywords': ('inflator', 'compressor'),
  'reference': 'https://www.ready.gov/car'},
 {'title': 'Automotive fuse assortment',
  'why': 'Replace a correctly rated blown vehicle fuse.',
  'check': 'Use the exact specified amperage; never up-rate a fuse to stop it blowing.',
  'photo_search': 'automotive blade fuses',
  'photo_keywords': ('fuse', 'fuses'),
  'reference': 'https://www.ready.gov/car'},
 {'title': 'Handheld two-way radio',
  'why': 'Communicate nearby when cellular reception is unreliable.',
  'check': 'Check legal channel rules, range under terrain and battery endurance.',
  'photo_search': 'handheld two way radio walkie talkie',
  'photo_keywords': ('walkie', 'radio'),
  'reference': 'https://www.ready.gov/plan'},
 {'title': 'Handheld GPS receiver',
  'why': 'Navigate without relying entirely on a cellular data connection.',
  'check': 'Download maps beforehand and carry spare power.',
  'photo_search': 'Garmin handheld GPS receiver',
  'photo_keywords': ('garmin', 'gps'),
  'reference': 'https://www.ready.gov/plan'},
 {'title': 'Baseplate compass',
  'why': 'Provide simple backup navigation when batteries are gone.',
  'check': 'Check that the needle moves freely and learn to use it with a map.',
  'photo_search': 'baseplate compass navigation',
  'photo_keywords': ('compass',),
  'reference': 'https://www.ready.gov/plan'},
 {'title': 'Emergency whistle',
  'why': 'Signal for attention without draining a battery.',
  'check': 'Choose a durable whistle that can be reached quickly.',
  'photo_search': 'emergency safety whistle',
  'photo_keywords': ('whistle',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Signal mirror',
  'why': 'Reflect sunlight to attract attention from a distance.',
  'check': 'Practice aiming and store it where it will not scratch.',
  'photo_search': 'emergency signal mirror',
  'photo_keywords': ('mirror', 'signal'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'High-visibility safety vest',
  'why': 'Improve visibility around farm vehicles and machinery.',
  'check': 'Check reflective strip placement and appropriate fit.',
  'photo_search': 'high visibility reflective vest',
  'photo_keywords': ('vest', 'reflective'),
  'reference': 'https://www.osha.gov/personal-protective-equipment'},
 {'title': 'Protective safety glasses',
  'why': 'Keep dust and flying debris away from the eyes.',
  'check': 'Check impact markings and fit for the task.',
  'photo_search': 'protective safety glasses',
  'photo_keywords': ('glasses', 'goggles'),
  'reference': 'https://www.osha.gov/eye-and-face-protection'},
 {'title': 'Work gloves',
  'why': 'Protect hands during suitable farm and repair tasks.',
  'check': 'Match cut, abrasion and grip protection to the job; avoid loose gloves near rotating equipment.',
  'photo_search': 'work gloves protective',
  'photo_keywords': ('gloves',),
  'reference': 'https://www.osha.gov/hand-protection'},
 {'title': 'Rubber work boots',
  'why': 'Keep feet drier in muddy or wet conditions.',
  'check': 'Check traction, fit and whether safety toes are needed.',
  'photo_search': 'rubber Wellington boots',
  'photo_keywords': ('boots', 'wellington'),
  'reference': 'https://www.osha.gov/personal-protective-equipment'},
 {'title': 'Rain poncho',
  'why': 'Provide a quick layer during sudden downpours.',
  'check': 'Check hood coverage, ventilation and how it behaves around machinery.',
  'photo_search': 'rain poncho waterproof',
  'photo_keywords': ('poncho',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Wide-brim sun hat',
  'why': 'Add shade for long hours in direct sun.',
  'check': 'Check brim coverage, ventilation and a secure fit in wind.',
  'photo_search': 'wide brim sun hat',
  'photo_keywords': ('hat', 'sun'),
  'reference': 'https://www.cdc.gov/niosh/heat-stress/about/index.html'},
 {'title': 'Cooling towel',
  'why': 'Provide temporary cooling when working in heat.',
  'check': 'Pair with shade, water and rest; do not treat a towel as heat-illness protection by itself.',
  'photo_search': 'cooling towel sports',
  'photo_keywords': ('towel', 'cooling'),
  'reference': 'https://www.cdc.gov/niosh/heat-stress/about/index.html'},
 {'title': 'Insulated water bottle',
  'why': 'Keep drinking water accessible during outdoor work.',
  'check': "Choose a cleanable bottle sized for the day's conditions.",
  'photo_search': 'insulated stainless steel water bottle',
  'photo_keywords': ('bottle', 'flask'),
  'reference': 'https://www.ready.gov/water'},
 {'title': 'Collapsible water container',
  'why': 'Carry extra potable water when a tap is far away.',
  'check': 'Confirm food-safe material, capacity and cleaning instructions.',
  'photo_search': 'collapsible water container camping',
  'photo_keywords': ('water', 'container'),
  'reference': 'https://www.ready.gov/water'},
 {'title': 'Portable water filter',
  'why': 'Filter appropriate untreated water when needed.',
  'check': 'Check what pathogens the filter actually removes; many filters do not remove viruses.',
  'photo_search': 'portable water filter camping',
  'photo_keywords': ('filter', 'water'),
  'reference': 'https://www.cdc.gov/healthy-water-drinking/about/about-water-treatment-options.html'},
 {'title': 'Water purification tablets',
  'why': 'Provide a lightweight emergency water-treatment option.',
  'check': 'Follow label directions and understand chemical-treatment limitations.',
  'photo_search': 'water purification tablets',
  'photo_keywords': ('purification', 'tablet'),
  'reference': 'https://www.cdc.gov/healthy-water-drinking/about/about-water-treatment-options.html'},
 {'title': 'First-aid kit',
  'why': 'Keep common injury supplies in one accessible location.',
  'check': 'Check the contents and restock used or expired supplies.',
  'photo_search': 'first aid kit red',
  'photo_keywords': ('first aid', 'kit'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Elastic bandage',
  'why': 'Support a suitable minor strain or hold a dressing in place.',
  'check': 'Check size, cleanliness and avoid wrapping too tightly.',
  'photo_search': 'elastic bandage first aid',
  'photo_keywords': ('bandage',),
  'reference': 'https://www.redcross.org/get-help/how-to-prepare-for-emergencies/survival-kit-supplies.html'},
 {'title': 'Fine-tip tweezers',
  'why': 'Remove small splinters when appropriate.',
  'check': 'Keep them clean and seek care for deep or infected wounds.',
  'photo_search': 'tweezers tool',
  'photo_keywords': ('tweezers',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Emergency thermal blanket',
  'why': 'Reduce heat loss during an emergency.',
  'check': 'Know that thin foil blankets are wind barriers, not complete shelter.',
  'photo_search': 'emergency foil space blanket',
  'photo_keywords': ('blanket', 'space'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Mosquito head net',
  'why': 'Keep biting insects away from the face during field work.',
  'check': 'Check mesh density and fit over a brimmed hat.',
  'photo_search': 'mosquito head net',
  'photo_keywords': ('mosquito', 'net'),
  'reference': 'https://www.cdc.gov/mosquitoes/prevention/index.html'},
 {'title': 'Mosquito netting',
  'why': 'Add a physical insect barrier around a resting area.',
  'check': 'Inspect for holes and secure edges so insects cannot enter.',
  'photo_search': 'mosquito net bed',
  'photo_keywords': ('mosquito', 'net'),
  'reference': 'https://www.cdc.gov/mosquitoes/prevention/index.html'},
 {'title': 'Sunscreen bottle',
  'why': 'Keep broad-spectrum sun protection handy.',
  'check': 'Check SPF and reapplication directions; clothing and shade also matter.',
  'photo_search': 'sunscreen lotion bottle',
  'photo_keywords': ('sunscreen',),
  'reference': 'https://www.cdc.gov/skin-cancer/sun-safety/index.html'},
 {'title': 'Portable weather meter',
  'why': 'Measure local wind and other conditions near the worksite.',
  'check': "Check sensor accuracy and don't replace official alerts with a handheld reading.",
  'photo_search': 'handheld anemometer weather meter',
  'photo_keywords': ('anemometer', 'weather'),
  'reference': 'https://www.weather.gov/safety/'},
 {'title': 'Rain gauge',
  'why': 'Track rainfall around the farm over time.',
  'check': 'Place it away from roof runoff and read at consistent intervals.',
  'photo_search': 'rain gauge garden',
  'photo_keywords': ('rain', 'gauge'),
  'reference': 'https://www.weather.gov/'},
 {'title': 'Outdoor thermometer',
  'why': 'Check ambient conditions where work is being done.',
  'check': 'Keep sensors shaded from direct sun for useful air-temperature readings.',
  'photo_search': 'outdoor thermometer',
  'photo_keywords': ('thermometer',),
  'reference': 'https://www.cdc.gov/niosh/heat-stress/about/index.html'},
 {'title': 'Battery-powered fan',
  'why': 'Move air in a sheltered space when power is limited.',
  'check': 'Check runtime, charging requirements and whether conditions are safe for fan use.',
  'photo_search': 'portable rechargeable fan',
  'photo_keywords': ('fan', 'portable'),
  'reference': 'https://www.ready.gov/power-outages'},
 {'title': 'Fire extinguisher',
  'why': 'Keep appropriate fire response equipment accessible.',
  'check': 'Match extinguisher class to hazards and know when to evacuate instead.',
  'photo_search': 'portable fire extinguisher',
  'photo_keywords': ('extinguisher',),
  'reference': 'https://www.ready.gov/home-fires'},
 {'title': 'Smoke alarm',
  'why': 'Provide early warning of smoke inside a building.',
  'check': 'Test alarms and replace batteries or units as directed.',
  'photo_search': 'smoke detector alarm',
  'photo_keywords': ('smoke', 'detector'),
  'reference': 'https://www.ready.gov/home-fires'},
 {'title': 'Carbon monoxide alarm',
  'why': 'Warn about dangerous carbon monoxide near enclosed spaces.',
  'check': 'Never operate a generator indoors or near openings; an alarm is not a substitute for ventilation.',
  'photo_search': 'carbon monoxide detector alarm',
  'photo_keywords': ('carbon', 'detector'),
  'reference': 'https://www.cdc.gov/carbon-monoxide/about/index.html'},
 {'title': 'Outdoor-rated extension cord',
  'why': 'Reach a suitable outlet when the generator is running.',
  'check': 'Check load rating and outdoor suitability; keep connectors out of standing water.',
  'photo_search': 'outdoor extension cord',
  'photo_keywords': ('extension', 'cord'),
  'reference': 'https://www.esfi.org/'},
 {'title': 'Surge-protected power strip',
  'why': 'Protect compatible electronics against some power disturbances.',
  'check': 'Check load limits; never daisy-chain power strips or use them in rain.',
  'photo_search': 'surge protector power strip',
  'photo_keywords': ('surge', 'power strip'),
  'reference': 'https://www.esfi.org/'},
 {'title': 'Solar motion-sensor light',
  'why': 'Light a walkway or entrance without a nearby outlet.',
  'check': 'Check nighttime runtime, sensor range and weather rating.',
  'photo_search': 'solar motion sensor light',
  'photo_keywords': ('solar', 'light'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Waterproof field notebook',
  'why': 'Record observations even when hands and surroundings are damp.',
  'check': 'Check paper type and use a compatible pencil or pen.',
  'photo_search': 'Rite in the Rain notebook',
  'photo_keywords': ('notebook', 'rain'),
  'reference': 'https://www.ready.gov/plan'},
 {'title': 'Permanent marker',
  'why': 'Label containers, batteries and emergency supplies.',
  'check': 'Choose ink suitable for the surface and moisture conditions.',
  'photo_search': 'permanent marker pen',
  'photo_keywords': ('marker',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Duct tape roll',
  'why': 'Handle temporary noncritical repairs and labeling.',
  'check': 'Do not use tape as a substitute for rated electrical or structural repairs.',
  'photo_search': 'duct tape roll',
  'photo_keywords': ('tape', 'duct'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Paracord bundle',
  'why': 'Tie down light gear and organize camp supplies.',
  'check': 'Check working-load limits; paracord is not climbing or lifting rope.',
  'photo_search': 'paracord rope',
  'photo_keywords': ('paracord',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Carabiner clip',
  'why': 'Keep small tools or keys attached to a pack.',
  'check': 'Do not use non-rated accessory clips for climbing or life safety.',
  'photo_search': 'carabiner clip',
  'photo_keywords': ('carabiner',),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Ratchet tie-down straps',
  'why': 'Secure suitable loads during transport.',
  'check': 'Check working load limits and inspect straps for damage.',
  'photo_search': 'ratchet tie down straps',
  'photo_keywords': ('ratchet', 'straps'),
  'reference': 'https://www.ready.gov/car'},
 {'title': 'Heavy-duty storage tote',
  'why': 'Keep emergency supplies organized and protected from splashes.',
  'check': 'Check lid seal, stacking strength and whether contents need additional dry bags.',
  'photo_search': 'plastic storage tote box',
  'photo_keywords': ('storage', 'box'),
  'reference': 'https://www.ready.gov/kit'},
 {'title': 'Waterproof Bluetooth speaker',
  'why': 'Play music outdoors without risking the phone.',
  'check': 'Check verified IP rating and charging-port protection; rainproof is not automatically submersible.',
  'photo_search': 'waterproof bluetooth speaker',
  'photo_keywords': ('speaker', 'bluetooth'),
  'reference': 'https://www.ready.gov/kit'}]


def daily_gear(issue: datetime) -> dict:
    # 17 is coprime with 65: each item appears once in a 65-day cycle.
    return JAY_GEAR_CATALOG[(issue.date().toordinal() * 17) % len(JAY_GEAR_CATALOG)]


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


def _photo_extension(blob: bytes) -> str | None:
    if blob.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if blob.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if blob[:4] == b'RIFF' and blob[8:12] == b'WEBP':
        return '.webp'
    return None



def _relevant_gear_photo_title(item: dict, filename: str) -> bool:
    """Reject obvious non-gear imagery before using a Commons photo.

    Commons search ranks text relevance, not whether an image depicts usable
    equipment. A word like "goggles" in a costume photo is not evidence of
    protective eyewear. This is a conservative title check, not a certification.
    """
    title = filename.removeprefix('File:').lower().replace('_', ' ')
    bad_contexts = (
        'jenny everywhere', 'cosplay', 'costume', 'halloween', 'scarf',
        'fan art', 'fictional', 'cartoon', 'anime', 'character',
        'fashion show', 'movie poster', 'portrait', 'comic',
        'museum exhibit', 'advertising poster',
    )
    if any(bad in title for bad in bad_contexts):
        return False
    if not any(k in title for k in item['photo_keywords']):
        return False
    if item['title'] == 'Protective safety glasses':
        # Generic goggles can be swimwear, fashion or a costume accessory.
        # Require explicit occupational safety context in the file title.
        eyewear = ('glasses', 'goggles', 'spectacles', 'eyewear')
        safety = ('safety', 'protective', 'industrial', 'ppe',
                  'eye protection', 'workshop', 'work goggles')
        return any(k in title for k in eyewear) and any(k in title for k in safety)
    return True

def _wikimedia_photo(item: dict, output_dir: Path) -> dict | None:
    """Find an appropriately licensed REAL photograph and copy its bytes into the site.

    The live website uses a local relative image path, so readers see the
    photograph even if Wikimedia is temporarily unavailable afterward.
    """
    api = 'https://commons.wikimedia.org/w/api.php'
    for term in (item['photo_search'], item['title'], item['photo_keywords'][0]):
        params = {
            'action': 'query', 'generator': 'search', 'gsrsearch': 'filetype:bitmap ' + term,
            'gsrnamespace': 6, 'gsrlimit': 20, 'prop': 'imageinfo',
            'iiprop': 'url|mime|extmetadata', 'iiurlwidth': 720,
            'format': 'json', 'formatversion': 2,
        }
        try:
            payload = get_json(api + '?' + urlencode(params))
        except (OSError, ValueError, HTTPError, URLError, TimeoutError):
            continue
        pages = payload.get('query', {}).get('pages', [])
        for page in pages:
            title = page.get('title', '').lower()
            if any(bad in title for bad in ('logo', 'icon', 'vector', 'drawing', 'diagram', 'screenshot', 'illustration', 'emblem', 'svg')):
                continue
            if not _relevant_gear_photo_title(item, page.get('title', '')):
                continue
            infos = page.get('imageinfo') or []
            if not infos:
                continue
            info = infos[0]
            if info.get('mime') not in ('image/jpeg', 'image/png', 'image/webp'):
                continue
            meta = info.get('extmetadata') or {}
            license_name = strip_markup(meta.get('LicenseShortName', {}).get('value', ''))[:80]
            upper = license_name.upper()
            if not ('CC BY' in upper or 'CC0' in upper or 'PUBLIC DOMAIN' in upper or upper.startswith('PD-')):
                continue
            src = info.get('thumburl') or info.get('url', '')
            source = info.get('descriptionurl', '')
            if urlparse(src).hostname != 'upload.wikimedia.org' or urlparse(source).hostname != 'commons.wikimedia.org':
                continue
            try:
                blob = http_get(src)
            except (OSError, ValueError, HTTPError, URLError, TimeoutError):
                continue
            ext = _photo_extension(blob)
            if not ext or len(blob) < 5000 or len(blob) > 1_000_000:
                continue
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = 'jay-gear-photo' + ext
            (output_dir / filename).write_bytes(blob)
            artist = strip_markup(meta.get('Artist', {}).get('value', ''))[:100] or 'Wikimedia Commons contributor'
            license_url = strip_markup(meta.get('LicenseUrl', {}).get('value', ''))
            if urlparse(license_url).scheme != 'https':
                license_url = source
            return {
                'item': item, 'src': filename,
                'alt': 'Photograph of ' + item['title'].lower(),
                'caption': page.get('title', '').removeprefix('File:').rsplit('.', 1)[0].replace('_', ' ')[:130],
                'artist': artist, 'license': license_name,
                'license_url': license_url, 'source': source,
            }
    return None


def select_daily_gear_photo(issue: datetime, output_dir: Path) -> dict:
    """Choose a different item daily and record recent features in the Pages artifact.

    The public history file is read back on the next run. If GitHub Pages is
    unavailable, deterministic date ordering still avoids intentional repeats.
    """
    history_url = ('https://fmpettinato-hash.github.io/the-daily-what-the-hell/'
                   'jay-gear-history.json?issue=' + issue.date().isoformat())
    try:
        old = json.loads(http_get(history_url).decode('utf-8'))
        if not isinstance(old, list):
            old = []
        old = [x for x in old if isinstance(x, dict) and isinstance(x.get('title'), str)
               and isinstance(x.get('date'), str)][-65:]
    except (OSError, ValueError, HTTPError, URLError, TimeoutError):
        old = []
    today = issue.date().isoformat()
    already_today = next((x['title'] for x in reversed(old) if x['date'] == today), None)
    recent = {x['title'] for x in old[-64:] if x['date'] != today}
    base = (issue.date().toordinal() * 17) % len(JAY_GEAR_CATALOG)
    # Same-day reruns keep the same item; otherwise favor today's scheduled item.
    ordered = ([g for g in JAY_GEAR_CATALOG if g['title'] == already_today]
               if already_today else [])
    ordered += [JAY_GEAR_CATALOG[(base + offset) % len(JAY_GEAR_CATALOG)]
                for offset in range(len(JAY_GEAR_CATALOG))]
    seen = set()
    attempts = 0
    for item in ordered:
        if item['title'] in seen or (item['title'] in recent and item['title'] != already_today):
            continue
        seen.add(item['title'])
        attempts += 1
        if attempts > 8:
            break
        found = _wikimedia_photo(item, output_dir)
        if found:
            history = [x for x in old if x['date'] != today]
            history.append({'date': today, 'title': item['title']})
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / 'jay-gear-history.json').write_text(
                json.dumps(history[-65:], ensure_ascii=False, indent=2), encoding='utf-8')
            return found
    raise RuntimeError('Could not verify a real, licensed photograph for a new Jay gear item; keeping prior edition online.')


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


def jay_html(issue: datetime, gear_photo: dict) -> str:
    item = gear_photo['item']
    if item['title'] not in {g['title'] for g in JAY_GEAR_CATALOG}:
        raise ValueError('Jay gear photo is not linked to a catalog item')
    picture = (
        '<figure class="jay-gear-figure" style="margin:14px 0 12px;">'
        '<div class="jay-gear-frame" style="width:100%;max-width:650px;'
        'margin:auto;background-color:#f4eee3;border-radius:12px;overflow:hidden;">'
        f'<img class="jay-gear-photo" src="{escape(gear_photo["src"], quote=True)}" '
        f'alt="{escape(gear_photo["alt"], quote=True)}" '
        'loading="lazy" decoding="async" width="720" height="540" '
        'style="display:block;width:100%;height:auto;max-height:420px;object-fit:contain;"/>'
        '</div>'
        f'<figcaption class="small" style="margin-top:6px;line-height:1.5;">'
        f'Photograph: {escape(gear_photo["caption"])}. '
        f'Credit: {escape(gear_photo["artist"])} · '
        f'<a href="{escape(gear_photo["license_url"], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(gear_photo["license"])}</a> · '
        f'<a href="{escape(gear_photo["source"], quote=True)}" target="_blank" rel="noopener noreferrer">Original photograph and license</a>. '
        'Photograph is an example of the gear category, not a tested product endorsement.</figcaption></figure>'
    )
    return ('<h2 class="banner" id="jay">⚡ Jay’s Corner: Farm Survival &amp; Preparedness</h2>'
            '<article class="feature"><div class="eyebrow">DAILY GEAR SPOTLIGHT • One different item each day</div>'
            f'<h3>{escape(item["title"])}</h3>' + picture +
            f'<p><strong>Why it matters on the farm:</strong> {escape(item["why"])}</p>'
            f'<p><strong>What to check:</strong> {escape(item["check"])}</p>'
            '<p class="small">Practical gear guidance, not a claim that any pictured model has been tested or is currently for sale. '
            'Always verify the exact model’s specifications and water-resistance rating.</p>'
            f'<a class="source" href="{escape(item["reference"], quote=True)}" target="_blank" rel="noopener noreferrer">Read the preparedness reference ↗</a></article>')


def horoscope_html(issue: datetime) -> str:
    i = issue.toordinal() % 7
    return ('<h2 class="banner">🔮 The Stars Have Opinions</h2>'
            '<article class="feature horoscope"><div class="eyebrow">Pisces &amp; Gemini • Just for fun, not a prediction</div>'
            f'<p><strong>♓ Pisces — Felicia:</strong> {escape(PISCES[i])}</p>'
            f'<p><strong>♊ Gemini — Jay:</strong> {escape(GEMINI[i])}</p>'
            '<p class="small">Astrology is entertainment. The only thing we can reliably forecast is another round of nonsense.</p></article>')


def build(template: str, issue: datetime, feeds: dict[str, list[dict]], gear_photo: dict) -> tuple[str, int]:
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
            + food_html(issue) + events_html() + apocalypse_html(issue) + jay_html(issue, gear_photo) + horoscope_html(issue)
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
    if 'class="destination-photo"' not in html or 'id="weather"' not in html or 'class="jay-gear-photo"' not in html:
        raise ValueError('Required travel photos, Jay gear photo, or two-island weather section missing')
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
    out = Path(args.output)
    if args.test_fixture:
        # Explicitly fake photo only for offline test fixtures, never for a live issue.
        gear_photo = {'item': daily_gear(now), 'src': 'test-photo-placeholder.jpg',
                      'alt': 'Offline test photo placeholder', 'caption': 'Test fixture',
                      'artist': 'Test fixture', 'license': 'CC0',
                      'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
                      'source': 'https://commons.wikimedia.org/'}
    else:
        gear_photo = select_daily_gear_photo(now, out.parent)
    html, count = build(template, now, feeds, gear_photo)
    if count < 5 and not args.test_fixture:
        raise SystemExit(f'Only {count} recent verified news headlines retrieved. Refusing to replace live website with an incomplete issue.')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    print(f'Built {out}: {len(html.encode("utf-8"))} bytes; {count} recent news cards; {now.isoformat()}')


if __name__ == '__main__':
    main()
