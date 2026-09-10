# Album Matching — Failure Analysis

وضعیت: تحلیل ریشه‌ای روی v2.1.0  
مرتبط: Phase B در `ROADMAP.md` (این سند scope آن phase را باز می‌کند)

---

## خلاصه

پیدا کردن آلبوم «درست کار نمی‌کند» چون **سه تصمیم طراحی غلط** روی هم انباشته شده‌اند، نه یک باگ کوچک:

1. جستجو **recording-first** است، نه album-first.
2. انتخاب release به تگ آلبومِ کاربر **نگاه نمی‌کند**.
3. سیاست سال **جدیدترین** را انتخاب می‌کند، مستندات می‌گویند قدیمی‌ترین.

---

## A. جریان فعلی (آنچه کد می‌کند)

```
tags(artist, title, album)
        │
        ▼
search_mb: recording:title AND artistname:artist [AND release:album]
        │
        ▼
recordings[0]          ← هیچ score، هیچ انتخاب بین کاندیدها
        │
        ▼
_best_release(recordings[0].releases)
        │  type_score * 1000 + year_score
        │  year_score = max(0, 30 - (now - year))   ← جدیدترین برنده
        ▼
result.album = release.title
```

تگ آلبومِ کاربر فقط در **query** استفاده می‌شود، نه در **انتخاب release**. حتی اگر search با `release:Abbey Road` محدود شود، `_best_release` ممکن است edition دیگری از همان recording را برگرداند.

---

## B. باگ‌ها (با شدت)

### B1 — CRITICAL · `_best_release` جدیدترین را ترجیح می‌دهد

```python
year_score = max(0, 30 - (current_year - year)) if year < 9999 else 0
```

| release | year | year_score (2026) |
|---|---|---|
| Original | 1973 | 0 |
| Remaster | 2011 | 15 |
| Anniversary | 2023 | 27 |

README: «Always picks the oldest known release date».  
کد: جدیدترین studio-album برنده است.

**اثر:** «The Dark Side of the Moon» می‌شود remaster 2011 نه 1973. همهٔ فایل‌ها زیر یک سال اشتباه سازمان می‌یابند.

---

### B2 — CRITICAL · تگ آلبوم کاربر در انتخاب release بی‌اثر است

```python
releases = rec.get("releases", [])
if releases:
    rel, year = _best_release(releases)   # album نه در ورودی، نه در score
```

یک recording مشهور روی ده‌ها release است:

- آلبوم اصلی
- Greatest Hits
- Soundtrack
- Live
- Box set
- هر reissue منطقه‌ای

اگر کاربر «OK Computer» را درست تگ کرده باشد و recording در «OKNOTOK 2017» هم باشد، انتخاب بر اساس type/year است — **نه بر اساس اینکه کاربر کدام آلبوم را دارد**.

---

### B3 — CRITICAL · track number وقتی media خالی است دروغ می‌گوید

```python
if not found_track and media:
    m0 = media[0]
    result["total_tracks"] = str(m0.get("track-count", ""))
    tracks = m0.get("track", [])
    if tracks:
        result["track"] = str(tracks[0].get("number", ""))  # track اول آلبوم!
```

MB search با `inc=releases` اغلب **track list کامل نمی‌دهد**. آنگاه:

- هر فایلِ آلبوم ← track «1»
- destination: `01 - Whatever.mp3` برای همه
- مرتب‌سازی آلبوم نابود می‌شود

این یکی از دلایل «آلبوم‌ها درست نمی‌آیند» از نظر کاربر است: نه فقط نام آلبوم، **ترتیب قطعات** هم خراب است.

---

### B4 — HIGH · `recordings[0]` کورکورانه

```python
rec = data["recordings"][0]
```

limit=5 است ولی فقط اولی مصرف می‌شود. MB اولین hit را بر اساس relevance داخلی خودش می‌دهد که لزوماً بهترین برای library کاربر نیست (cover، live، different spelling).

---

### B5 — HIGH · query شکننده + بدون fallback

```python
if album: parts.append(f'release:{album}')
query = " AND ".join(parts)
```

- کاراکترهای Lucene در title/artist/album escape نمی‌شوند: `+ - : ( ) " ~ *`
- اگر تگ آلبوم کثیف باشد (`Abbey Road (2019 Remaster)` vs `Abbey Road`)، کل AND ممکن است صفر نتیجه دهد
- **هیچ retry بدون album وجود ندارد**

---

### B6 — HIGH · AcoustID همان `_best_release` خراب را صدا می‌زند

```python
rel, yr = _best_release(rec["releases"])
```

Fingerprint معمولاً چند release برمی‌گرداند. همان سوگیری جدیدترین + نادیده گرفتن تگ آلبوم.

ساختار AcoustID هم فرق دارد (`mediums`/`tracks`/`position` vs `media`/`track`/`number`) — مسیر track آن جداست و درست‌تر است، ولی release selection همان باگ را دارد.

---

### B7 — CRITICAL برای شما · `normalize_album_key` فارسی را نابود می‌کند

```python
return re.sub(r'[^a-z0-9]', '', name.lower())
```

| ورودی | key |
|---|---|
| `آبی` | `""` |
| `دربارهٔ الی` | `""` |
| `Greatest Hits` | `greatesthits` |
| `Greatest Hits!` | `greatesthits` |

هر نامِ غیر ASCII به رشتهٔ خالی می‌رسد. **همهٔ آلبوم‌های فارسی/عربی/سیریلیک/CJK در یک bucket می‌افتند** و merge آن‌ها را در هم می‌ریزد — یا برعکس، آلبوم‌های واقعاً یکسان ادغام نمی‌شوند اگر فقط با حرف لاتین قاطی باشند.

برای یک library فارسی‌زبان این data-loss در سطح ساختار پوشه است.

---

### B8 — MEDIUM · `_is_confident_match` با album equality خام

```python
return bool(orig_album and mb_album and orig_album == mb_album)
```

- Exact string: `Abbey Road` ≠ `ABBEY ROAD` ≠ `Abbey Road (Remastered)`
- اگر title نامساوی ولی album خالی → False (خوب) ولی اگر title برابر → True حتی وقتی release اشتباه است (بدی B2)
- اگر title خالی باشد → True (همیشه confident) — برای untagged خطرناک

---

## C. نگاشت باگ ← علامت کاربر

| علامتی که می‌بینی | باگ ریشه |
|---|---|
| سال آلبوم همیشه جدید/امروزی | B1 |
| نام آلبوم edition عجیب/Remaster | B2 + B1 |
| همهٔ آهنگ‌ها track 01 | B3 |
| آهنگ در آلبوم اشتباه (Greatest Hits) | B2 + B4 |
| بعضی فایل‌ها اصلاً identify نمی‌شوند | B5 |
| آلبوم‌های فارسی قاطی/گم | B7 |
| بعد از fingerprint باز هم آلبوم غلط | B6 |

---

## D. طراحی هدف (Phase B+)

### D.1 دو مسیر جستجو — album-first سپس recording fallback

```
if album_tag and artist_tag:
    candidates = search_album_then_track(artist, album, title)
    # release-group search → بهترین album → track در آن album
if not accepted:
    candidates = search_recording(artist, title)
    # score هر recording و هر release‌اش نسبت به album_tag اگر داریم
if still not accepted:
    reject → keep local tags
```

### D.2 انتخاب release با score چند-سیگناله

```python
def score_release_for_library(
    release: Mapping[str, Any],
    *,
    desired_album: str,
    desired_artist: str,
    prefer_oldest: bool = True,
    exclude_secondary: frozenset[str] = ...,
) -> float:
    """Score 0..100 for choosing which edition/release to file under."""
```

سیگنال‌ها (وزن پیشنهادی):

| سیگنال | وزن | منطق |
|---|---|---|
| similarity(release.title, desired_album) | 0.40 | اگر album خالی، این سیگنال حذف و نرمال می‌شود |
| primary-type == album و بدون secondary | 0.20 | compilation/live/soundtrack جریمه |
| country/status official | 0.05 | bootleg/Pseudo-Release جریمه |
| year policy (oldest در type برابر) | 0.15 | نه «جدیدترین همیشه» |
| track presence روی همین release | 0.20 | اگر media.track پیدا شد |

حد پذیرش: **≥ 55** برای overwrite آلبوم؛ زیر آن album محلی بماند.

### D.3 recording selection نیز score می‌گیرد

```python
def score_recording_match(query, candidate) -> float
# artist + title توکن‌ای؛ album فقط bonus
```

حد پذیرش recording: **0.82**. بهترین کاندید از limit=10، نه recordings[0].

### D.4 track number فقط وقتی واقعاً پیدا شد

```python
track_number = None  # هرگز tracks[0] را جایگزین نکن
for medium in media:
    for track in medium.get("track", []):
        if track.recording.id == recording_id:
            track_number = track.number
```

اگر پیدا نشد: track از tag محلی؛ اگر آن هم خالی: بدون zero-fill دروغین — فایل بدون پیشوند track برود.

### D.5 normalize برای Unicode

```python
def normalize_album_key(folder_name: str) -> str:
    # strip year prefix
    # casefold (نه lower خالی)
    # حذف punctuation
    # نگه‌داشتن حروف Unicode (فارسی/عربی/سیریلیک/CJK)
    # اگر بعد از نرمال‌سازی خالی شد → از hash پایدار نام خام استفاده کن، نه ""
```

### D.6 Escape و fallback query

- Lucene escape کاراکترهای خاص
- اگر query با album صفر نتیجه داد → retry فقط artist+title
- اگر باز هم صفر → artist فقط برای diagnostic log (اختیاری، default خاموش)

---

## E. تست‌هایی که باید قبل از fix قرمز شوند

1. `test_best_release_prefers_oldest_studio` — 1973 vs 2011 remaster → 1973
2. `test_best_release_prefers_user_album` — desired=OK Computer، کاندیدها OKNOTOK + OK Computer → OK Computer
3. `test_track_not_defaulted_to_one` — media بدون track list → track از local tag یا خالی، هرگز «1»
4. `test_recording_first_result_not_blind` — hit دوم score بالاتر → hit دوم
5. `test_album_query_failure_falls_back` — query با album خالی → retry بدون album
6. `test_normalize_preserves_persian` — `آبی` ≠ `""` و با `دیگری` تصادفی merge نمی‌شود
7. `test_confident_match_rejects_empty_title_overwrite` — untagged + fingerprint ضعیف → overwrite نشود
8. `test_rejects_below_threshold` — score پایین → album محلی حفظ شود

---

## F. تأثیر روی رودمپ

Phase B از «matching عمومی» باید **explicitly album-centric** شود:

| زیرمرحله | خروجی |
|---|---|
| B0 | تست‌های قرمز بالا (TDD) |
| B1 | `domain/matching.py` — score recording + score release (pure) |
| B2 | `metadata/musicbrainz.py` — album-first search + fallback + Lucene escape |
| B3 | fix track resolution (فقط exact recording id) |
| B4 | `normalize_album_key` Unicode-safe |
| B5 | `prefer_oldest` + threshold + README alignment |
| B6 | پوشش AcoustID با همان release scorer مشترک |

**Version بعد از B: 2.3.0** (feat — رفتار album عوض می‌شود؛ برای کسی که به remasterهای جدید عادت کرده breaking-behavior محسوب می‌شود، ولی SemVer minor می‌ماند چون API نشکسته؛ اگر خواستی major بگو).

---

## G. تصمیم‌هایی که قبل از کدنویسی لازم دارم

1. **prefer_oldest** قطعی؟ (توصیه: بله — مطابق README و عرف collector)
2. آیا **Remaster/Deluxe را هرگز** نخواهیم مگر تگ آلبوم کاربر دقیقاً همان edition را نام ببرد؟ (توصیه: بله)
3. برای آهنگ‌هایی که «تک‌آهنگ» هستند و روی آلبوم نیستند: folder با عنوان release type=Single قبول داری؟ (توصیه: بله، ولی type_score پایین‌تر از album)
4. threshold album ≥ 55 و recording ≥ 0.82 — قابل تنظیم از config؟ (توصیه: بله، با defaultهای فوق)
