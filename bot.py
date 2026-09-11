import os
import asyncio
import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# =========================
# CONFIGURATION
# =========================

TELEGRAM_TOKEN = (
    os.environ["TELEGRAM_TOKEN"]
    .replace("\n", "")
    .replace("\r", "")
    .strip()
)

# Ton identifiant Telegram doit être ajouté dans Railway.
# Nom de variable : TELEGRAM_CHAT_ID
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

CHECK_EVERY_SECONDS = 180  # 3 minutes

SEEN_FILE = Path("seen.json")


BRANDS = [
    "Nike",
    "Adidas",
    "Ralph Lauren",
    "Lacoste",
    "Carhartt",
    "Carhartt WIP",
    "The North Face",
    "Stone Island",
    "New Balance",
    "Polo Sport",
    "Arc'teryx",
    "Ami Paris",
    "Jacquemus",
    "Moncler",
    "Canada Goose",
    "Prada",
    "Louis Vuitton",
    "Dior",
    "Gucci",
    "Burberry",
    "Balenciaga",
]

# Plafonds
COMMON_MAX = 25
PREMIUM_MAX = 60
LUXURY_MAX = 90

PREMIUM = {
    "Stone Island",
    "Arc'teryx",
    "Ami Paris",
    "Jacquemus",
}

LUXURY = {
    "Moncler",
    "Canada Goose",
    "Prada",
    "Louis Vuitton",
    "Dior",
    "Gucci",
    "Burberry",
    "Balenciaga",
}


# =========================
# OUTILS
# =========================

def load_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(seen):
    # On garde seulement les 5000 dernières annonces
    values = list(seen)[-5000:]
    SEEN_FILE.write_text(json.dumps(values))


def price_limit(brand):
    if brand in LUXURY:
        return LUXURY_MAX

    if brand in PREMIUM:
        return PREMIUM_MAX

    return COMMON_MAX


def find_brand(text):
    text_lower = text.lower()

    for brand in BRANDS:
        if brand.lower() in text_lower:
            return brand

    return None


def extract_price(text):
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*€", text)

    if not match:
        return None

    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


# =========================
# VINTED
# =========================

SEARCH_URL = (
    "https://www.vinted.fr/catalog?"
    "search_text={brand}"
    "&order=newest_first"
)


async def fetch_vinted(brand):
    url = SEARCH_URL.format(
        brand=brand.replace(" ", "%20")
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9",
    }

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers=headers,
    ) as client:

        response = await client.get(url)
        response.raise_for_status()

        return response.text


def parse_items(html, brand):
    soup = BeautifulSoup(html, "html.parser")

    items = []

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/items/" not in href:
            continue

        text = " ".join(link.stripped_strings)

        detected_brand = find_brand(text)

        if detected_brand is None:
            continue

        if detected_brand.lower() != brand.lower():
            continue

        price = extract_price(text)

        if price is None:
            continue

        if price > price_limit(detected_brand):
            continue

        full_url = href

        if full_url.startswith("/"):
            full_url = "https://www.vinted.fr" + full_url

        items.append({
            "id": full_url,
            "brand": detected_brand,
            "price": price,
            "text": text[:500],
            "url": full_url,
        })

    return items


# =========================
# TELEGRAM
# =========================

async def send_deal(app, item):
    if not CHAT_ID:
        print("TELEGRAM_CHAT_ID n'est pas configuré.")
        return

    message = (
        "🔥 NOUVELLE PÉPITE VINTED 🔥\n\n"
        f"🏷️ {item['brand']}\n"
        f"💰 {item['price']:.2f} €\n\n"
        f"{item['text']}\n\n"
        f"👉 {item['url']}"
    )

    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        disable_web_page_preview=False,
    )


# =========================
# SURVEILLANCE
# =========================

async def monitor(app):
    seen = load_seen()

    print("🔥 Surveillance Vinted démarrée.")

    while True:

        for brand in BRANDS:

            try:
                html = await fetch_vinted(brand)
                items = parse_items(html, brand)

                # Les résultats sont parcourus du plus récent au plus ancien.
                for item in reversed(items):

                    item_id = item["id"]

                    if item_id in seen:
                        continue

                    seen.add(item_id)

                    await send_deal(app, item)

                save_seen(seen)

            except Exception as e:
                print(f"Erreur {brand}: {e}")

            # On évite d'enchaîner trop rapidement les requêtes.
            await asyncio.sleep(3)

        await asyncio.sleep(CHECK_EVERY_SECONDS)


# =========================
# COMMANDES TELEGRAM
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔥 Vinted Pépite Bot est connecté !\n\n"
        "La surveillance des bonnes affaires est activée 👀"
    )


# =========================
# DÉMARRAGE
# =========================

async def post_init(app):
    asyncio.create_task(monitor(app))


def main():

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
