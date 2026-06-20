import json

# Read current watchlist
with open("app/data/watchlist.json", "r", encoding="utf-8") as f:
    watchlist = json.load(f)

replacements = {
    "elektronika/telefony-i-aksesuary/mobilnye-telefony-i-aksesuary/mobilnye-telefony/": "elektronika/telefony-i-aksesuary/",
    "elektronika/igrovye-pristavki-i-igry/pristavki/": "elektronika/igry-i-igrovye-pristavki/",
    "elektronika/kompyutery-i-komplektuyuschie/noutbuki-i-aksesuary/noutbuki/": "elektronika/kompyutery-i-komplektuyuschie/",
    "transport/velosipedy-i-samokaty/elektrosamokaty-i-giroscootery/": "transport/",
    "sport-i-hobbi/velosipedy/": "hobbi-otdyh-i-sport/",
    "dom-i-sad/instrumenty-i-oborudovanie/": "dom-i-sad/",
    "detskiy-mir/avtokresla/": "detskiy-mir/",
    "moda-i-stil/obuv/": "moda-i-stil/",
}

updated_count = 0
for item in watchlist:
    old_url = item["search_url"]
    new_url = old_url
    for old_segment, new_segment in replacements.items():
        if old_segment in new_url:
            new_url = new_url.replace(old_segment, new_segment)
    
    if new_url != old_url:
        item["search_url"] = new_url
        updated_count += 1
        print(f"Updated {item['id']}:")
        print(f"  Old: {old_url}")
        print(f"  New: {new_url}")

# Write back
with open("app/data/watchlist.json", "w", encoding="utf-8") as f:
    json.dump(watchlist, f, indent=2, ensure_ascii=False)

print(f"\nSuccessfully updated {updated_count} watchlist items!")
