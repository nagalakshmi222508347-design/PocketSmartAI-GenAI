"""All Gemini prompt logic + fallback recommendations + product links."""
import json
import os
import re
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

try:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=API_KEY) if API_KEY else None
except Exception:  # SDK missing or bad key -> fallback mode
    client = None

# Search-link templates (safe "simulated" platform links; no scraping)
LINKS = {
    "amazon": "https://www.amazon.in/s?k={}",
    "flipkart": "https://www.flipkart.com/search?q={}",
    "ikea": "https://www.ikea.com/in/en/search/?q={}",
    "swiggy": "https://www.swiggy.com/search?query={}",
    "oyo": "https://www.oyorooms.com/search?location={}",
}

SCHEMA = """Return ONLY valid JSON (no markdown) in this exact shape:
{"summary": "2 sentence overview",
 "items": [{"category": "...", "name": "specific product/service", "platform": "Amazon|Flipkart|IKEA|Swiggy|Zomato|OYO",
            "price": <number in INR>, "reason": "one short sentence"}],
 "tips": ["short money-saving tip", "..."]}
Rules: prices are in Indian Rupees (INR); the SUM of all item prices must NOT exceed the budget; 5-10 items."""


def link_for(platform: str, name: str) -> str:
    key = (platform or "").lower().strip()
    if key in LINKS:
        return LINKS[key].format(quote_plus(name))
    return "https://www.google.com/search?q=" + quote_plus(f"{name} {platform}")


def _ask(prompt, image=None):
    if client is None:
        raise RuntimeError("Gemini client not configured")
    parts = [prompt]
    if image:
        parts.insert(0, types.Part.from_bytes(data=image[0], mime_type=image[1]))
    resp = client.models.generate_content(
        model=MODEL, contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.6))
    text = re.sub(r"^```(?:json)?|```$", "", resp.text.strip(), flags=re.M).strip()
    return json.loads(text)


def _finish(data, budget, source):
    items = []
    for it in data.get("items", []):
        try:
            price = float(it.get("price", 0))
        except (TypeError, ValueError):
            continue
        it["price"] = round(price)
        it["link"] = link_for(it.get("platform", ""), it.get("name", ""))
        items.append(it)
    if not items:
        raise ValueError("AI returned no items")
    total = sum(i["price"] for i in items)
    return {"summary": data.get("summary", ""), "items": items, "tips": data.get("tips", []),
            "total": total, "budget": round(budget), "remaining": round(budget - total),
            "over_budget": total > budget, "source": source}


def _run(prompt, budget, fallback, image=None):
    try:
        return _finish(_ask(prompt, image), budget, "Gemini AI")
    except Exception as e:  # any failure -> safe default (Activity 5.4)
        print("Gemini fallback used:", e)
        return _finish(fallback(), budget, "Fallback (offline defaults)")


# ------------------------------------------------------------------ HOME
def home_recommendations(budget, style, rooms):
    desc = "; ".join(f"{r['room']}: {r['lights']} lights, {r['fans']} ceiling fans, {r['tables']} dining tables"
                     for r in rooms)
    prompt = (f"You are PocketSmart AI, a home-interior budget planner for India.\n"
              f"Total budget: INR {budget}. Style: {style}.\nRooms & quantities: {desc}.\n"
              f"Recommend cost-effective products from IKEA, Amazon and Flipkart balancing function, style and price.\n{SCHEMA}")

    def fallback():
        base = {"lights": ("LED ceiling light", 900, "Amazon"), "fans": ("BLDC ceiling fan", 3000, "Flipkart"),
                "tables": ("4-seater dining table", 9000, "IKEA")}
        rows = []
        for r in rooms:
            for k, (n, p, pf) in base.items():
                if int(r[k]) > 0:
                    rows.append({"category": r["room"], "name": f"{n} x{r[k]}", "platform": pf,
                                 "price": p * int(r[k]), "reason": f"Reliable {style} choice for {r['room']}."})
        raw = sum(x["price"] for x in rows) or 1
        f = min(1, budget * 0.95 / raw)
        for x in rows:
            x["price"] = x["price"] * f
        return {"summary": "Default plan scaled to your budget.", "items": rows,
                "tips": ["Compare prices on 2 platforms.", "Buy during festival sales."]}
    return _run(prompt, budget, fallback)


# ------------------------------------------------------------------ PARTY
def party_recommendations(budget, guests, event_type, venue, city):
    prompt = (f"You are PocketSmart AI, a party budget planner for India.\n"
              f"Event: {event_type}. Guests: {guests}. Venue: {venue}. City: {city}. Budget: INR {budget}.\n"
              f"Split the budget across catering, decoration and entertainment (and stay/venue if needed) "
              f"and suggest options from Swiggy, Zomato, OYO, Amazon. Tailor to the event type.\n{SCHEMA}")

    def fallback():
        split = [("Catering", .50, "Swiggy", f"Catering for {guests} guests"),
                 ("Decoration", .20, "Amazon", f"{event_type} decoration kit"),
                 ("Entertainment", .15, "Zomato", "DJ / music & games"),
                 ("Venue / Stay", .12, "OYO", f"Venue or rooms in {city}")]
        return {"summary": f"Standard split for a {event_type} party.",
                "items": [{"category": c, "name": n, "platform": p, "price": budget * s,
                           "reason": f"{int(s*100)}% of budget."} for c, s, p, n in split],
                "tips": ["Book vendors 2 weeks ahead.", "Ask for bundle discounts."]}
    return _run(prompt, budget, fallback)


# ------------------------------------------------------------------ JEWELRY
def jewelry_recommendations(budget, occasion, style, image=None):
    img_note = "An outfit image is attached: match colours and neckline." if image else "No outfit image given."
    prompt = (f"You are PocketSmart AI, a jewelry stylist.\nOccasion: {occasion}. Style: {style}. "
              f"Budget: INR {budget}. {img_note}\nSuggest matching jewelry sets/pieces from Amazon and Flipkart.\n{SCHEMA}")

    def fallback():
        parts = [("Necklace", .35, "Amazon"), ("Earrings", .25, "Flipkart"),
                 ("Bracelet / Bangles", .25, "Amazon"), ("Ring", .10, "Flipkart")]
        return {"summary": f"A balanced {style} set for a {occasion}.",
                "items": [{"category": c, "name": f"{style} {c.lower()} for {occasion}", "platform": p,
                           "price": budget * s, "reason": "Fits the occasion and budget."} for c, s, p in parts],
                "tips": ["Pick one statement piece, keep the rest simple."]}
    return _run(prompt, budget, fallback, image)
