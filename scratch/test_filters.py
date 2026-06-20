import sys
sys.path.insert(0, 'c:/Users/HOMEH/Desktop/БОТЫ/ОЛХ/resell_radar')

print('=== FILTER LOGIC TEST ===')
from app.scoring.text_analyzer import load_global_bad_words
from app.services.monitor import load_watchlist

global_bw = load_global_bad_words()
print(f'Global bad words loaded: {len(global_bw)}')

wl = load_watchlist()
print(f'Watchlist items: {len(wl)}')
iphone11 = next(i for i in wl if i['id'] == 'iphone_11')
normal_range = iphone11['normal_price_range']
price_floor = normal_range[0] * 0.15
keywords = iphone11['keywords']
item_bw = [bw.lower() for bw in iphone11['bad_words']]
all_bw = set(item_bw) | set(bw.lower() for bw in global_bw)

print(f'Price floor for iPhone 11: {price_floor:.0f} UAH')
print(f'Normal range: {normal_range}')
print(f'All bad words for item: {len(all_bw)}')
print()

test_cases = [
    # (title, price, should_pass)
    ('iPhone 11 64GB стан хороший', 7200, True),
    ('iPhone 11 Pro Max 256GB', 14900, True),
    ('Чехол для iPhone 11', 150, False),
    ('Чохол iPhone 11 силікон', 89, False),
    ('стекло на iphone 11', 99, False),
    ('Захисне скло iPhone 11', 79, False),
    ('Зарядка для iPhone 11', 200, False),
    ('МАГАЗИН чехлы для iPhone 11 все цвета', 100, False),
    ('Навушники для iPhone 11', 350, False),
    ('iPhone 11 icloud не включається', 1500, False),
    ('iPhone 11 64GB Київ оригінал', 8900, True),
    ('Айфон 11 128gb стан ідеальний', 9500, True),
    ('Кабель USB для iPhone 11', 120, False),
    ('iPhone 11 R-SIM USA locked', 4000, False),
    ('iPhone 11 накладка прозора', 80, False),
]

passed = 0
failed = 0
for title, price, should_pass in test_cases:
    title_lower = title.lower()
    kw_match = any(kw.lower() in title_lower for kw in keywords)
    price_ok = price > 0 and price >= price_floor and price <= normal_range[1] * 1.3
    has_bad = any(bw in title_lower for bw in all_bw)
    
    result_pass = kw_match and price_ok and (not has_bad)
    test_ok = (result_pass == should_pass)
    
    status_icon = "PASS" if result_pass else "FILT"
    check = "OK" if test_ok else "WRONG"
    
    reason = []
    if not kw_match:
        reason.append('no_keyword')
    if has_bad:
        matched_bw = [bw for bw in all_bw if bw in title_lower]
        reason.append(f'bad_word={matched_bw[:2]}')
    if not price_ok:
        reason.append(f'price {price} < floor {price_floor:.0f}' if price < price_floor else f'price {price} > max')
    
    reason_str = ', '.join(reason) if reason else 'OK'
    
    print(f'  [{check}] [{status_icon}] {price:>6} UAH - {title[:45]:<45} | {reason_str}')
    
    if test_ok:
        passed += 1
    else:
        failed += 1
        print(f'         ^^^ EXPECTED {"PASS" if should_pass else "FILTER"}, GOT {"PASS" if result_pass else "FILTER"}')

print()
print(f'Results: {passed}/{len(test_cases)} correct')
if failed == 0:
    print('=== ALL FILTER TESTS PASSED! ===')
else:
    print(f'=== FAILURES: {failed} ===')
