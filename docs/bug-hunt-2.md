# Bug Hunt #2 — Additional Findings (v2.1.0)

مکمل تحلیل‌های قبلی (`ROADMAP.md`, `docs/album-matching-analysis.md`)  
وضعیت: تأییدشده با اجرای probe محلی — نه حدس

---

## Severity legend

| نماد | معنی |
|---|---|
| **P0** | data loss / دروغ به کاربر / خراب‌کردن library |
| **P1** | feature شکسته / رفتار غیرمنتظره جدی |
| **P2** | ناهماهنگی config/docs / edge case |

---

## P0 — خطرناک‌ترین‌ها

### X1 · `--preview` هنوز tag فایل source را می‌نویسد

```1236:1250:music_core.py
    # 6. Write tags
    has_new_data = source != "tags" or meta.get("_lyrics_plain") or meta.get("_lyrics_synced") or cover_bytes
    if opts.get("write_tags", True) and has_new_data:
        try:
            write_tags(path, meta, cover_bytes=cover_bytes)
        ...
    # 7. Copy / move
    dest = destination(dst, meta)

    if opts.get("dry_run", False):
        stats["ok"] += 1
        log(f"  [DRY] \u2192 {dest}")
        return meta, source, "dry-run", str(dest)
```

ترتیب: **write_tags → سپس dry_run check**.

README: «Preview without making changes».  
واقعیت: با `--preview` هم tag فایل‌های اصلی عوض می‌شود؛ فقط copy/move انجام نمی‌شود.

**این بدترین باگ پروژه است** — dry-run دقیقاً همان چیزی است که کاربر قبل از اجرای خطرناک می‌زند و همان چیزی است که به او امنیت دروغ می‌دهد.

---

### X2 · merge پوشه، فایل‌های غیر-صوتی را حذف می‌کند

```1107:1119:music_core.py
                for src_file in collect_audio_files(loser):
                    ...
                for src_img in loser.glob("cover.*"):
                    ...
                try:
                    shutil.rmtree(str(loser))
```

فقط audio + `cover.*` منتقل می‌شوند. بعد `rmtree`:

- `.cue` / `.log` / `.accurip` (rips)
- `.m3u` / `.nfo` / `.sfv`
- booklet PDF
- هر فایل جانبی دیگر

**Data loss بی‌صدا.**

---

### X3 · `normalize_album_key` همهٔ نام‌های Unicode را در یک bucket می‌ریزد

تأیید probe:

```
'آبی'          -> ''
'درباره الی'    -> ''
'دیگری'        -> ''
collision آبی vs دیگری: True
```

```python
re.sub(r'[^a-z0-9]', '', name.lower())
```

هر آلبوم فارسی/عربی/سیریلیک/CJK → key خالی → **همه با هم merge**. برای library فارسی‌زبان data-loss ساختاری است.

---

### X4 · Cover art cache اصلاً کار نمی‌کند (تأییدشده)

```
bytes json: FAIL -> TypeError : Object of type bytes is not JSON serializable
```

`fetch_cover_art` بایت خام را با `_cache_set` → `json.dumps` می‌فرستد. TypeError می‌خورد، `except: pass` می‌بلعد. هر بار دانلود از نو؛ TTL/cache فقط برای JSON کار می‌کند.

---

## P1 — Feature شکسته

### X5 · `overwrite_art` / `--replace-art` art جاسازی‌شده را عوض نمی‌کند

- `save_folder_cover(..., overwrite=opts["overwrite_art"])` ← فقط `cover.jpg` کنار پوشه
- writerها: `if cover_bytes and not meta.get("has_art")` ← **هرگز APIC/covr موجود را جایگزین نمی‌کند**

GUI label: «Replace existing art».  
CLI: `--replace-art`.  
واقعیت: فقط فایل cover.jpg پوشه. Art توکار دست‌نخورده می‌ماند.

---

### X6 · کلیدهای config نوشته می‌شوند و هرگز خوانده نمی‌شوند

| Key | کد مصرف‌کننده |
|---|---|
| `mb_rate_limit_seconds` | hardcoded `1.1` در `mb_get` |
| `request_timeout` | hardcoded `10`/`15`/`8` در HTTPها |
| `cover_filename` | hardcoded `"cover.jpg"` |
| `max_genre_count` | hardcoded `[:4]` |
| `config_dir` | `_CACHE_DIR` جدا hardcoded از home |
| `fpcalc_urls` | installer دیکتهٔ URL متفاوت خودش را دارد |
| `output_template` | مستقیمً مستند: بی‌اثر |
| `discogs_token` | هیچ‌جا |
| `is_mp3` property | dead API |

Probe: installer و config **دو URL متفاوت** برای همان باینری:

```
installer: https://acoustid.org/files/chromaprint/...
config:    https://github.com/acoustid/chromaprint/releases/...
same? False
```

یعنی سیستم config دروغ می‌گوید: «centralized» نیست.

---

### X7 · `mb_get` قفل را موقع sleep + کل network نگه می‌دارد

```python
with _mb_lock:
    if gap > 0: time.sleep(gap)      # تا ~۱.۱s
    with urllib.request.urlopen(..., timeout=10) as r:  # تا ۱۰s
```

Rate-limit فقط باید فاصلهٔ start-requestها را کنترل کند. نگه‌داشتن lock موقع I/O یعنی هیچ thread دیگری حتی برای cache-hit هم نمی‌تواند وارد شود (البته cache قبل از lock است — پس فقط missها). هنوز design اشتباه است و باعث می‌شود timeout 10s × فایل‌ها صف کاذب بسازد.

---

### X8 · LRC parser خطوط رایج را می‌اندازد

Regex: `r'^\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)$'`

| خط | match؟ |
|---|---|
| `[00:12.50] x` | بله |
| `[00:12] x` | **نه** |
| `[0:12.50] x` | **نه** |
| `[00:12.5] x` | **نه** (۱ رقم اعشار) |
| `[00:12.500] x` | بله |

منابع LRCLIB/playerها `[MM:SS]` و `[M:SS.xx]` هم تولید می‌کنند. Synced lyrics برای این خطوط گم می‌شود.

---

### X9 · Windows reserved names از `safe()` رد می‌شوند

```
safe('CON') -> 'CON'
safe('PRN') -> 'PRN'
safe('COM1') -> 'COM1'
```

ایجاد پوشه/فایل با این نام‌ها روی Windows شکست می‌خورد (`mkdir CON`) یا به دستگاه خاص وصل می‌شود. Artist به‌نام «CON» یا «PRN» کل آلبوم‌هایش fail می‌شوند.

---

### X10 · Path length بدون کنترل

Probe: مسیر نمونه با nameهای ۶۰ کاراکتری ≈ **۲۶۲** — از `MAX_PATH=260` رد می‌شود.

`filename_max_length=60` کاراکتر است نه UTF-8 bytes و هیچ سقفی روی `root/artist/album/file` نیست. کپی روی Windows بدون long-path enable شکست می‌خورد؛ exception بلعیده می‌شود.

---

### X11 · `merge_similar_albums` در config وجود دارد؛ process از `opts["do_merge"]` می‌خواند

GUI/CLI flag دارند. کلید config **هرگز در pipeline خوانده نمی‌شود**. یکپارچگی config شکسته است.

---

### X12 · نصب fpcalc vs یافتن fpcalc مسیر متفاوت

| | مسیر |
|---|---|
| `find_fpcalc` (dev) | `Path(__file__).parent` |
| `install_dir` (non-frozen) | `Path(sys.argv[0]).parent` |

با entry point (`music-organizer` از Scripts) یا `python -m`، `__file__` و `argv[0]` جاهای متفاوت‌اند. دانلود «موفق» → فایل یک‌جا → finder جای دیگر → هنوز fingerprint نداری.

---

## P2 — edge / polish

### X13 · سال اعتبارسنجی نمی‌شود

`year = "XXXX"` یا `"0000"` → پوشه `XXXX - Album`. `safe()` سال را نمی‌گیرد.

### X14 · `write_tags` فیلدهای خالی را در FLAC/OGG حذف می‌کند بدون جایگزین

managed keys delete → فقط اگر truthy باشد set می‌شود. اگر pipeline عمداً field را خالی کرده باشد، tag قبلی می‌رود. برای MP4 برعکس: فیلد خالی پاک نمی‌شود. **ناسازگار بین فرمت‌ها.**

### X15 · MP4 `overwrite` مفید نیست ولی `has_art` از read می‌آید

اگر `read_tags` art را نبیند (فرمت خاص)، `has_art=False` و art دوباره embed می‌شود حتی وقتی overwrite_art خاموش است.

### X16 · GUI tooltip «Keep originals» برعکس است

```
"Keep originals" → "Move originals to output; uncheck to copy"
```

Label و variable (`copy=True`) درست‌اند؛ tooltip دروغ می‌گوید. کاربر ممکن است تیک را بردارد و فکر کند copy می‌کند.

### X17 · CLI skip-list پیام «Identified» را نمی‌گیرد

فیلتر: `" ✓ MusicBrainz"`, `" ✓ AcoustID"`  
پیام واقعی: `"  ✓ Identified: Artist — Title"`  
→ در non-verbose هم print می‌شود. GUI هم همین skip ناقص را دارد.

### X18 · Space در GUI با Pause تداخل دارد

`bind("<space>", toggle_pause)` روی کل window. Checkbutton از Space استفاده می‌کند؛ رفتار دوگانه/گیج‌کننده.

### X19 · `dry_run` هنوز شبکه و rate-limit و cache مصرف می‌کند

فقط کپی skip است. Preview کتابخانه ۵۰۰۰ فایلی = ۵۰۰۰ درخواست MB. برای «بدون تغییر» غیرمنتظره است (cache side-effect).

### X20 · year در destination از TDRC خام می‌آید

`g("TDRC")[:4]` — اگر TDRC عجیب باشد فولدر می‌شود `202 - Album` یا `20xx`. بدون regex `^\d{4}$`.

### X21 · genre TCON با `"; ".join"` یک رشته است

بازیکن‌هایی که multi-genre ID3v2.4 می‌خواهند این را یک ژانر می‌خوانند. minor.

### X22 · `_cache_cleanup` side effect در import

Import ماژول = دیسک‌کاری. برای CLI سریع/تست غیرمنتظره. باید lazy یا explicit باشد.

### X23 · Config singleton در تست‌ها state leak می‌کند

تست‌ها `c._data = dict(DEFAULTS)` می‌کنند ولی singleton ممکن است کلید custom از تست قبلی را نگه دارد. `test_set_and_get` کلید می‌سازد و پاک نمی‌کند.

### X24 · `install_deps` با pip بدون isolated env

`subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", ...])`  
روی anaconda/سیستمی که pip قفل دارد خطا می‌دهد یا env کاربر را کثیف می‌کند. anti-pattern.

---

## نگاشت باگ ← Phase

| باگ‌ها | Phase |
|---|---|
| X1, X2, X16, X19 (partial) | **A — Safety** |
| X3, X5 (policy matching/art), album bugs قبلی | **B — Matching** |
| X6, X7, X11, X12, X22, X24 | **C/E — Package + config truth** |
| X4, X8, X9, X10, X14, X20 | **B/D — correctness + tests** |
| X13, X15, X17, X18, X21, X23 | **F — UX/perf + D tests** |

---

## توصیه به رودمپ

Phase A باید X1 را **صراحتاً** در DoD بگذارد:

> `--preview` / `dry_run=True` هیچ write روی filesystem انجام نمی‌دهد — نه tag، نه cover، نه copy، نه merge.

بدون این، هر feature بعدی روی شن ساخته می‌شود.
