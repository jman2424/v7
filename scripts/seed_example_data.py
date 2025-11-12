#!/usr/bin/env python3
"""
Seed the EXAMPLE tenant data (idempotent).

Usage:
  python scripts/seed_example_data.py [--tenant EXAMPLE]

Writes:
  business/<TENANT>/{catalog.json,delivery.json,branches.json,store_info.json,faq.json,
                     synonyms.json,overrides.json,branding.json}
"""

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUSINESS = ROOT / "business"

CATALOG = {
  "version": "2025-11-09",
  "currency": "GBP",
  "categories": [
    {"id": "POULTRY","name": "Poultry","items": [
      {"sku":"CHICK_BREAST_1KG","name":"Chicken Breast Fillets (1kg)","unit":"kg","price":8.99,"in_stock":True,"tags":["chicken","breast","fillet","lean","bbq","grill"]},
      {"sku":"CHICK_THIGH_1KG","name":"Chicken Thigh (Bone-in, 1kg)","unit":"kg","price":6.49,"in_stock":True,"tags":["chicken","thigh","bbq","stew"]},
      {"sku":"CHICK_WINGS_1KG","name":"Chicken Wings (1kg)","unit":"kg","price":5.99,"in_stock":True,"tags":["chicken","wings","bbq","party"]},
      {"sku":"CHICK_DRUM_1KG","name":"Chicken Drumsticks (1kg)","unit":"kg","price":5.79,"in_stock":True,"tags":["chicken","drumstick","bbq"]},
      {"sku":"CHICK_WHOLE_1_3KG","name":"Whole Chicken (1.3–1.5kg)","unit":"each","price":6.99,"in_stock":True,"tags":["chicken","whole","roast"]},
      {"sku":"TURKEY_MINCE_500G","name":"Turkey Mince (5% fat, 500g)","unit":"pack","price":4.49,"in_stock":True,"tags":["turkey","mince","lean"]}
    ]},
    {"id":"LAMB","name":"Lamb","items":[
      {"sku":"LAMB_SHOULDER_BONEIN_1KG","name":"Lamb Shoulder (Bone-in, 1kg)","unit":"kg","price":12.99,"in_stock":True,"tags":["lamb","shoulder","roast","slow-cook"]},
      {"sku":"LAMB_LEG_BONELESS_1KG","name":"Lamb Leg (Boneless, 1kg)","unit":"kg","price":14.49,"in_stock":True,"tags":["lamb","leg","roast","bbq"]},
      {"sku":"LAMB_CHOPS_1KG","name":"Lamb Chops (1kg)","unit":"kg","price":16.99,"in_stock":True,"tags":["lamb","chop","bbq","grill"]},
      {"sku":"LAMB_MINCE_10FAT_500G","name":"Lamb Mince (10% fat, 500g)","unit":"pack","price":5.49,"in_stock":True,"tags":["lamb","mince","kebab","kofta","bbq"]},
      {"sku":"MUTTON_STEW_1KG","name":"Mutton Stewing Pieces (1kg)","unit":"kg","price":9.99,"in_stock":True,"tags":["mutton","stew","curry","slow-cook"]}
    ]},
    {"id":"BEEF","name":"Beef","items":[
      {"sku":"BEEF_MINCE_5FAT_500G","name":"Beef Mince (5% fat, 500g)","unit":"pack","price":4.99,"in_stock":True,"tags":["beef","mince","lean","burger","bolognese"]},
      {"sku":"BEEF_RUMP_STEAK_1KG","name":"Rump Steak (1kg)","unit":"kg","price":17.99,"in_stock":True,"tags":["beef","steak","grill","bbq"]},
      {"sku":"BEEF_BRISKET_1KG","name":"Brisket (1kg)","unit":"kg","price":10.99,"in_stock":True,"tags":["beef","brisket","slow-cook","smoke","bbq"]},
      {"sku":"BEEF_STEWING_1KG","name":"Beef Stewing Pieces (1kg)","unit":"kg","price":9.49,"in_stock":True,"tags":["beef","stew","curry"]}
    ]},
    {"id":"BBQ_READY","name":"BBQ & Ready-to-Cook","items":[
      {"sku":"CHICK_WINGS_MARINATED_1KG","name":"Marinated Chicken Wings (BBQ, 1kg)","unit":"kg","price":6.79,"in_stock":True,"tags":["bbq","wings","marinated","party"]},
      {"sku":"CHICK_DRUM_MARINATED_1KG","name":"Marinated Drumsticks (Peri-Peri, 1kg)","unit":"kg","price":6.49,"in_stock":True,"tags":["bbq","drumstick","marinated","spicy"]},
      {"sku":"LAMB_KEBAB_SKEWERS_6PK","name":"Lamb Kofta Skewers (6 pcs)","unit":"pack","price":7.99,"in_stock":True,"tags":["lamb","kofta","skewer","bbq"]},
      {"sku":"BEEF_BURGER_PATTIES_4PK","name":"Beef Burger Patties (4 pcs)","unit":"pack","price":5.99,"in_stock":True,"tags":["beef","burger","bbq","grill"]}
    ]},
    {"id":"GROCERIES","name":"Groceries & Essentials","items":[
      {"sku":"BBQ_SAUCE_500ML","name":"BBQ Sauce (500ml)","unit":"bottle","price":2.49,"in_stock":True,"tags":["sauce","bbq","condiment"]},
      {"sku":"PERI_PERI_SAUCE_350ML","name":"Peri-Peri Sauce (350ml)","unit":"bottle","price":2.99,"in_stock":True,"tags":["sauce","peri-peri","spicy"]},
      {"sku":"CHARCOAL_5KG","name":"Charcoal Briquettes (5kg)","unit":"bag","price":6.99,"in_stock":True,"tags":["charcoal","bbq","fuel"]},
      {"sku":"SKEWERS_METAL_6PK","name":"Metal Skewers (6 pcs)","unit":"pack","price":3.49,"in_stock":True,"tags":["skewer","accessory","bbq"]}
    ]}
  ]
}

DELIVERY = {
  "zones": [
    {"area":"E1-E4","min_order":25.0,"fee":3.50,"eta_hours":"Same-day (order before 5pm)"},
    {"area":"E5-E14","min_order":35.0,"fee":4.00,"eta_hours":"Next-day (Mon–Sat)"},
    {"area":"EC1-EC4","min_order":30.0,"fee":3.50,"eta_hours":"Same-day (order before 3pm)"},
    {"area":"N1-N8","min_order":35.0,"fee":4.50,"eta_hours":"Next-day (Mon–Sat)"}
  ],
  "notes":"Free delivery over £50 across all serviced postcodes. Click & collect available during opening hours.",
  "exceptions":[{"date":"2025-12-25","note":"Closed on Christmas Day"},{"date":"2025-12-26","note":"Limited delivery windows"}]
}

BRANCHES = [
  {"id":"east-london","name":"East London Branch","address":"12 Whitechapel Rd, London E1 1AA","postcode":"E1 1AA","phone":"+44 20 7946 1001","lat":51.5151,"lon":-0.0672,"hours":{"mon-sat":"09:00–20:00","sun":"10:00–18:00"}},
  {"id":"north-london","name":"North London Branch","address":"220 Seven Sisters Rd, London N4 3NG","postcode":"N4 3NG","phone":"+44 20 7946 1002","lat":51.5658,"lon":-0.1065,"hours":{"mon-sat":"09:00–20:00","sun":"10:00–18:00"}}
]

STORE_INFO = {
  "name":"EXAMPLE Halal Butchers",
  "about":"Independent halal-certified butcher offering fresh poultry, lamb, and beef with same-day delivery in selected London postcodes.",
  "email":"support@examplebutchers.co.uk","phone":"+44 20 7946 0000",
  "website":"https://examplebutchers.co.uk",
  "halal_certified":True,"certifications":["HMC-inspected"],
  "social":{"instagram":"https://instagram.com/examplebutchers","facebook":"https://facebook.com/examplebutchers"}
}

FAQ = [
  {"q":"Do you deliver to {postcode}?","a":"We deliver to many London areas. {delivery_summary} If you share your postcode, I’ll confirm the exact minimum order and fee."},
  {"q":"What are your opening hours?","a":"Most branches are open Mon–Sat 09:00–20:00 and Sun 10:00–18:00. On bank holidays, hours may vary."},
  {"q":"Is your meat halal certified?","a":"Yes. All products are halal and HMC-inspected."},
  {"q":"Do you have BBQ bundles?","a":"Yes. We can build BBQ bundles for different group sizes — wings, drumsticks, skewers, sauces, and charcoal. Tell me how many people."},
  {"q":"Can I click and collect?","a":"Yes, click & collect is available during branch opening hours. You can place an order and pick it up from your nearest branch{branch_name}."}
]

SYNONYMS = {
  "chicken":["hen","bird","poultry"],
  "lamb":["mutton","sheep meat"],
  "beef":["cow meat","steak"],
  "mince":["ground","keema"],
  "bbq":["barbecue","grill","cookout"],
  "drumstick":["drum","leg piece"],
  "thigh":["upper leg"],
  "kofta":["seekh","skewer","kebab"],
  "wing":["flapper","wingette"],
  "charcoal":["coal","briquette"],
  "sauce":["marinade","condiment","dip"]
}

OVERRIDES = {
  "tone":{"style":"friendly","max_sentences":2},
  "recommendations":{"related_count":3,"show_out_of_stock":False},
  "thresholds":{"search_confidence":0.82,"geo_radius_km":15},
  "filters":{"exclude_tags":["test","placeholder"]},
  "self_repair":{"auto_suggest_synonyms":True,"log_issues_only":True}
}

BRANDING = {
  "theme":{"primary_color":"#127A32","secondary_color":"#FFFFFF","accent_color":"#E63946","text_color":"#222222","font_family":"Inter, sans-serif"},
  "logo":{"light":"https://cdn.examplebutchers.co.uk/logo-light.png","dark":"https://cdn.examplebutchers.co.uk/logo-dark.png"},
  "favicon":"https://cdn.examplebutchers.co.uk/favicon.ico",
  "widget":{"avatar":"https://cdn.examplebutchers.co.uk/chat-avatar.png","greeting":"Hi! How can I help you today?","chat_title":"Example Butchers Assistant"}
}

def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    tenant = "EXAMPLE"
    base = BUSINESS / tenant
    write_json(base / "catalog.json", CATALOG)
    write_json(base / "delivery.json", DELIVERY)
    write_json(base / "branches.json", BRANCHES)
    write_json(base / "store_info.json", STORE_INFO)
    write_json(base / "faq.json", FAQ)
    write_json(base / "synonyms.json", SYNONYMS)
    write_json(base / "overrides.json", OVERRIDES)
    write_json(base / "branding.json", BRANDING)
    print(f"[OK] Seeded tenant {tenant} under {base}")

if __name__ == "__main__":
    main()
