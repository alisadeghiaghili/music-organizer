# Music Organizer — Engineering Roadmap

وضعیت فعلی: **v2.3.0** (Phase A+B done)  
هدف نهایی: ابزار سازمان‌دهی موسیقی production-grade، multi-format، امن برای library واقعی  
رویکرد: **TDD** · **Clean Architecture** · **PRهایی در مقیاس ~یک هفته کار انسانی**

این سند قرارداد اجراست. هر مرحله باید Definition of Done را رد کند قبل از merge.

---

## 0. قراردادهای پروژه

### 0.1 Naming

| لایه | قرارداد | مثال |
|---|---|---|
| Package / module | `snake_case` | `metadata/musicbrainz.py` |
| Class | `PascalCase` | `TrackMeta`, `MusicBrainzClient` |
| Function / method | `snake_case` | `process_file`, `fetch_cover_art` |
| Constant | `UPPER_SNAKE` | `DEFAULT_RATE_LIMIT_SECONDS` |
| Private module helper | leading `_` | `_select_best_release` |
| Type alias | `PascalCase` | `ProcessStatus` |
| Test class | `Test` + subject | `TestMusicBrainzClient` |
| Test function | `test_` + behavior | `test_rejects_low_score_match` |

Python naming: PEP 8. Domain terms از موسیقی حفظ می‌شوند (`release`, `recording`, `medium`, `track`).

### 0.2 Type hints & docstring (اجباری روی public API)

```python
def select_best_release(
    releases: Sequence[Mapping[str, Any]],
    *,
    prefer_oldest: bool = True,
) -> tuple[ReleaseInfo | None, int | None]:
    """Select the studio-album release that best matches library policy.

    Prefers primary type ``album`` without secondary types, then applies
    year policy (oldest by default).

    Args:
        releases: MusicBrainz release objects from a recording search.
        prefer_oldest: When True, earlier years win ties on type score.

    Returns:
        Tuple of selected release (or None) and release year (or None).

    Examples:
        >>> select_best_release([{"date": "1999-01-01", "primary-type": "Album"}])
        ({"date": "1999-01-01", "primary-type": "Album"}, 1999)
    """
```

قواعد:

- هر public function/class: type hints کامل + docstring با Args/Returns
- Examples فقط جایی که رفتار non-obvious است (نه برای getter بدیهی)
- `from __future__ import annotations` در ماژول‌های جدید
- Prefer `dataclasses` / `TypedDict` / `Protocol` روی `dict` خام
- Exceptions اختصاصی: `MusicOrganizerError` به‌عنوان root

### 0.3 Commit & PR

**Commit (Conventional Commits):**

```
<type>(<scope>): <imperative summary>

[optional body: why, not what]
```

انواع: `feat` `fix` `refactor` `test` `docs` `chore` `ci` `perf` `build`

Scope پیشنهادی: `core`, `metadata`, `tags`, `organize`, `cache`, `cli`, `gui`, `packaging`, `fpcalc`, `config`

**PR:**

- یک PR ≈ یک هفته کار انسانی (~۴۰ ساعت مهندسی، معمولاً ۸۰۰–۱۵۰۰ خط تغییر مفید + تست)
- عنوان: همان commit اول یا خلاصهٔ feat/fix
- بدنه: Why · What · How verified (دستور تست) · Breaking changes
- بعد از merge: branch حذف شود
- هیچ اثر AI: نه co-author، نه پیام، نه شاخه، نه trailer

**Release:**

- بعد از هر phase کامل: tag + CHANGELOG + به‌روزرسانی README
- SemVer: breaking → major · feat → minor · fix/docs/test → patch (مگر phase بزرگ‌تر باشد)

### 0.4 کیفیت گیت (Definition of Done — همهٔ phases)

- [ ] تست‌های جدید **قبل از** پیاده‌سازی نوشته و fail شوند (TDD)
- [ ] `pytest` سبز
- [ ] coverage ماژول‌های تازه ≥ 85% (کل پروژه بعد از Phase C ≥ 75%)
- [ ] `ruff check` و `ruff format` تمیز
- [ ] `ty` یا `pyright` بدون error روی public API
- [ ] docstring عمومی کامل
- [ ] CHANGELOG به‌روز
- [ ] مستندات با کد یکی باشند (هر ادعای README قابل ردیابی در کد)

---

## 1. معماری هدف

```
music_organizer/
  __init__.py
  __about__.py              # __version__ تنها منبع نسخه
  errors.py                 # exception hierarchy
  config/
    __init__.py
    schema.py               # typed settings
    loader.py               # file + env merge
  domain/
    __init__.py
    models.py               # TrackMeta, MatchCandidate, ProcessOptions, ProcessResult
    matching.py             # pure scoring / policy
    paths.py                # pure path policy
  cache/
    __init__.py
    store.py                # CacheStore protocol + filesystem impl (safe binary)
  metadata/
    __init__.py
    http.py                 # shared HTTP session, timeout, UA
    rate_limit.py
    musicbrainz.py
    acoustid.py
    lastfm.py
    lrclib.py
    covers.py
  tags/
    __init__.py
    types.py                # TagReader / TagWriter protocols
    id3.py
    vorbis.py
    mp4.py
    wave_aiff.py
    registry.py             # extension → handlers
    io.py                   # read_tags / write_tags facade
  organize/
    __init__.py
    processor.py            # process_file orchestration
    merge.py
    journal.py              # undo/manifest
    runner.py               # batch + pause/stop (UI-agnostic)
  binaries/
    __init__.py
    fpcalc.py               # locate, install, hash-verify
  ui/
    cli/
      __init__.py
      main.py
      interactive.py
    gui/
      __init__.py
      app.py
tests/
  unit/
  integration/
  fixtures/
pyproject.toml
```

**وابستگی‌ها فقط به سمت داخل:**

```
ui → organize → metadata/tags/domain
metadata → cache, domain
tags → domain
domain → (هیچ)
```

`domain` بدون I/O. Network فقط در `metadata/*`. فایل سیستم مخرب فقط در `organize/*` پشت journal.

---

## 2. نگاشت نسخه ← Phase

| Phase | Version | عنوان | اندازه |
|---|---|---|---|
| A | **2.2.0** | Safety net — جلوگیری از تخریب library | 1 week · 1 PR |
| B | **2.3.0** | Album-centric matching — album-first + scored release + Unicode key | 1–2 weeks · 1 PR |
| C | **3.0.0** | Package split — بازسازی معماری بدون شکستن CLI/GUI | 2 weeks · 2 PRs |
| D | **3.1.0** | Test fortress — پوشش pipeline و I/O | 1 week · 1 PR |
| E | **3.2.0** | Packaging & CI gate — نصب‌پذیر و CI واقعی | 1 week · 1 PR |
| F | **3.3.0** | UX & perf — GUI/CLI سریع و درست | 1 week · 1 PR |
| G | **4.0.0** | Product polish — release واقعی | 1 week · 1 PR |

جمع تقریبی: **۸ هفته کار مهندسی**، ۸ PR اصلی.

---

## 3. Phase A — Safety net → **v2.2.0**

**هدف:** هیچ راهی برای خراب‌کردن source library با tag write اشتباه وجود نداشته باشد.

### A.1 مشکلات

باگ‌های تأییدشده: [`docs/bug-hunt-2.md`](docs/bug-hunt-2.md)

| ID | مشکل | شدت |
|---|---|---|
| X1 | **`dry_run` هنوز tag source را می‌نویسد** (write قبل از check) | P0 |
| X2 | merge با `rmtree` فایل‌های غیر-صوتی را حذف می‌کند | P0 |
| — | `write_tags` روی source قبل از copy/move حتی در اجرای عادی | P0 |
| — | merge بدون journal | P1 |
| X16 | tooltip «Keep originals» برعکس است | P1 |
| X19 | dry_run هنوز شبکه/rate-limit مصرف می‌کند (قابل قبول ولی باید مستند شود) | P2 |

### A.2 کارها (ترتیب TDD)

1. **تست اول (red):** `dry_run=True` باید **هیچ** تغییری روی filesystem بگذارد — نه tag، نه cover، نه copy، نه merge.
2. **تست دوم (red):** حالت عادی copy-mode نباید tag فایل source را mutate کند.
3. **تست سوم (red):** merge نباید فایل غیر-صوتی (`.cue`, `.log`, `.nfo`) را حذف کند.
4. `ProcessOptions.write_to_source: bool = False` — default محافظه‌کارانه.
5. Tag write فقط روی **مقصد بعد از copy**؛ اگر move، اول move سپس tag روی مقصد.
6. Reorder `process_file`: dry_run guard **قبل از هر I/O مخرب**.
7. `organize/journal.py`: `organize-journal.jsonl` در output root:
   ```json
   {"ts": "...", "action": "copy|move|tag|merge|skip", "src": "...", "dst": "...", "meta_hash": "..."}
   ```
8. merge: انتقال **کل محتوای پوشه** (نه فقط audio+cover) + journal + rmtree فقط بعد از موفقیت کامل.
9. Log ساختاریافته (`logging`) جایگزین `pass`های بی‌صدا در مسیرهای I/O مخرب.
10. Fix tooltip نادرست «Keep originals».

### A.3 تست‌های جدید

- dry_run: صفر تغییر روی FS (tag hash قبل/بعد یکسان)
- source immutable در copy mode
- merge: `.cue`/`.nfo` زنده می‌مانند
- journal هر copy/move/merge را ثبت می‌کند
- merge با فایل تکراری: skip + log، نه overwrite خاموش
- exception در tag write: stats.error افزایش می‌یابد + log

### A.4 DoD Phase A

- [ ] `--preview` هیچ write ندارد (X1 سبز)
- [ ] source در copy mode دست‌نخورده
- [ ] merge فایل جانبی حذف نمی‌کند (X2 سبز)
- [ ] journal در CLI و GUI فعال
- [ ] CHANGELOG 2.2.0
- [ ] README: safety model + ساختار journal
- [ ] version = 2.2.0

**PR:** `fix(core): make dry-run side-effect free and journal all file mutations`

---

## 4. Phase B — Album-centric matching → **v2.3.0**

**هدف:** آلبومِ درستِ همان edition، با track درست. نه remaster تصادفی، نه Greatest Hits، نه track=01 برای همه.

تحلیل کامل: [`docs/album-matching-analysis.md`](docs/album-matching-analysis.md)

### B.1 مشکلات ریشه

| ID | باگ | شدت |
|---|---|---|
| B1 | `_best_release` جدیدترین را انتخاب می‌کند | CRITICAL |
| B2 | تگ آلبوم کاربر در انتخاب release بی‌اثر است | CRITICAL |
| B3 | track وقتی media خالی است ← همیشه «1» | CRITICAL |
| B4 | `recordings[0]` کور | HIGH |
| B5 | query شکننده، بدون fallback | HIGH |
| B6 | AcoustID همان release picker خراب | HIGH |
| B7 | `normalize_album_key` فارسی/Unicode → `""` | CRITICAL |
| B8 | `_is_confident_match` exact-only | MEDIUM |

### B.2 کارها (ترتیب TDD)

1. **B0 — تست‌های قرمز** (۸ تست analysis §E).
2. **B1 — `domain/matching.py` pure:**
   - `score_recording_match(...) -> float`
   - `score_release_for_library(...) -> float` (album similarity + type + oldest + track presence)
   - `should_accept(..., threshold) -> bool`
3. **B2 — جستجوی album-first در MusicBrainz:**
   - اگر artist+album: release search سپس یافتن track
   - fallback: recording search + score همهٔ releaseها نسبت به album_tag
   - Lucene escape + retry بدون album
   - `limit=10` و انتخاب best-score نه `[0]`
4. **B3 — track resolution فقط با recording id exact** — حذف `tracks[0]` fallback.
5. **B4 — `normalize_album_key` Unicode:** casefold + حفظ حروف + fallback hash به‌جای `""`.
6. **B5 — policy:** `prefer_oldest=True`، Remaster/Deluxe فقط اگر کاربر دقیقاً همان را تگ کرده.
7. **B6 — AcoustID** با همان `score_release_for_library` مشترک.
8. Threshold در config: `recording_min_score=0.82`، `album_min_score=55.0`.

### B.3 تست‌های جدید

- oldest studio بر remaster جدید غالب است
- desired album بر edition دیگر غالب است
- track ناموجود → خالی/local، هرگز «1»
- hit دوم با score بالاتر انتخاب می‌شود
- album query شکست → fallback
- `normalize_album_key("آبی")` غیرخالی و مستقل از `"دیگری"`
- زیر threshold → overwrite نمی‌شود
- compilation هرگز بر studio album غالب نمی‌شود

### B.4 DoD

- [ ] تست‌های §E همه سبز
- [ ] unit matching ~100% branch
- [ ] integration process_file با fake MB (hit + fallback + reject)
- [ ] README year/edition policy با کد یکی
- [ ] CHANGELOG 2.3.0
- [ ] version = 2.3.0

**PR:** `feat(metadata): album-first MusicBrainz matching with scored release selection`

---

## 5. Phase C — Package split → **v3.0.0**

**هدف:** معماری قابل رشد. رفتار CLI/GUI حفظ شود (compat shim موقت).

### C.1 ساختار هدف

دقیقاً همان layout بخش ۱.  
Migration دو PR:

**PR C1 (هفته ۱):** package skeleton + extract خالص‌ها

- `domain/models.py`: `TrackMeta` (dataclass), `ProcessOptions`, `ProcessResult`, `MatchCandidate`
- `domain/paths.py`: `safe_name`, `destination_path`, `normalize_album_key`
- `cache/store.py`: `CacheStore` Protocol + `FileSystemCache` (JSON برای dict، sidecar `.bin` برای bytes)
- `tags/registry` + extract ID3/Vorbis/MP4 از `music_core`
- `music_core.py` → facade نازک که به package اشاره می‌کند (deprecated warning داخلی، نه برای user)

**PR C2 (هفته ۲):** metadata clients + organize processor

- `metadata/musicbrainz.py` با injectable `HttpTransport` + `RateLimiter` + `CacheStore`
- `organize/processor.py` = pipeline جدید `process_file`
- `ui/cli` و `ui/gui` import از package
- حذف globals سطح ماژول (`_last_mb`, `_cfg`)

### C.2 قواعد extraction

- هر تابع منتقل‌شده: type hints + docstring + تست منتقل/جدید
- رفتار public CLI/GUI نباید بشکند (flagها یکسان)
- `collect_mp3s` حذف یا alias رسمی deprecated

### C.3 DoD

- [ ] `import music_organizer` کار می‌کند
- [ ] entry points به `music_organizer.ui.cli:main` و gui
- [ ] تست‌های قدیمی سبز
- [ ] module size: هیچ فایلی > ~400 خط (به‌جز gui در صورت نیاز)
- [ ] version = 3.0.0 (breaking: layout داخلی؛ CLI سازگار)

**PRها:**

1. `refactor(core): extract domain models, paths, and tag registry into package`
2. `refactor(metadata): introduce injectable clients and rewire processor`

---

## 6. Phase D — Test fortress → **v3.1.0**

**هدف:** pipeline واقعاً تست‌شده؛ CI coverage دروغ نگوید.

### D.1 ماتریس پوشش اجباری

| واحد | هدف coverage |
|---|---|
| `domain/*` | 95%+ |
| `tags/*` | 90%+ |
| `metadata/*` (با fake HTTP) | 85%+ |
| `organize/processor.py` | 90%+ |
| `organize/merge.py` | 90%+ |
| cache | 90%+ |

### D.2 تست‌ها

- **Unit pure:** matching, paths, LRC→SYLT, best_release, cache key/TTL
- **Unit with fakes:** MB client (responses متنوع), CAA bytes, LRCLIB
- **Integration tmp_path:** process_file کامل با stub transport — هیچ شبکه‌ای نرود
- **Property-ish:** `safe_name` هیچ‌وقت path traversal تولید نمی‌کند
- **Regression:** هر bug از CHANGELOG یک تست

### D.3 زیرساخت

- `tests/factories.py` — ساختن `TrackMeta` و fake recordings
- `tests/fake_http.py` — transport ساده dict-based
- حذف `sys.path` hack — نصب editable
- CI: `pytest --cov=music_organizer --cov-fail-under=75`

### D.4 DoD

- [ ] coverage gate در CI واقعی
- [ ] هیچ تست شبکه‌ای به اینترنت نمی‌زند
- [ ] version = 3.1.0

**PR:** `test(core): cover processor, merge, tags, and metadata with fakes`

---

## 7. Phase E — Packaging & CI → **v3.2.0**

**هدف:** نصب‌پذیر، build‌پذیر، CI معتبر.

### E.1 کارها

1. `pyproject.toml`:
   - `build-backend = "setuptools.build_meta"`
   - package discovery
   - optional extras: `gui`, `dev`, `all`
   - ruff + pyright + coverage config یک‌جا
2. حذف `requirements.txt` به‌عنوان منبع حقیقت (یا generate-only)
3. Single-source version در `__about__.py`
4. LICENSE فایل واقعی
5. PyInstaller spec مشترک با `config`/`package` درست (نه add-data اشتباه)
6. CI:
   - lint (ruff)
   - typecheck (pyright)
   - test matrix (کمتر از ۵×۳ کامل — اول 3.10/3.12/3.13 × ubuntu/windows)
   - coverage upload یا artifact
   - build EXE optional job (فقط windows)
7. User-Agent از `__version__` ساخته شود

### E.2 DoD

- [ ] `pip install -e ".[dev,gui]"` سبز
- [ ] `python -m music_organizer.ui.cli --version`
- [ ] build EXE حداقل یک‌بار verify شده
- [ ] version = 3.2.0

**PR:** `build(packaging): fix setuptools backend, license, and CI quality gates`

---

## 8. Phase F — UX & performance → **v3.3.0**

**هدف:** library بزرگ (۱۰k+ فایل) روان؛ GUI امن.

### F.1 کارها

1. Batch Treeview insert (هر ۲۰۰ ردیف)
2. Cancel واقعی: `urllib` → session با timeout کوتاه‌تر + abort event در میانهٔ pipeline
3. Cache negative results (miss) با TTL کوتاه‌تر (مثلاً ۶ ساعت)
4. Parallelism محدود و کنترل‌شده برای art/lyrics (pool کوچک) — MB همچنان rate-limit سریالی
5. CLI progress بدون وابستگی شکننده به rich در حالت fallback
6. فیلتر log مشترک بین CLI/GUI (یک policy، نه دو لیست کپی)
7. Keyboard: Space فقط وقتی focus روی دکمه‌ها نیست (یا حذف bind کلی)

### F.2 DoD

- [ ] bench ساده: 500 فایل fake I/O بدون freeze
- [ ] Stop زیر ۱ ثانیه بین فایل‌ها
- [ ] version = 3.3.0

**PR:** `perf(ui): batch updates, cancellable runs, and shared log policy`

---

## 9. Phase G — Product polish → **v4.0.0**

**هدف:** release‌ای که بتوانی بدون عذرخواهی نشان بدهی.

### G.1 کارها

1. README rewrite: واقعیت محض، architecture diagram، safety model
2. `docs/architecture.md` — dependency rules
3. `docs/matching.md` — چرا score و threshold
4. pin کردن SHA-256 فایل‌های fpcalc رسمی
5. حذف کد مرده (`is_mp3`, imports مرده, template غیرفعال)
6. Screenshot GUI در README
7. GitHub Release v4.0.0 + notes

### G.2 DoD

- [ ] هیچ ادعای README بدون کد نیست
- [ ] version = 4.0.0
- [ ] tag + release

**PR:** `docs(release): document safety model, architecture, and v4 claims`

---

## 10. ترتیب اجرای روزانه (الگوی TDD per ticket)

برای هر unit of work:

1. شاخه: `feat/<scope>-<short-name>` یا `fix/...`
2. تست fail بنویس
3. حداقل implementation برای سبز شدن
4. refactor با تست سبز
5. lint + typecheck
6. commit: `test(...)` سپس `feat/fix(...)` یا یک commit منسجم با پیام درست
7. PR وقتی یک week-of-work بسته شد
8. merge → delete branch
9. نسخه و CHANGELOG در انتهای phase

---

## 11. ریسک‌ها و تصمیم‌های باز

| ریسک | واکنش |
|---|---|
| rapidfuzz نمی‌خواهی | پیاده‌سازی token-ratio ساده در `domain/matching.py` — ولی threshold را با تست نگه دار |
| رفتار قدیمی write-to-source برای بعضی کاربران مهم است | opt-in `write_to_source` با هشدار، default خاموش |
| ۸ هفته زیاد است | می‌توان A+B را فوری‌تر برد؛ C بدون A/B خطرناک است |
| فارسی/عربی در tags | `safe()` unicode-aware بماند؛ تست unicode در Phase D |

**ترتیب اجباری:** A → B → C → D → E → F → G  
هیچ‌وقت C (بازسازی) قبل از A (امنیت) نرود — refactor روی کد خطرناک یعنی انتقال خطر با سرعت بیشتر.

---

## 12. Checkpoint نسخه

بعد از هر phase در گفتگو گزارش می‌دهم:

```
Phase done: A — Safety net
Version: 2.2.0
PR: <url یا merge status>
Tests: N passed · coverage X%
Next: Phase B — Album-centric matching (first red test: prefer_oldest + user album)
```

---

## 13. اکنون

**Version: 2.1.0**  
**Phase بعدی: A — Safety net → 2.2.0**  
**اولین تست red:** جلوگیری از mutate شدن source در `process_file` با write_tags فعال.

منتظر چراغ سبز برای شروع Phase A هستم. اگر threshold matching یا prefer_oldest را می‌خواهی از همین الان تغییر بدهی، الان بگو — بعد از B دیر است.
