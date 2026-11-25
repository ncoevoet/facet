"""Machine licence gate for the reference photo set (GitHub issue #393, amendment 2026-11-25).

Reads researcher candidate JSONL files, verifies every licence from the source's own metadata and
writes partial manifest photo entries that ``make_reference_set.py --pin`` completes with sha256
and byte counts.

* Wikimedia Commons: ``extmetadata.LicenseShortName`` fetched twice independently (pinning the file
  revision's ``sha1`` and ``timestamp``). Files in a copyright or deletion problem category are
  rejected as ``copyright_problem``; ``Restrictions: personality`` is kept and flagged in ``notes``.
  A maxlag or other API error is retried (honouring ``Retry-After``, capped at 60 s), never cached,
  and after the retries becomes an ``api_error`` rejection, never ``not_found``.
* raw.pixls.us: the licence is read per sample from the repository feed (1874 samples are CC0, 146
  are CC BY-NC-SA); only a CC0 row is accepted, and its sha256 and megapixels are recorded
  (``licence_evidence.expected_sha256``, entry ``sha256``) for ``--pin`` to compare.
* Any other source is rejected as ``source_unsupported``.

The manifest given by ``--manifest`` (default: the committed one) is read so that new ids continue
after the existing ``<case>-NN`` ids (an id is never reused), ``--max-per-case`` counts the photos
already there, and a url already present is skipped as ``already_present``.

Layout of ``path`` (relative POSIX): companion pairs under ``companions/`` sharing one stem (the RAW
is ``scored: false`` and ``companion_of`` the JPEG id), sequence frames under
``sequences/<set_id>/``, other RAW formats under ``raw/``, derived files under ``derived/`` and
everything else under the case group directory.

    python testdb/licence_check.py CANDIDATES.jsonl [...] --out APPROVED.json --rejected REJECTED.json
"""


import argparse
import email.utils
import html
import copy
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from make_reference_set import RecipeError, parse_recipe
from reference_common import (
    DEFAULT_MAX_PHOTOS,
    DEFAULT_MIN_PHOTOS,
    DERIVABLE_LICENCE,
    FORMATS,
    LICENCE_PATTERN,
    MANIFEST_PATH,
    SHARE_ALIKE_PATTERN,
    load_manifest,
)

USER_AGENT = "FacetReferenceSet/1.0 (https://github.com/ncoevoet/facet)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_PAGE = "https://commons.wikimedia.org/wiki/"
BATCH_SIZE = 50
PIXLS_FEED = "https://raw.pixls.us/json/getrepository.php?set=all"
PIXLS_FILELIST = "https://raw.pixls.us/data/filelist.sha256"
PIXLS_DATA = "https://raw.pixls.us/data/"
BASE_DATE = datetime(2001, 1, 1)
PIXLS_CC0 = "creativecommons.org/publicdomain/zero/1.0"
RAW_FORMATS = ("cr2", "cr3", "nef", "arw", "raf", "rw2", "orf", "pef", "dng", "srw")
MAX_AUTHOR = 200
MAX_WAIT = 60.0
PROBLEM_CATEGORIES = re.compile(
    r"copyright violation|deletion request|permission pending|permission received|otrs pending"
    r"|no permission since|no source since|no license since|non-free|speedy deletion"
    r"|possibly unfree|unfree|files with no machine-readable (?:license|licence|author|source)",
    re.I,
)
CHILD_WORDS = ("children", "minors", "girls", "boys", "kids")

_TAG = re.compile(r"<[^>]+>")
_NC_ND = re.compile(r"(?:^|[\s-])(NC|ND)(?:$|[\s-])")
_CC_BY = re.compile(r"CC[ -]BY(-SA)?[ -](\d\.\d)", re.I)
_CC0 = re.compile(r"CC0(?:[ -]1\.0)?|CC[ -]ZERO", re.I)
_PD = re.compile(r"PD(?:[- ][\w.\- ]*)?|Public domain", re.I)


_HIDDEN = re.compile(r"<(\w+)[^>]*display:\s*none[^>]*>.*?</\1\s*>", re.I | re.S)
_DOUBLED = re.compile(r"(.{3,}?)\s*\1")


def strip_html(value):
    """Plain text of an extmetadata HTML fragment (hidden elements dropped, repeats collapsed)."""
    text = html.unescape(_TAG.sub("", _HIDDEN.sub("", str(value or ""))))
    text = re.sub(r"\s+", " ", text).strip()
    doubled = _DOUBLED.fullmatch(text)
    return doubled.group(1) if doubled else text


def normalise_licence(raw):
    """``(manifest value | None, reason)`` for a Commons ``LicenseShortName``."""
    text = str(raw or "").strip()
    if not text:
        return None, "licence_unreadable"
    if _NC_ND.search(text.upper()):
        return None, "nc_nd"
    if _CC0.fullmatch(text):
        return "CC0-1.0", None
    match = _CC_BY.fullmatch(text)
    if match:
        value = f"CC-BY-SA-{match.group(2)}" if match.group(1) else f"CC-BY-{match.group(2)}"
        if LICENCE_PATTERN.fullmatch(value) or SHARE_ALIKE_PATTERN.fullmatch(value):
            return value, None
        return None, "licence_not_allowed"
    if _PD.fullmatch(text):
        return "PD", None
    return None, "licence_not_allowed"


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ApiError(Exception):
    """The source kept answering with an error after every retry."""


def api_error_of(url, body, headers=None):
    """The MediaWiki error code of a Commons API reply that is an error, else ``None``."""
    if not url.startswith(COMMONS_API):
        return None
    header = (headers or {}).get("mediawiki-api-error")
    if header:
        return str(header)
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if isinstance(data, dict) and "error" in data:
        error = data["error"]
        return str(error.get("code", "error") if isinstance(error, dict) else error)
    return None


def retry_delay(value, default):
    """Seconds to wait: ``Retry-After`` (number or HTTP date) else ``default``, capped at 60."""
    seconds = default
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(str(value))
                seconds = (when - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError):
                seconds = default
    return min(max(seconds, 0.0), MAX_WAIT)


def http_fetch(url, retries=5):
    """GET ``url`` as text, backing off on 429, 5xx and MediaWiki API errors (maxlag)."""
    delay, last = 2.0, "no attempt"
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        wait = delay
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf8", errors="replace")
                code = api_error_of(url, body, response.headers)
                if code is None:
                    return body
                last, wait = f"api error {code}", retry_delay(response.headers.get("Retry-After"), delay)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504):
                raise
            last, wait = f"HTTP {error.code}", retry_delay(error.headers.get("Retry-After"), delay)
        except urllib.error.URLError as error:
            last = str(error)
        if attempt < retries - 1:
            time.sleep(wait)
            delay = min(delay * 2, MAX_WAIT)
    raise ApiError(f"{url}: {last} after {retries} attempts")


class CachedFetch:
    """``fetch(url) -> (body, fetched_at)`` over a JSON file so re-runs are cheap."""

    def __init__(self, fetch, path=None):
        self.fetch, self.path, self.dirty = fetch, path, False
        self.data = {}
        if path and Path(path).exists():
            self.data = json.loads(Path(path).read_text(encoding="utf8"))

    def __call__(self, url):
        if url not in self.data:
            body = self.fetch(url)
            code = api_error_of(url, body)
            if code is not None:
                raise ApiError(f"{url}: api error {code}")  # an error reply is never cached
            self.data[url] = {"body": body, "fetched_at": now_utc()}
            self.dirty = True
        entry = self.data[url]
        return entry["body"], entry["fetched_at"]

    def save(self):
        if self.path and self.dirty:
            Path(self.path).write_text(json.dumps(self.data, indent=1), encoding="utf8")


def commons_url(titles, read_no=None, extra=None):
    params = {
        "action": "query", "format": "json", "prop": "imageinfo|categories",
        "iiprop": "url|size|mime|extmetadata|sha1|timestamp", "cllimit": "max", "maxlag": "5",
        "titles": "|".join(titles),
    }
    if read_no is not None:
        params["_read"] = str(read_no)  # distinct request and cache key per independent read
    params.update(extra or {})
    return f"{COMMONS_API}?{urllib.parse.urlencode(params)}"


def evidence_url(title):
    """Reproducible single-title form of the API query, recorded as evidence."""
    return commons_url([title])


def commons_read(titles, read_no, cached):
    """``{title: record | None}`` for one independent read of up to 50 titles."""
    pages, normalized, stamp, extra = {}, {}, None, {}
    while True:
        body, stamp = cached(commons_url(titles, read_no, extra))
        data = json.loads(body)
        query = data.get("query", {})
        for item in query.get("normalized", []):
            normalized[item["from"]] = item["to"]
        for page in query.get("pages", {}).values():
            slot = pages.setdefault(page.get("title"), {"categories": []})
            slot["missing"] = "missing" in page or "invalid" in page
            if page.get("imageinfo"):
                slot["info"] = page["imageinfo"][0]
            slot["categories"] += [c.get("title", "") for c in page.get("categories", [])]
        if "continue" not in data:
            break
        extra = dict(data["continue"])
    result = {}
    for title in titles:
        page = pages.get(normalized.get(title, title))
        ok = page and not page["missing"] and page.get("info")
        result[title] = {**page, "fetched_at": stamp} if ok else None
    return result


def meta_value(info, key):
    return strip_html(((info.get("extmetadata") or {}).get(key) or {}).get("value", ""))


def raw_meta_value(info, key):
    return str(((info.get("extmetadata") or {}).get(key) or {}).get("value", "")).strip()


def candidate_key(candidate):
    return candidate.get("title") or candidate.get("direct_url") or candidate.get("page_url") or ""


def candidate_cases(candidate):
    cases = [candidate.get("case")] + list(candidate.get("covers_also") or [])
    return [c for i, c in enumerate(cases) if c and c not in cases[:i]]


def reject(candidate, reason, detail=""):
    return {"key": candidate_key(candidate), "reason": reason, "detail": detail,
            "cases": candidate_cases(candidate), "candidate": candidate}


def merge_candidates(candidates):
    """Dedupe by key, unioning the cases; the first proposal's case stays primary."""
    merged = {}
    for candidate in candidates:
        key = candidate_key(candidate)
        if candidate.get("derive"):
            key += "|" + json.dumps(candidate["derive"], sort_keys=True)
        if key not in merged:
            merged[key] = dict(candidate)
            continue
        have = merged[key]
        union = candidate_cases(have) + candidate_cases(candidate)
        have["covers_also"] = [c for c in dict.fromkeys(union) if c != have.get("case")]
        for flag in ("identifiable_people", "child", "ai_generated"):
            have[flag] = bool(have.get(flag)) or bool(candidate.get(flag))
    return list(merged.values())


def format_and_ext(url_or_path):
    """``(format, extension)`` using the case-sensitive FORMATS enum, or ``(None, ext)``."""
    path = urllib.parse.unquote(urllib.parse.urlparse(url_or_path).path)
    suffix = PurePosixPath(path).suffix.lstrip(".")
    if suffix in FORMATS:
        return suffix, suffix
    lower = suffix.lower()
    if lower in ("jpg", "jpeg"):
        return "jpeg", "jpg"
    if lower in ("tif", "tiff"):
        return "tiff", "tif"
    if lower in FORMATS:
        return lower, lower
    return None, suffix


def screen_flags(candidate, categories=()):
    cats = " | ".join(categories).lower()
    if candidate.get("ai_generated") or "ai-generated" in cats or "ai generated" in cats:
        return "ai_generated"
    if candidate.get("child"):
        return "child"
    if candidate.get("identifiable_people") and any(w in cats for w in CHILD_WORDS):
        return "child"
    return None


def problem_category(categories):
    """The first Commons copyright/deletion problem category, else ``None``."""
    return next((c for c in categories if PROBLEM_CATEGORIES.search(c)), None)


def clean_url(url):
    """``url`` without its query and fragment."""
    return urllib.parse.urlsplit(url)._replace(query="", fragment="").geturl()


def check_commons(candidate, reads):
    """Approved partial entry or a rejection for one Commons candidate (reads: two records)."""
    first, second = reads
    failed = next((r for r in reads if r and "api_error" in r), None)
    if failed:
        return reject(candidate, "api_error", failed["api_error"])
    if first is None or second is None:
        return reject(candidate, "not_found")
    categories = first["categories"] + second["categories"]
    problem = problem_category(categories)
    if problem:
        return reject(candidate, "copyright_problem", problem)
    flag = screen_flags(candidate, categories)
    if flag:
        return reject(candidate, flag)
    raws = [raw_meta_value(r["info"], "LicenseShortName") for r in reads]
    if not all(raws):
        return reject(candidate, "licence_unreadable", repr(raws))
    norm = [normalise_licence(raw) for raw in raws]
    if norm[0] != norm[1]:
        return reject(candidate, "second_read_mismatch", repr(raws))
    licence, reason = norm[0]
    if licence is None:
        return reject(candidate, reason, raws[0])
    info = first["info"]
    full = meta_value(info, "Artist") or meta_value(info, "Credit") or meta_value(info, "Attribution")
    if not full:
        return reject(candidate, "author_missing")
    title = candidate["title"].replace(" ", "_")
    page = COMMONS_PAGE + urllib.parse.quote(title, safe=":_()%,'")
    fmt, ext = format_and_ext(info.get("url", ""))
    if fmt is None:
        return reject(candidate, "format_unknown", info.get("url", ""))
    evidence = {
        "api_url": evidence_url(candidate["title"]), "license_short_name": raws[0],
        "usage_terms": meta_value(info, "UsageTerms"), "fetched_at": first["fetched_at"],
        "second_read_matches": True, "sha1": info.get("sha1"), "timestamp": info.get("timestamp"),
        "attribution_required": raw_meta_value(info, "AttributionRequired"),
    }
    entry = {
        "url": clean_url(info["url"]), "licence": licence, "author": full[:MAX_AUTHOR],
        "source_page": page, "attribution": f"{full}, {licence}, via Wikimedia Commons ({page})",
        "licence_evidence": evidence, "format": fmt, "_ext": ext,
    }
    restrictions = raw_meta_value(info, "Restrictions").lower()
    if "personality" in restrictions and not candidate.get("public_figure"):
        entry["_note"] = "Commons Restrictions: personality rights"
    if SHARE_ALIKE_PATTERN.fullmatch(licence):
        entry["share_alike_ok"] = True
        entry["change_notice"] = "unmodified"
    return entry


def _norm(text):
    return re.sub(r"[\s_]+", " ", urllib.parse.unquote(str(text))).strip().lower()


_GETFILE = re.compile(r"getfile\.php/(\d+)/nice/([^'\"]+)")
_SHA = re.compile(r"sha256 Checksum'>\s*([0-9a-fA-F]{64})")
_HREF = re.compile(r"href=['\"]([^'\"]+)")


def parse_pixls_feed(body):
    """Feed rows as dicts: id, filename, make, model, licence href, sha256, megapixels, url."""
    rows = []
    for row in json.loads(body).get("data", []):
        found = _GETFILE.search(str(row[7]))
        if not found:
            continue
        licence = _HREF.search(str(row[5]))
        sha = _SHA.search(str(row[7]))
        name = urllib.parse.unquote(found.group(2))
        rows.append({
            "id": found.group(1), "filename": name, "make": str(row[0]), "model": str(row[1]),
            "licence_href": licence.group(1) if licence else "",
            "sha256": sha.group(1).lower() if sha else None, "megapixels": row[3],
            "url": f"https://raw.pixls.us/getfile.php/{found.group(1)}/nice/{urllib.parse.quote(name)}",
        })
    return rows


def parse_filelist(body):
    """``{path: sha256}`` of ``filelist.sha256`` lines (``<sha256> *<path>``, path under /data/)."""
    found = {}
    for line in body.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [* ](.+)", line.rstrip("\r\n"))
        if match:
            found[match.group(2)] = match.group(1).lower()
    return found


def unquote_all(text):
    """Percent-decode until stable (researchers sometimes double-encode ``[`` and ``]``)."""
    text = str(text)
    for _ in range(4):
        decoded = urllib.parse.unquote(text)
        if decoded == text:
            break
        text = decoded
    return text


def data_path(candidate):
    """The decoded path under ``/data/`` of a candidate's direct or page URL, or None."""
    for field in ("direct_url", "page_url"):
        path = urllib.parse.urlparse(str(candidate.get(field) or "")).path
        if path.startswith("/data/") and not path.endswith("/"):
            return unquote_all(path[len("/data/"):])
    return None


def pixls_row(candidate, rows, filelist=None):
    """``(row | None, detail, data_url)``: by getfile id, /data/ path sha256, else make + model + filename."""
    for field in ("direct_url", "page_url"):
        found = re.search(r"getfile\.php/(\d+)", str(candidate.get(field) or ""))
        if found:
            hit = [r for r in rows if r["id"] == found.group(1)]
            return (hit[0], "", None) if hit else (None, f"no feed row for getfile id {found.group(1)}", None)
    path = data_path(candidate)
    if path and filelist is not None:
        files = filelist()
        sha = files.get(path)
        if sha is None:
            lowered = {k.lower(): v for k, v in files.items()}
            sha = lowered.get(path.lower())
        hits = [r for r in rows if sha and r["sha256"] == sha]
        hits.sort(key=lambda r: r["licence_href"].rstrip("/").lower() != PIXLS_CC0)
        if hits:
            return hits[0], "", PIXLS_DATA + urllib.parse.quote(path)
    return pixls_name_row(candidate, rows) + (None,)


def pixls_name_row(candidate, rows):
    """``(row | None, detail)`` by make + model + filename segments."""
    paths = [urllib.parse.urlparse(str(candidate.get(f) or "")).path for f in ("direct_url", "page_url")]
    segments = {_norm(s) for path in paths for s in path.split("/") if s}
    hits = [r for r in rows
            if _norm(r["make"]) in segments and _norm(r["model"]) in segments
            and _norm(r["filename"]) in segments]
    if len(hits) == 1:
        return hits[0], ""
    return None, "ambiguous feed rows" if hits else "no feed row matched make + model + filename"


def check_pixls(candidate, feed):
    """Accept a raw.pixls.us sample only when its own feed row says CC0 1.0."""
    flag = screen_flags(candidate)
    if flag:
        return reject(candidate, flag)
    if feed is None:
        return reject(candidate, "api_error", "repository feed unavailable")
    row, detail, data_url = pixls_row(candidate, feed[0], feed[2] if len(feed) > 2 else None)
    if row is None:
        return reject(candidate, "not_found", detail)
    href = re.sub(r"^https?://", "", row["licence_href"]).rstrip("/").lower()
    if href != PIXLS_CC0:
        reason = "nc_nd" if re.search(r"by-n[cd]", href) else "licence_not_allowed"
        return reject(candidate, reason, row["licence_href"])
    if not row["sha256"]:
        return reject(candidate, "licence_unreadable", "feed row has no sha256")
    fmt, ext = format_and_ext(row["url"])
    if fmt is None:
        return reject(candidate, "format_unknown", row["url"])
    page = candidate.get("page_url") or row["url"]
    return {
        "url": data_url or row["url"], "licence": "CC0-1.0", "author": "raw.pixls.us contributors",
        "source_page": page, "attribution": f"raw.pixls.us contributors, CC0-1.0, raw.pixls.us ({page})",
        "licence_evidence": {
            "api_url": PIXLS_FEED, "license_short_name": row["licence_href"],
            "usage_terms": "CC0 1.0 Universal", "fetched_at": feed[1], "second_read_matches": True,
            "expected_sha256": row["sha256"],
        },
        "format": fmt, "_ext": ext, "sha256": row["sha256"], "megapixels": row["megapixels"],
    }


def verify_commons_candidates(candidates, cached):
    commons = [c for c in candidates if c.get("source") == "commons" and c.get("title")]
    titles = sorted({c["title"] for c in commons})
    first, second = {}, {}
    for start in range(0, len(titles), BATCH_SIZE):
        batch = titles[start:start + BATCH_SIZE]
        for read_no, into in ((1, first), (2, second)):
            try:
                into.update(commons_read(batch, read_no, cached))
            except ApiError as error:
                into.update({t: {"api_error": str(error)} for t in batch})
    return {c["title"]: (first.get(c["title"]), second.get(c["title"])) for c in commons}


def lazy_filelist(fetch):
    """A memoised loader of ``filelist.sha256``; an unreachable list reads as empty."""
    state = {}

    def load():
        if "files" not in state:
            try:
                state["files"] = parse_filelist(fetch(PIXLS_FILELIST)[0])
            except (ApiError, urllib.error.URLError, OSError):
                state["files"] = {}
        return state["files"]

    return load


def verify_all(candidates, fetch):
    """``(verified {key: (candidate, entry)}, rejected)`` for the non-derived candidates."""
    reads = verify_commons_candidates(candidates, fetch)
    feed = None
    if any(c.get("source") == "rawpixls" for c in candidates):
        try:
            body, stamp = fetch(PIXLS_FEED)
            feed = (parse_pixls_feed(body), stamp, lazy_filelist(fetch))
        except (ApiError, urllib.error.URLError, OSError, ValueError):
            feed = None
    verified, rejected = {}, []
    for candidate in sorted(candidates, key=candidate_key):
        if candidate.get("derive"):
            continue
        if candidate.get("source") == "commons":
            if candidate.get("title"):
                result = check_commons(candidate, reads[candidate["title"]])
            else:
                result = reject(candidate, "not_found", "commons candidate without title")
        elif candidate.get("source") == "rawpixls":
            result = check_pixls(candidate, feed)
        else:
            result = reject(candidate, "source_unsupported", str(candidate.get("source")))
        if "reason" in result:
            rejected.append(result)
        else:
            verified[candidate_key(candidate)] = (candidate, result)
    return verified, rejected


def entry_directory(candidate, source, group, derived, companion):
    if derived:
        return f"derived/{group}"
    if companion:
        return "companions"
    sequence = candidate.get("sequence")
    if isinstance(sequence, dict) and sequence.get("set_id") not in (None, ""):
        return "sequences/" + re.sub(r"[^\w.-]", "_", str(sequence["set_id"]))
    if source["format"].lower() in RAW_FORMATS:
        return "raw"
    if candidate.get("auto_base"):
        return "bases"
    return group


# --- recipes -------------------------------------------------------------------------------

_STEP_MAP = (
    (re.compile(r"grayscale"), "to_grayscale"),
    (re.compile(r"sepia"), "to_sepia"),
    (re.compile(r"crop:center_square"), "crop_aspect:1x1"),
    (re.compile(r"crop:(\d+x\d+)"), r"crop_aspect:\1"),
    (re.compile(r"resize:max_edge=(\d+)"), r"resize:\1"),
    (re.compile(r"reencode_jpeg:q(\d+)"), r"reencode_jpeg:\1"),
    (re.compile(r"to_(\d+)bit_(png|tiff)"), r"to_\1bit:\2"),
    (re.compile(r"encode_heic"), "encode_heic:90"),
    (re.compile(r"write_xmp_sidecar\((.*)\)"), r"write_xmp_sidecar:\1"),
)


def normalise_recipe(raw):
    """Map a researcher's recipe spelling onto the canonical grammar of ``make_reference_set``."""
    text = str(raw or "").strip()
    if re.search(r"extract embedded|^render_jpeg_from_raw", text):
        return "raw_embedded_jpeg"
    text = re.sub(r"write_xmp_sidecar\(([^)]*)\)", r"write_xmp_sidecar:\1", text)
    text = re.sub(r"\s*\([^)]*\)", "", text)
    steps = []
    for part in re.split(r"[;+]", text):
        part = part.strip()
        for pattern, replacement in _STEP_MAP:
            if pattern.fullmatch(part):
                part = pattern.sub(replacement, part)
                break
        steps.append(part)
    return ";".join(steps)


def recipe_extension(steps, base_ext):
    """``(extension, format)`` of a derived output, following its ops."""
    ops = [op for op, _ in steps]
    if "write_xmp_sidecar" in ops:
        return "xmp", "xmp"
    if "raw_embedded_jpeg" in ops:
        return "jpg", "jpeg"
    if "encode_heic" in ops:
        return "heic", "heic"
    if ops[-1] == "to_16bit":
        return ("png", "png") if steps[-1][1] == "png" else ("tif", "tiff")
    return (base_ext, "jpeg") if base_ext in ("jpg", "jpeg") else (base_ext, base_ext)


def add_datetimes(entries):
    """Give each JPEG/TIFF variant of one base its own capture time (2001-01-01 + N hours)."""
    groups = {}
    for entry in entries:
        if entry.get("kind") != "derived" or entry["path"].rsplit(".", 1)[-1] not in ("jpg", "tif"):
            continue
        steps = parse_recipe(entry["recipe"])
        if any(op in ("set_exif_datetime", "raw_embedded_jpeg", "write_xmp_sidecar") for op, _ in steps):
            continue
        groups.setdefault(entry["derived_from"], []).append((entry, steps))
    for variants in groups.values():
        for index, (entry, steps) in enumerate(sorted(variants, key=lambda v: v[0]["id"]), 1):
            stamp = (BASE_DATE + timedelta(hours=index)).strftime("%Y:%m:%d %H:%M:%S")
            texts = [f"{op}:{arg}" if arg else op for op, arg in steps]
            at = len(texts) - 1 if steps[-1][0] == "to_16bit" else len(texts)
            texts.insert(at, f"set_exif_datetime:{stamp}")
            entry["recipe"] = ";".join(texts)
            parse_recipe(entry["recipe"])


# --- base lookup ---------------------------------------------------------------------------

def ref_keys(value):
    """Lookup keys of a title / URL / filename: the decoded path and its bare file name."""
    text = unquote_all(value or "").strip()
    if not text:
        return set()
    text = re.sub(r"^https?://[^/]+/", "", text.split("#")[0].split("?")[0])
    name = re.sub(r"^file:", "", text.rsplit("/", 1)[-1], flags=re.I)
    keys = {"name:" + _norm(name)}
    if "/" in text:
        keys.add("path:" + _norm(re.sub(r"^(data|wiki)/", "", text)))
    return keys


def derive_refs(candidate):
    spec = candidate.get("derive") or {}
    return [spec[k] for k in ("from_case_candidate", "from_title", "from_url") if spec.get(k)]


def auto_base_candidate(ref, derived):
    """A base candidate for a derivation source that no candidate covers, or None."""
    if re.match(r"file:", str(ref), re.I):
        return {"case": None, "source": "commons", "title": str(ref), "page_url": None,
                "covers_also": [], "derive": None, "auto_base": True,
                "notes": "auto-added derivation base"}
    if str(ref).startswith(PIXLS_DATA) or derived.get("source") == "rawpixls":
        direct = str(ref) if str(ref).startswith(PIXLS_DATA) else derived.get("direct_url")
        if direct and ref_keys(ref) & ref_keys(direct):
            return {"case": None, "source": "rawpixls", "title": None, "direct_url": direct,
                    "page_url": derived.get("page_url"), "covers_also": [], "derive": None,
                    "auto_base": True, "notes": "auto-added derivation base"}
    return None


def add_auto_bases(candidates):
    covered = set()
    for candidate in candidates:
        if not candidate.get("derive"):
            for field in ("title", "page_url", "direct_url"):
                covered |= ref_keys(candidate.get(field))
    extra = {}
    for candidate in candidates:
        refs = derive_refs(candidate)
        if not refs or any(ref_keys(ref) & covered for ref in refs):
            continue
        base = auto_base_candidate(refs[0], candidate)
        if base:
            extra.setdefault(candidate_key(base), base)
    return candidates + list(extra.values())


PAIR_CASE = "comp-raw-jpeg"


def set_id_of(item):
    sequence = item.get("sequence")
    sid = sequence.get("set_id") if isinstance(sequence, dict) else None
    return None if sid in (None, "") else sid


def set_key(item):
    """The identity a sequence case counts: the set id, or the photo itself when it has none."""
    sid = set_id_of(item)
    return ("set", sid) if sid is not None else ("photo", item.get("id") or candidate_key(item))


def run(candidates, manifest, fetch, max_per_case=DEFAULT_MAX_PHOTOS, date=None):
    """``(approved, rejected, short)``; ``fetch`` is a ``CachedFetch``-style callable."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cases = manifest["cases"]
    existing = manifest.get("photos") or []
    present = {clean_url(p["url"]) for p in existing if p.get("url")}
    counts, last = {}, {}
    # Sequence-group cases count SETS (one per sequence.set_id, a lone frame being its own set).
    seq_cases = {c for c, spec in cases.items() if spec.get("group") == "sequences"}
    set_members = {c: set() for c in seq_cases}
    for photo in existing:
        for case in photo.get("cases") or ():
            if case in seq_cases:
                set_members[case].add(set_key(photo))
                counts[case] = len(set_members[case])
            else:
                counts[case] = counts.get(case, 0) + 1
        found = re.fullmatch(r"(.+)-(\d+)", str(photo.get("id")))
        if found:
            last[found.group(1)] = max(last.get(found.group(1), 0), int(found.group(2)))
    candidates = add_auto_bases(merge_candidates(candidates))
    verified, rejected = verify_all(candidates, fetch)
    bases = {c["companion_of"] for c in candidates if c.get("companion_of")}
    approved, lookup = [], {}
    paths = {p.get("path") for p in existing}
    sources, placed_keys = {}, set()
    companion_cases = {c for c, spec in cases.items() if spec.get("group") == "companions"}

    def case_open(case, skey):
        if case in seq_cases:
            return skey in set_members[case] or len(set_members[case]) < max_per_case
        # comp-raw-jpeg counts PAIRS: only the derived JPEG is counted, its RAW rides along.
        return counts.get(case, 0) < max_per_case

    def place(candidate, source, derived_from=None, companion=None, output=None):
        wanted = candidate_cases(candidate)
        auto = bool(candidate.get("auto_base"))
        known = [c for c in wanted if c in cases]
        if not known and not auto:
            rejected.append(reject(candidate, "case_unknown", ", ".join(wanted)))
            return
        if not derived_from and clean_url(source["url"]) in present:
            rejected.append(reject(candidate, "already_present", source["url"]))
            return
        skey = set_key(candidate)
        open_cases = [c for c in known if case_open(c, skey)]
        if not open_cases and not auto:
            rejected.append(reject(candidate, "case_full", ", ".join(known)))
            return
        primary = open_cases[0] if open_cases else "base"
        pid = f"{primary}-{last.get(primary, 0) + 1:02d}"
        group = cases[primary]["group"] if open_cases else "bases"
        ext, fmt = output or (source["_ext"], source["format"])
        in_pair = companion is not None or any(
            candidate.get(f) in bases for f in ("title", "page_url", "direct_url") if candidate.get(f))
        directory = entry_directory(candidate, source, group, derived_from, in_pair)
        stem = companion["path"].rsplit("/", 1)[1].rsplit(".", 1)[0] if companion else pid
        raw_pair = bool(derived_from) and fmt == "jpeg" and str(
            (candidate.get("derive") or {}).get("recipe")) == "raw_embedded_jpeg"
        if raw_pair:
            # The JPEG stands in for its RAW: the pair shares companions/<stem>, as facet.py's
            # RAW suppression needs (same directory, same stem).
            directory = "companions"
            stem = derived_from["path"].rsplit("/", 1)[1].rsplit(".", 1)[0]
            raw_path = f"companions/{stem}.{derived_from['path'].rsplit('.', 1)[1]}"
            if raw_path != derived_from["path"] and raw_path in paths:
                rejected.append(reject(candidate, "duplicate_path", raw_path))
                return
            paths.add(raw_path)
        if fmt == "xmp":
            directory, _, stem = derived_from["path"].rpartition("/")
            stem = stem.rsplit(".", 1)[0]
        path = f"{directory}/{stem}.{ext}"
        if path in paths:
            rejected.append(reject(candidate, "duplicate_path", path))
            return
        paths.add(path)
        last[primary] = last.get(primary, 0) + 1
        # A companion is scored: false, so only the companions group may list it.
        if companion:
            open_cases = [c for c in open_cases if c in companion_cases]
        for case in open_cases:
            if case in seq_cases:
                set_members[case].add(skey)
                counts[case] = len(set_members[case])
            else:
                counts[case] = counts.get(case, 0) + 1
        notes = " ".join(n for n in (candidate.get("notes") or "", source.get("_note") or "") if n)
        entry = {
            "id": pid, "path": path,
            "url": None if derived_from else source["url"],
            "kind": "derived" if derived_from else "download",
            "licence": source["licence"], "author": source["author"],
            "source_page": source["source_page"], "attribution": source["attribution"],
            "approved_by": "licence-check", "approved_on": date,
            "licence_evidence": source["licence_evidence"],
            "cases": open_cases, "format": fmt, "notes": notes,
        }
        for extra in ("share_alike_ok", "change_notice") + (() if derived_from else ("sha256",)):
            if extra in source:
                entry[extra] = source[extra]
        megapixels = source.get("megapixels") or candidate.get("megapixels")
        if megapixels:
            entry["megapixels"] = megapixels
        if isinstance(candidate.get("sequence"), dict):
            entry["sequence"] = candidate["sequence"]
        if companion:
            entry["companion_of"] = companion["id"]
            entry["scored"] = False
        if derived_from:
            entry["derived_from"] = derived_from["id"]
            entry["recipe"] = candidate["derive"]["recipe"]
            if fmt == "xmp":
                entry["companion_of"] = derived_from["id"]
                entry["scored"] = False
            if raw_pair:
                # The RAW moves beside the JPEG as its companion; run() trims its cases to the
                # companions group once the pair is placed.
                derived_from["path"] = raw_path
                derived_from["companion_of"] = pid
                derived_from["scored"] = False
        approved.append(entry)
        sources[pid] = source
        if not derived_from:
            placed_keys.add(candidate_key(candidate))
            for field in ("title", "page_url", "direct_url"):
                for key in ref_keys(candidate.get(field)):
                    lookup.setdefault(key, (entry, source))

    def find_base(candidate):
        refs = derive_refs(candidate)
        for ref in refs:
            for key in sorted(ref_keys(ref), key=lambda k: not k.startswith("path:")):
                if key in lookup:
                    return lookup[key], str(ref)
        return None, str(refs[0] if refs else None)

    def strippable(entry):
        """The non-companion cases of ``entry`` if dropping them keeps every case at min_photos."""
        own = [c for c in entry["cases"] if c not in companion_cases]
        for case in own:
            if counts.get(case, 0) - 1 < cases[case].get("min_photos", DEFAULT_MIN_PHOTOS):
                return None
        return own

    def choose_companion_raw(base_entry, base_source):
        """``(entry, source, cases_to_strip)`` of the RAW to pair with an embedded JPEG, or None.

        A companion RAW is ``scored: false``, so facet.py never produces golden output for it and
        any non-companion case left on it would count a photo that is never checked."""
        fmt = base_source["format"].lower()
        if not base_entry.get("companion_of") and strippable(base_entry) == []:
            return base_entry, base_source, []
        for key in sorted(verified):
            candidate, source = verified[key]
            if (key in placed_keys or candidate.get("derive") or source["format"].lower() != fmt
                    or source["licence"] != DERIVABLE_LICENCE
                    or not any(r["key"] == key and r["reason"] == "case_full" for r in rejected)):
                continue
            rejected[:] = [r for r in rejected if not (r["key"] == key and r["reason"] == "case_full")]
            before = len(approved)
            place({**candidate, "auto_base": True}, source)
            if len(approved) > before:
                return approved[-1], source, []
        others = sorted((e for e in approved if e["kind"] == "download" and not e.get("companion_of")
                         and e["format"].lower() == fmt and e["licence"] == DERIVABLE_LICENCE
                         and e["id"] in sources and strippable(e) is not None),
                        key=lambda e: (e is not base_entry, e["id"]))
        if others:
            return others[0], sources[others[0]["id"]], strippable(others[0])
        return None

    pairs = [k for k in sorted(verified) if verified[k][0].get("companion_of")]
    # Sequence sets are atomic: every frame of a set.set_id is kept or none is.
    failed_sets = {}
    for item in rejected:
        sid = set_id_of(item["candidate"])
        if sid is not None:
            failed_sets.setdefault(sid, item)
    set_keys = {}
    for key in sorted(verified):
        sid = set_id_of(verified[key][0])
        if sid is not None and key not in pairs:
            set_keys.setdefault(sid, []).append(key)

    def reject_set(sid, why):
        for member in set_keys[sid]:
            rejected.append(reject(verified[member][0], "set_member_rejected", f"{sid}: {why}"))

    def place_set(sid):
        saved = (copy.copy(counts), copy.copy(last), set(paths), len(approved), copy.copy(lookup),
                 copy.copy(sources), set(placed_keys), {c: set(v) for c, v in set_members.items()},
                 len(rejected))
        for member in set_keys[sid]:
            place(*verified[member])
            if len(rejected) > saved[-1]:
                bad = rejected[saved[-1]]
                for live, old in zip((counts, last, paths, lookup, sources, placed_keys), saved[:3] + saved[4:7]):
                    live.clear()
                    live.update(old)
                del approved[saved[3]:]
                for c in set_members:
                    set_members[c] = saved[7][c]
                del rejected[saved[-1]:]
                reject_set(sid, f"{bad['key']}: {bad['reason']}")
                return

    for sid, item in failed_sets.items():
        if sid in set_keys:
            reject_set(sid, f"{item['key']}: {item['reason']}")
            del set_keys[sid]
    done_sets = set()
    for key in sorted(verified):
        if key in pairs:
            continue
        candidate, source = verified[key]
        sid = set_id_of(candidate)
        if sid is not None:
            if sid in set_keys and sid not in done_sets:
                done_sets.add(sid)
                place_set(sid)
            continue
        if candidate.get("auto_base") and source["licence"] != DERIVABLE_LICENCE:
            rejected.append(reject(candidate, "derive_base_not_cc0", source["licence"]))
        else:
            place(candidate, source)
    for key in pairs:
        candidate, source = verified[key]
        base = None
        for k in ref_keys(candidate["companion_of"]) | {candidate["companion_of"]}:
            base = base or lookup.get(k)
        if base is None:
            rejected.append(reject(candidate, "companion_base_missing", str(candidate["companion_of"])))
        else:
            place(candidate, source, companion=base[0])
    for candidate in sorted((c for c in candidates if c.get("derive")),
                            key=lambda c: (candidate_key(c), json.dumps(c["derive"], sort_keys=True))):
        spec = candidate["derive"]
        found, ref = find_base(candidate)
        if found is None:
            rejected.append(reject(candidate, "derive_base_missing", ref))
        elif found[0]["licence"] != DERIVABLE_LICENCE:
            rejected.append(reject(candidate, "derive_base_not_cc0", found[0]["licence"]))
        elif not str(spec.get("recipe") or "").strip():
            rejected.append(reject(candidate, "derive_recipe_missing"))
        else:
            recipe = normalise_recipe(spec["recipe"])
            try:
                steps = parse_recipe(recipe)
            except RecipeError as error:
                rejected.append(reject(candidate, "recipe_invalid", str(error)))
                continue
            base_entry, base_source = found
            if steps[0][0] == "raw_embedded_jpeg" and base_source["format"].lower() not in RAW_FORMATS:
                rejected.append(reject(candidate, "recipe_invalid", "raw_embedded_jpeg needs a RAW base"))
                continue
            candidate = {**candidate, "derive": {**spec, "recipe": recipe}}
            strip = []
            if steps[0][0] == "raw_embedded_jpeg":
                chosen = choose_companion_raw(base_entry, base_source)
                if chosen is None:
                    rejected.append(reject(candidate, "companion_base_unavailable", base_source["format"]))
                    continue
                base_entry, base_source, strip = chosen
            before = len(approved)
            place(candidate, base_source, derived_from=base_entry,
                  output=recipe_extension(steps, base_source["_ext"]))
            if steps[0][0] == "raw_embedded_jpeg" and len(approved) > before:
                base_entry["scored"] = False
                for case in strip:
                    counts[case] -= 1
                keep = [c for c in base_entry["cases"] if c in companion_cases]
                base_entry["cases"] = keep + [c for c in approved[-1]["cases"]
                                              if c in companion_cases and c not in keep]
    add_datetimes(approved)
    approved.sort(key=lambda e: e["id"])
    short = {}
    for case, spec in cases.items():
        have = counts.get(case, 0) * (2 if case == PAIR_CASE else 1)
        if have < spec.get("min_photos", DEFAULT_MIN_PHOTOS) and any(
            case in candidate_cases(c) for c in candidates
        ):
            short[case] = have
    return approved, rejected, short


def read_jsonl(paths):
    rows = []
    for path in paths:
        for number, line in enumerate(Path(path).read_text(encoding="utf8").splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise SystemExit(f"{path}:{number}: {error}") from error
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidates", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--rejected", required=True)
    parser.add_argument("--max-per-case", type=int, default=DEFAULT_MAX_PHOTOS)
    parser.add_argument("--date", default=None)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    args = parser.parse_args(argv)
    cached = CachedFetch(http_fetch, Path(args.out).with_suffix(".cache.json"))
    try:
        approved, rejected, short = run(
            read_jsonl(args.candidates), load_manifest(args.manifest), cached, args.max_per_case, args.date
        )
    finally:
        cached.save()
    Path(args.out).write_text(json.dumps(approved, indent=2), encoding="utf8")
    Path(args.rejected).write_text(json.dumps(rejected, indent=2), encoding="utf8")
    print(f"approved {len(approved)}, rejected {len(rejected)}")
    for case, have in sorted(short.items()):
        print(f"SHORT {case}: {have} approved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
