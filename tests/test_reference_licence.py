"""Machine licence gate (issue #393): every rule has a failing fixture; no real network."""

import copy
import email.utils
import json
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

TESTDB = Path(__file__).resolve().parent.parent / "testdb"
if str(TESTDB) not in sys.path:
    sys.path.insert(0, str(TESTDB))

import licence_check as lc  # noqa: E402
import reference_common as rc  # noqa: E402

from tests.test_reference_set import CASE, make_photo  # noqa: E402

MANIFEST = rc.load_manifest()
# The shipped set is full; the gate tests need an empty one so the case caps do not interfere.
MANIFEST["photos"], MANIFEST["pairs"] = [], []


def meta(licence, artist="<a href='x'>Jane &amp; Co</a>", **extra):
    values = {"LicenseShortName": licence, "Artist": artist, "UsageTerms": licence}
    values.update(extra)
    return {k: {"value": v} for k, v in values.items()}


class FakeCommons:
    """Serves Commons API pages; ``second`` overrides fields of a title on the second read."""

    def __init__(self, files, second=None):
        self.files, self.second, self.calls = files, second or {}, []

    def __call__(self, url):
        self.calls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        read = query["_read"][0]
        pages = {}
        for index, title in enumerate(query["titles"][0].split("|"), 1):
            spec = self.files.get(title)
            if spec is None:
                pages[str(-index)] = {"title": title, "missing": ""}
                continue
            if read == "2" and title in self.second:
                spec = {**spec, **self.second[title]}
            pages[str(index)] = {
                "title": title,
                "imageinfo": [{"url": "https://upload.example/" + title[5:],
                               "sha1": "0" * 40, "timestamp": "2024-01-01T00:00:00Z",
                               "extmetadata": spec["meta"]}],
                "categories": [{"title": c} for c in spec.get("cats", [])],
            }
        return json.dumps({"query": {"pages": pages}})


def cand(title, case=CASE, **extra):
    return {"case": case, "source": "commons", "title": title, "page_url": "p", "covers_also": [],
            "identifiable_people": False, "child": False, "ai_generated": False, "derive": None,
            "notes": "", **extra}


def run(candidates, files, second=None, fetch=None, **kwargs):
    fetch = fetch or FakeCommons(files, second)
    result = lc.run(candidates, MANIFEST, lc.CachedFetch(fetch), date="2026-11-25", **kwargs)
    return result, fetch


@pytest.mark.parametrize("name,expected", [
    ("CC0", "CC0-1.0"), ("CC0 1.0", "CC0-1.0"), ("Public domain", "PD"), ("PD-USGov-NASA", "PD"),
    ("CC BY 4.0", "CC-BY-4.0"), ("CC BY 2.0", "CC-BY-2.0"), ("CC BY-SA 3.0", "CC-BY-SA-3.0"),
])
def test_licence_mapping_accepted(name, expected):
    assert lc.normalise_licence(name) == (expected, None)


@pytest.mark.parametrize("name,reason", [
    ("CC BY-NC 4.0", "nc_nd"), ("CC BY-ND 2.0", "nc_nd"), ("CC BY-NC-SA 3.0", "nc_nd"),
    ("GFDL", "licence_not_allowed"), ("CC BY 1.0", "licence_not_allowed"),
    ("CC BY 3.0 de", "licence_not_allowed"), ("Copyrighted free use", "licence_not_allowed"),
    ("", "licence_unreadable"),
])
def test_licence_mapping_rejected(name, reason):
    assert lc.normalise_licence(name) == (None, reason)


@pytest.mark.parametrize("name,expected", [
    ("CC0", "CC0-1.0"), ("Public domain", "PD"), ("CC BY 4.0", "CC-BY-4.0"),
])
def test_allowed_licences_are_approved(name, expected):
    (approved, rejected, _), fetch = run([cand("File:A.jpg")], {"File:A.jpg": {"meta": meta(name)}})
    assert rejected == []
    assert approved[0]["licence"] == expected
    assert approved[0]["author"] == "Jane & Co"
    assert approved[0]["approved_by"] == "licence-check"
    assert approved[0]["licence_evidence"]["license_short_name"] == name
    assert approved[0]["licence_evidence"]["second_read_matches"] is True
    assert "via Wikimedia Commons" in approved[0]["attribution"]
    assert len(fetch.calls) == 2  # two independent reads


def test_share_alike_gets_flag_and_change_notice():
    (approved, _, _), _ = run([cand("File:A.jpg")], {"File:A.jpg": {"meta": meta("CC BY-SA 4.0")}})
    assert approved[0]["share_alike_ok"] is True
    assert approved[0]["change_notice"] == "unmodified"


@pytest.mark.parametrize("name", ["CC BY-NC 4.0", "CC BY-ND 4.0", "GFDL", "weird"])
def test_disallowed_licence_rejected(name):
    (approved, rejected, _), _ = run([cand("File:A.jpg")], {"File:A.jpg": {"meta": meta(name)}})
    assert approved == []
    assert rejected[0]["reason"] in ("nc_nd", "licence_not_allowed")


def test_second_read_mismatch():
    files = {"File:A.jpg": {"meta": meta("CC0")}}
    second = {"File:A.jpg": {"meta": meta("CC BY 4.0")}}
    (approved, rejected, _), _ = run([cand("File:A.jpg")], files, second)
    assert approved == [] and rejected[0]["reason"] == "second_read_mismatch"


def test_missing_licence_and_missing_file():
    files = {"File:A.jpg": {"meta": meta("")}}
    (_, rejected, _), _ = run([cand("File:A.jpg"), cand("File:B.jpg")], files)
    assert {r["key"]: r["reason"] for r in rejected} == {
        "File:A.jpg": "licence_unreadable", "File:B.jpg": "not_found"}


def test_author_missing_and_pd_unknown_author():
    files = {"File:A.jpg": {"meta": meta("CC BY 4.0", artist="")},
             "File:B.jpg": {"meta": meta("Public domain", artist="Unknown author")}}
    (approved, rejected, _), _ = run([cand("File:A.jpg"), cand("File:B.jpg")], files)
    assert [r["reason"] for r in rejected] == ["author_missing"]
    assert approved[0]["author"] == "Unknown author"


def test_credit_is_used_when_artist_absent():
    m = meta("CC0", artist="")
    m["Credit"] = {"value": "<b>Own work</b>"}
    (approved, _, _), _ = run([cand("File:A.jpg")], {"File:A.jpg": {"meta": m}})
    assert approved[0]["author"] == "Own work"


def test_child_rejected_by_flag_and_by_category():
    files = {"File:A.jpg": {"meta": meta("CC0")},
             "File:B.jpg": {"meta": meta("CC0"), "cats": ["Category:Children playing"]},
             "File:C.jpg": {"meta": meta("CC0"), "cats": ["Category:Children playing"]}}
    candidates = [cand("File:A.jpg", child=True), cand("File:B.jpg", identifiable_people=True),
                  cand("File:C.jpg")]
    (approved, rejected, _), _ = run(candidates, files)
    assert sorted(r["key"] for r in rejected) == ["File:A.jpg", "File:B.jpg"]
    assert {r["reason"] for r in rejected} == {"child"}
    assert [e["source_page"].endswith("File:C.jpg") for e in approved] == [True]


def test_ai_generated_rejected():
    files = {"File:A.jpg": {"meta": meta("CC0"), "cats": ["Category:AI-generated images"]}}
    (approved, rejected, _), _ = run([cand("File:A.jpg")], files)
    assert approved == [] and rejected[0]["reason"] == "ai_generated"


def test_dedupe_unions_cases_and_reads_once():
    files = {"File:A.jpg": {"meta": meta("CC0")}}
    candidates = [cand("File:A.jpg", "landscape", covers_also=["macro"]),
                  cand("File:A.jpg", "food", covers_also=["landscape"])]
    (approved, _, _), fetch = run(candidates, files)
    assert len(approved) == 1
    assert approved[0]["cases"] == ["landscape", "macro", "food"]
    assert len(fetch.calls) == 2


def test_case_full_and_case_unknown():
    files = {f"File:{n}.jpg": {"meta": meta("CC0")} for n in "ABCD"}
    candidates = [cand(f"File:{n}.jpg") for n in "ABC"] + [cand("File:D.jpg", "nonsense")]
    (approved, rejected, _), _ = run(candidates, files, max_per_case=2)
    assert len(approved) == 2
    assert sorted(r["reason"] for r in rejected) == ["case_full", "case_unknown"]


def test_short_cases_are_reported():
    files = {"File:A.jpg": {"meta": meta("CC0")}}
    (_, _, short), _ = run([cand("File:A.jpg")], files)
    assert short == {CASE: 1}


def test_id_path_and_format_generation():
    titles = ["File:A.HIF", "File:B.hif", "File:C.JPEG"]
    (approved, _, _), _ = run([cand(t) for t in titles], {t: {"meta": meta("CC0")} for t in titles})
    by_title = {e["source_page"].rsplit("/", 1)[1]: e for e in approved}
    assert [e["id"] for e in approved] == ["landscape-01", "landscape-02", "landscape-03"]
    assert by_title["File:A.HIF"]["format"] == "HIF" and by_title["File:A.HIF"]["path"].endswith(".HIF")
    assert by_title["File:B.hif"]["format"] == "hif" and by_title["File:B.hif"]["path"].endswith(".hif")
    assert by_title["File:C.JPEG"]["format"] == "jpeg" and by_title["File:C.JPEG"]["path"].endswith(".jpg")
    group = MANIFEST["cases"][CASE]["group"]
    assert by_title["File:A.HIF"]["path"].startswith(f"{group}/landscape-0")


def derive_candidate(base, **spec):
    return {"case": "macro", "source": "commons", "title": None, "page_url": "derived-one",
            "derive": {"from_case_candidate": base, "recipe": "resize:50", **spec}, "notes": ""}


@pytest.mark.parametrize("licence,ok", [("CC0", True), ("CC BY 4.0", False), ("Public domain", False)])
def test_derived_needs_cc0_base(licence, ok):
    files = {"File:A.jpg": {"meta": meta(licence)}}
    (approved, rejected, _), _ = run([cand("File:A.jpg"), derive_candidate("File:A.jpg")], files)
    derived = [e for e in approved if e["kind"] == "derived"]
    if ok:
        assert derived[0]["derived_from"] == "landscape-01"
        assert derived[0]["path"].startswith("derived/") and derived[0]["recipe"].startswith("resize:50")
        assert derived[0]["id"] == "macro-01"
    else:
        assert derived == [] and rejected[0]["reason"] == "derive_base_not_cc0"


def test_derived_base_missing():
    (_, rejected, _), _ = run([derive_candidate("File:Nope.jpg")], {})
    assert [r["reason"] for r in rejected] == ["not_found", "derive_base_missing"]


def test_approved_entry_validates_once_completed():
    files = {f"File:{n}.jpg": {"meta": meta("CC0" if n != "C" else "CC BY-SA 4.0")} for n in "ABC"}
    (approved, _, _), _ = run([cand(f"File:{n}.jpg") for n in "ABC"], files)
    manifest = copy.deepcopy(MANIFEST)
    manifest["cases"][CASE]["known_gap"] = None
    photos = []
    for index, entry in enumerate(approved, 1):
        base = make_photo(index)
        base.update(entry)
        base.update(sha256=f"{index:064x}", bytes=10 + index, expected_category=None,
                    acceptable_categories=[], labeller=None, reviewed=False)
        photos.append(base)
    manifest["photos"] = photos
    errors = [e for e in rc.validate(manifest) if "photo " in e]
    assert errors == []


class Pages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise OSError("404")
        return self.pages[url]


def pixls_row(row_id, name, href, sha="a" * 64, make="Canon", model="EOS 7D", mp=17.92):
    return [make, model, "mode", mp, "", f"<a href='{href}' class='cc'>co</a>", "2016-12-29",
            f"<a href='https://raw.pixls.us/getfile.php/{row_id}/nice/{name}'>{name}</a>"
            f"<div><span title='sha256 Checksum'>{sha}</span>&nbsp;(1MB)</div>", "<a>exif</a>"]


CC0_HREF = "https://creativecommons.org/publicdomain/zero/1.0/"
NCSA_HREF = "http://creativecommons.org/licenses/by-nc-sa/4.0/"
FEED = json.dumps({"data": [
    pixls_row(1, "Canon - EOS 7D - a.CR2", CC0_HREF, "1" * 64),
    pixls_row(2, "Canon - EOS 7D - b.CR2", NCSA_HREF, "2" * 64),
    pixls_row(3, "Canon - EOS 7D - c.CR3", CC0_HREF, "3" * 64),
]})


def pixls_cand(**extra):
    return {"case": CASE, "source": "rawpixls", "title": None, "page_url": "https://raw.pixls.us/",
            "covers_also": [], "derive": None, "notes": "", **extra}


def page_cand(source, page, direct="https://h.example/x.CR3", **extra):
    return {"case": CASE, "source": source, "title": None, "page_url": page, "direct_url": direct,
            "covers_also": [], "derive": None, "notes": "", **extra}


def test_rawpixls_cc0_row_accepted_with_sha256_and_megapixels():
    fetch = Pages({lc.PIXLS_FEED: FEED})
    direct = "https://raw.pixls.us/getfile.php/1/nice/Canon - EOS 7D - a.CR2"
    verified, rejected = lc.verify_all([pixls_cand(direct_url=direct)], lc.CachedFetch(fetch))
    entry = verified[direct][1]
    assert not rejected and entry["licence"] == "CC0-1.0" and entry["format"] == "cr2"
    assert entry["sha256"] == "1" * 64 and entry["megapixels"] == 17.92
    assert entry["licence_evidence"]["expected_sha256"] == "1" * 64


def test_rawpixls_ncsa_row_rejected_and_feed_read_once():
    fetch = Pages({lc.PIXLS_FEED: FEED})
    cands = [pixls_cand(direct_url=f"https://raw.pixls.us/getfile.php/{i}/nice/x.CR2") for i in (2, 3)]
    verified, rejected = lc.verify_all(cands, lc.CachedFetch(fetch))
    assert [r["reason"] for r in rejected] == ["nc_nd"]
    assert len(verified) == 1 and fetch.calls == [lc.PIXLS_FEED]


def test_rawpixls_page_text_no_longer_decides():
    # a page that says CC0 anywhere must not rescue a row that is not CC0
    direct = "https://raw.pixls.us/getfile.php/2/nice/Canon - EOS 7D - b.CR2"
    pages = Pages({lc.PIXLS_FEED: FEED, "https://raw.pixls.us/": "<p>CC0</p>"})
    _, rejected = lc.verify_all([pixls_cand(direct_url=direct)], lc.CachedFetch(pages))
    assert rejected[0]["reason"] == "nc_nd"


def test_rawpixls_matched_by_make_model_filename_without_direct_url():
    page = "https://raw.pixls.us/data/Canon/EOS%207D/Canon - EOS 7D - c.CR3"
    feed = lc.CachedFetch(Pages({lc.PIXLS_FEED: FEED}))
    verified, rejected = lc.verify_all([pixls_cand(page_url=page)], feed)
    assert not rejected and next(iter(verified.values()))[1]["sha256"] == "3" * 64
    _, rejected = lc.verify_all([pixls_cand(page_url="https://raw.pixls.us/data/Canon/EOS%207D/")], feed)
    assert rejected[0]["reason"] == "not_found"


def test_rawpixls_feed_unreachable_is_api_error():
    direct = "https://raw.pixls.us/getfile.php/1/nice/x.CR2"
    _, rejected = lc.verify_all([pixls_cand(direct_url=direct)], lc.CachedFetch(Pages({})))
    assert rejected[0]["reason"] == "api_error"


def test_pixls_sha256_reaches_approved_entry():
    direct = "https://raw.pixls.us/getfile.php/1/nice/Canon - EOS 7D - a.CR2"
    (approved, _, _), _ = run([pixls_cand(direct_url=direct)], {}, fetch=Pages({lc.PIXLS_FEED: FEED}))
    assert approved[0]["sha256"] == "1" * 64 and approved[0]["path"] == "raw/landscape-01.cr2"
    assert approved[0]["url"].startswith("https://raw.pixls.us/getfile.php/1/nice/Canon%20-%20EOS")


@pytest.mark.parametrize("source", ["other", "nonsense"])
def test_other_sources_are_unsupported(source):
    nasa = "https://images.nasa.gov/details/x"
    cands = [page_cand(source, nasa, "https://h.example/x.jpg")]
    _, rejected = lc.verify_all(cands, lc.CachedFetch(Pages({})))
    assert rejected[0]["reason"] == "source_unsupported"


@pytest.mark.parametrize("category", [
    "Category:Copyright violations", "Category:Deletion requests May 2024", "Category:Permission pending",
    "Category:Permission received", "Category:OTRS pending", "Category:No permission since 2020",
    "Category:No source since 2020", "Category:No license since 2020", "Category:Non-free Wikipedia images",
    "Category:Speedy deletion candidates", "Category:Possibly unfree files", "Category:Unfree Flickr",
    "Category:Files with no machine-readable author", "Category:Files with no machine-readable license",
    "Category:Files with no machine-readable source", "category:copyright violations",
])
def test_problem_category_rejected(category):
    files = {"File:A.jpg": {"meta": meta("CC0"), "cats": ["Category:Landscapes", category]}}
    (approved, rejected, _), _ = run([cand("File:A.jpg")], files)
    assert approved == [] and rejected[0]["reason"] == "copyright_problem"


def test_problem_category_on_continuation_page_is_seen():
    class Paged(FakeCommons):
        def __call__(self, url):
            body = json.loads(super().__call__(url))
            if "clcontinue" not in url:
                body["continue"] = {"clcontinue": "A|1", "continue": "||"}
                body["query"]["pages"]["1"]["categories"] = [{"title": "Category:Fine"}]
            else:
                body["query"]["pages"]["1"].pop("imageinfo")
                body["query"]["pages"]["1"]["categories"] = [{"title": "Category:Copyright violations"}]
            return json.dumps(body)
    fetch = Paged({"File:A.jpg": {"meta": meta("CC0")}})
    approved, rejected, _ = lc.run([cand("File:A.jpg")], MANIFEST, lc.CachedFetch(fetch), date="2026-11-25")
    assert approved == [] and rejected[0]["reason"] == "copyright_problem"


def test_personality_restriction_is_kept_and_flagged():
    files = {"File:A.jpg": {"meta": meta("CC0", Restrictions="personality")}}
    (approved, rejected, _), _ = run([cand("File:A.jpg", notes="x")], files)
    assert rejected == [] and "personality" in approved[0]["notes"] and approved[0]["notes"].startswith("x ")
    (approved, _, _), _ = run([cand("File:A.jpg", public_figure=True)], files)
    assert "personality" not in approved[0]["notes"]


def test_ids_and_caps_continue_from_manifest():
    manifest = copy.deepcopy(MANIFEST)
    manifest["photos"] = [
        {"id": "landscape-07", "cases": [CASE], "url": "https://upload.example/Taken.jpg"},
        {"id": "landscape-02", "cases": [CASE], "url": "https://upload.example/Other.jpg"},
    ]
    titles = ["File:A.jpg", "File:B.jpg", "File:C.jpg", "File:Taken.jpg"]
    fetch = FakeCommons({t: {"meta": meta("CC0")} for t in titles})
    approved, rejected, _ = lc.run([cand(t) for t in titles], manifest, lc.CachedFetch(fetch),
                                   max_per_case=4, date="2026-11-25")
    assert [e["id"] for e in approved] == ["landscape-08", "landscape-09"]
    assert {r["key"]: r["reason"] for r in rejected} == {
        "File:C.jpg": "case_full", "File:Taken.jpg": "already_present"}


class Response:
    def __init__(self, body, headers=None):
        self.body, self.headers = body.encode(), headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def serve(monkeypatch, replies):
    calls, sleeps = [], []
    queue = iter(replies)

    def fake_open(request, timeout=0):
        calls.append(request.full_url)
        return next(queue)
    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(lc.time, "sleep", sleeps.append)
    return calls, sleeps


MAXLAG = json.dumps({"error": {"code": "maxlag", "info": "waiting"}})


def http_date(seconds):
    return email.utils.formatdate(time.time() + seconds, usegmt=True)


def test_maxlag_is_retried_with_retry_after_then_succeeds(monkeypatch):
    calls, sleeps = serve(monkeypatch, [
        Response(MAXLAG, {"Retry-After": "3"}), Response(MAXLAG, {"mediawiki-api-error": "maxlag"}),
        Response('{"query": {}}')])
    assert lc.http_fetch(lc.COMMONS_API + "?a=1") == '{"query": {}}'
    assert len(calls) == 3 and sleeps[0] == 3.0


def test_retry_after_http_date_and_cap():
    assert lc.retry_delay("999", 2) == 60.0
    assert lc.retry_delay("garbage", 2) == 2
    assert 20 < lc.retry_delay(http_date(30), 2) <= 30
    assert lc.retry_delay(http_date(-100), 2) == 0.0


def test_persistent_maxlag_raises_and_becomes_api_error_never_not_found(monkeypatch, tmp_path):
    serve(monkeypatch, [Response(MAXLAG)] * 20)
    with pytest.raises(lc.ApiError):
        lc.http_fetch(lc.COMMONS_API + "?a=1", retries=3)
    cache = tmp_path / "c.json"
    fetched = lc.CachedFetch(lambda url: lc.http_fetch(url, retries=2), cache)
    approved, rejected, _ = lc.run([cand("File:A.jpg")], MANIFEST, fetched, date="2026-11-25")
    fetched.save()
    assert approved == [] and rejected[0]["reason"] == "api_error"
    assert not cache.exists() or json.loads(cache.read_text()) == {}


def test_cached_fetch_never_stores_an_error_body(tmp_path):
    cached = lc.CachedFetch(lambda url: MAXLAG, tmp_path / "c.json")
    with pytest.raises(lc.ApiError):
        cached(lc.COMMONS_API + "?x=1")
    assert cached.data == {}


def test_url_query_and_fragment_dropped_and_revision_pinned():
    class Rev(FakeCommons):
        def __call__(self, url):
            body = json.loads(super().__call__(url))
            info = body["query"]["pages"]["1"]["imageinfo"][0]
            info.update(url="https://upload.example/A.jpg?utm_source=x&b=2#frag", sha1="f" * 40,
                        timestamp="2024-01-02T03:04:05Z")
            return json.dumps(body)
    fetch = Rev({"File:A.jpg": {"meta": meta("CC0", AttributionRequired="false")}})
    approved, _, _ = lc.run([cand("File:A.jpg")], MANIFEST, lc.CachedFetch(fetch), date="2026-11-25")
    assert approved[0]["url"] == "https://upload.example/A.jpg"
    evidence = approved[0]["licence_evidence"]
    assert evidence["sha1"] == "f" * 40 and evidence["timestamp"] == "2024-01-02T03:04:05Z"
    assert evidence["attribution_required"] == "false"
    assert "sha1|timestamp" in urllib.parse.unquote(fetch.calls[0].replace("+", " ")) or "sha1" in fetch.calls[0]


def test_strip_html_collapses_hidden_duplicates():
    nested = ('<div class="fn value">\nUnknown author<span style="display: none;">Unknown author</span>'
              " or not provided</div>")
    assert lc.strip_html(nested) == "Unknown author or not provided"
    assert lc.strip_html("<b>Unknown author</b><i>Unknown author</i>") == "Unknown author"
    assert lc.strip_html("<a>Jane   &amp;\n Co</a>") == "Jane & Co"


def test_long_author_is_capped_but_attribution_keeps_full_text():
    full = " ".join(f"Name{i}" for i in range(60))
    (approved, _, _), _ = run([cand("File:A.jpg")], {"File:A.jpg": {"meta": meta("CC0", artist=full)}})
    assert len(approved[0]["author"]) == 200
    assert full.strip() in approved[0]["attribution"]


def test_layout_raw_sequence_and_plain():
    titles = ["File:A.CR3", "File:B.jpg", "File:C.jpg"]
    files = {t: {"meta": meta("CC0")} for t in titles}
    seq = {"set_id": "pano 1", "expected_kind": "panorama"}
    cands = [cand("File:A.CR3"), cand("File:B.jpg", megapixels=12.5), cand("File:C.jpg", sequence=seq)]
    (approved, _, _), _ = run(cands, files)
    paths = {e["source_page"].rsplit("/", 1)[1]: e for e in approved}
    assert paths["File:A.CR3"]["path"] == "raw/landscape-01.cr3"
    group = MANIFEST["cases"][CASE]["group"]
    assert paths["File:B.jpg"]["path"] == f"{group}/landscape-02.jpg"
    assert paths["File:B.jpg"]["megapixels"] == 12.5
    assert paths["File:C.jpg"]["path"] == "sequences/pano_1/landscape-03.jpg"
    assert paths["File:C.jpg"]["sequence"] == seq


def test_companion_pair_shares_stem_and_validates():
    files = {"File:A.jpg": {"meta": meta("CC0")}, "File:A.CR3": {"meta": meta("CC0")}}
    cands = [cand("File:A.jpg"), cand("File:A.CR3", companion_of="File:A.jpg")]
    (approved, _, _), _ = run(cands, files)
    jpeg, raw = approved
    assert jpeg["path"] == "companions/landscape-01.jpg" and "companion_of" not in jpeg
    assert raw["path"] == "companions/landscape-01.cr3" and raw["id"] == "landscape-02"
    assert raw["companion_of"] == "landscape-01" and raw["scored"] is False
    manifest = copy.deepcopy(MANIFEST)
    manifest["cases"][CASE]["known_gap"] = None
    photos = []
    for index, entry in enumerate(approved, 1):
        base = make_photo(index)
        base.update(entry)
        base.update(sha256=f"{index:064x}", bytes=10 + index, expected_category=None,
                    acceptable_categories=[], labeller=None, reviewed=False)
        photos.append(base)
    manifest["photos"] = photos
    assert [e for e in rc.validate(manifest) if "companion" in e] == []


def test_companion_base_missing():
    files = {"File:A.CR3": {"meta": meta("CC0")}}
    (_, rejected, _), _ = run([cand("File:A.CR3", companion_of="File:Nope.jpg")], files)
    assert rejected[0]["reason"] == "companion_base_missing"


def test_manifest_option_is_read(tmp_path, monkeypatch):
    manifest = copy.deepcopy(MANIFEST)
    manifest["photos"] = [{"id": "landscape-04", "cases": [CASE], "url": "u"}]
    path = tmp_path / "m.json"
    path.write_text(json.dumps(manifest), encoding="utf8")
    monkeypatch.setattr(lc, "http_fetch", FakeCommons({"File:A.jpg": {"meta": meta("CC0")}}))
    source = tmp_path / "c.jsonl"
    source.write_text(json.dumps(cand("File:A.jpg")) + "\n", encoding="utf8")
    out, rej = tmp_path / "ok.json", tmp_path / "rej.json"
    args = [str(source), "--out", str(out), "--rejected", str(rej), "--manifest", str(path),
            "--date", "2026-11-25"]
    lc.main(args)
    assert json.loads(out.read_text())[0]["id"] == "landscape-05"


def test_cache_makes_rerun_free(tmp_path):
    files = {"File:A.jpg": {"meta": meta("CC0")}}
    path = tmp_path / "c.json"
    first = lc.CachedFetch(FakeCommons(files), path)
    lc.run([cand("File:A.jpg")], MANIFEST, first, date="2026-11-25")
    first.save()
    again = FakeCommons(files)
    lc.run([cand("File:A.jpg")], MANIFEST, lc.CachedFetch(again, path), date="2026-11-25")
    assert again.calls == []


def test_cli_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "http_fetch", FakeCommons({"File:A.jpg": {"meta": meta("CC0")}}))
    source = tmp_path / "c.jsonl"
    source.write_text(json.dumps(cand("File:A.jpg")) + "\n", encoding="utf8")
    out, rej = tmp_path / "ok.json", tmp_path / "rej.json"
    path = tmp_path / "m.json"  # an empty manifest: the shipped one is full, so ids would not start at 01
    path.write_text(json.dumps(MANIFEST), encoding="utf8")
    args = [str(source), "--out", str(out), "--rejected", str(rej), "--manifest", str(path), "--date", "2026-11-25"]
    assert lc.main(args) == 0
    assert json.loads(out.read_text())[0]["id"] == "landscape-01"
    assert json.loads(rej.read_text()) == []


# --- raw.pixls.us /data/ paths through filelist.sha256 ------------------------------------

DATA = "https://raw.pixls.us/data/Canon/Canon%20EOS%207D/"
FILELIST = (f"{'1' * 64} *Canon/Canon EOS 7D/IMG_0001.CR2\n{'2' * 64} *Canon/Canon EOS 7D/IMG_0002.CR2\n"
            f"{'3' * 64} *Canon/Canon EOS 7D/IMG_[3].CR2\n")


def data_pages():
    return Pages({lc.PIXLS_FEED: FEED, lc.PIXLS_FILELIST: FILELIST})


def test_filelist_maps_data_path_to_feed_row_and_keeps_data_url():
    cands = [pixls_cand(direct_url=DATA + "IMG_0001.CR2"), pixls_cand(direct_url=DATA + "IMG_%255b3%255d.CR2")]
    (approved, rejected, _), _ = run(cands, {}, fetch=data_pages())
    assert rejected == []
    by_sha = {e["sha256"]: e for e in approved}
    assert by_sha["1" * 64]["url"] == DATA + "IMG_0001.CR2"
    assert by_sha["3" * 64]["url"] == DATA + "IMG_%5B3%5D.CR2"


def test_filelist_row_still_needs_cc0_and_unknown_path_is_not_found():
    cands = [pixls_cand(direct_url=DATA + "IMG_0002.CR2"), pixls_cand(direct_url=DATA + "IMG_9.CR2")]
    _, rejected = lc.verify_all(cands, lc.CachedFetch(data_pages()))
    assert sorted(r["reason"] for r in rejected) == ["nc_nd", "not_found"]


def test_filelist_is_fetched_once_and_only_when_needed():
    pages = data_pages()
    cands = [pixls_cand(direct_url=DATA + f"IMG_000{i}.CR2") for i in (1, 2)]
    lc.verify_all(cands, lc.CachedFetch(pages))
    assert pages.calls.count(lc.PIXLS_FILELIST) == 1


# --- derivations ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,canonical", [
    ("grayscale", "to_grayscale"), ("sepia", "to_sepia"),
    ("crop:center_square", "crop_aspect:1x1"), ("crop:21x9", "crop_aspect:21x9"),
    ("resize:max_edge=640", "resize:640"), ("reencode_jpeg:q70", "reencode_jpeg:70"),
    ("resize:max_edge=1600+reencode_jpeg:q85", "resize:1600;reencode_jpeg:85"),
    ("to_grayscale+reencode_jpeg:q70", "to_grayscale;reencode_jpeg:70"),
    ("to_16bit_tiff (new recipe; JPEG source is 8-bit)", "to_16bit:tiff"),
    ("write_xmp_sidecar(rating=4)", "write_xmp_sidecar:rating=4"),
    ("encode_heic (pillow-heif; not in closed recipe set)", "encode_heic:90"),
    ("encode_heic:80", "encode_heic:80"),
    ("render_jpeg_from_raw (not in closed set; extract embedded preview via exiftool/rawpy)", "raw_embedded_jpeg"),
    ("strip_icc (not in closed recipe set; use strip_exif variant)", "strip_icc"),
    ("strip_exif", "strip_exif"), ("set_exif_orientation:6", "set_exif_orientation:6"),
])
def test_recipe_normalisation(raw, canonical):
    assert lc.normalise_recipe(raw) == canonical
    lc.parse_recipe(canonical)


def derived_of(recipe, base="File:A.jpg", case="macro", **extra):
    return {"case": case, "source": "commons", "title": None, "page_url": "d", "covers_also": [],
            "derive": {"from_title": base, "recipe": recipe}, "notes": "", **extra}


A_FILES = {"File:A.jpg": {"meta": meta("CC0")}}


def test_invalid_recipe_is_rejected_with_parser_message():
    (approved, rejected, _), _ = run([cand("File:A.jpg"), derived_of("warp:9")], A_FILES)
    assert [e["kind"] for e in approved] == ["download"]
    assert rejected[0]["reason"] == "recipe_invalid" and "warp" in rejected[0]["detail"]


def test_missing_base_is_added_as_cc0_base_without_cases():
    files = {"File:B.jpg": {"meta": meta("CC0")}}
    (approved, rejected, _), _ = run([derived_of("sepia", base="File:B.jpg")], files)
    base, derived = sorted(approved, key=lambda e: e["kind"] != "download")
    assert rejected == [] and base["cases"] == [] and base["path"].startswith("bases/")
    assert derived["derived_from"] == base["id"] and derived["path"].startswith("derived/")
    assert derived["recipe"].startswith("to_sepia;set_exif_datetime:")


def test_auto_added_base_must_be_cc0():
    files = {"File:B.jpg": {"meta": meta("CC BY 4.0")}}
    (approved, rejected, _), _ = run([derived_of("sepia", base="File:B.jpg")], files)
    assert approved == []
    assert [r["reason"] for r in rejected] == ["derive_base_not_cc0", "derive_base_missing"]


def test_same_base_with_different_recipes_stays_separate():
    cands = [cand("File:A.jpg"), derived_of("sepia"), derived_of("grayscale"), derived_of("sepia")]
    (approved, _, _), _ = run(cands, A_FILES)
    derived = [e for e in approved if e["kind"] == "derived"]
    assert len(derived) == 2 and len({e["path"] for e in derived}) == 2


@pytest.mark.parametrize("recipe,suffix,fmt", [
    ("encode_heic", ".heic", "heic"), ("to_16bit_tiff", ".tif", "tiff"),
    ("to_16bit:png", ".png", "png"), ("reencode_jpeg:8", ".jpg", "jpeg"),
])
def test_derived_extension_follows_recipe(recipe, suffix, fmt):
    (approved, _, _), _ = run([cand("File:A.jpg"), derived_of(recipe)], A_FILES)
    derived = [e for e in approved if e["kind"] == "derived"][0]
    group = MANIFEST["cases"]["macro"]["group"]
    assert derived["path"] == f"derived/{group}/{derived['id']}{suffix}" and derived["format"] == fmt


def test_datetimes_are_distinct_per_variant_and_skipped_for_heic():
    cands = [cand("File:A.jpg"), derived_of("sepia"), derived_of("grayscale"),
             derived_of("to_16bit_tiff"), derived_of("encode_heic"),
             derived_of("strip_exif;set_exif_datetime:2020:05:05 05:05:05")]
    (approved, _, _), _ = run(cands, A_FILES)
    recipes = {e["recipe"] for e in approved if e["kind"] == "derived"}
    stamps = {r.split("set_exif_datetime:")[1][:19] for r in recipes if "2001:01:01" in r}
    assert len(stamps) == 3 and all(s.startswith("2001:01:01 0") for s in stamps)
    assert "encode_heic:90" in recipes
    assert "strip_exif;set_exif_datetime:2020:05:05 05:05:05" in recipes
    assert any(r.endswith(";to_16bit:tiff") and "set_exif_datetime" in r for r in recipes)
    for recipe in recipes:
        lc.parse_recipe(recipe)


def test_xmp_sidecar_sits_beside_its_base_as_companion():
    (approved, _, _), _ = run([cand("File:A.jpg"), derived_of("write_xmp_sidecar(rating=4)")], A_FILES)
    base = next(e for e in approved if e["kind"] == "download")
    xmp = next(e for e in approved if e["kind"] == "derived")
    assert xmp["path"] == base["path"].rsplit(".", 1)[0] + ".xmp"
    assert xmp["companion_of"] == xmp["derived_from"] == base["id"] and xmp["format"] == "xmp"
    assert xmp["recipe"] == "write_xmp_sidecar:rating=4"


def raw_pair_run(cases_of, max_per_case=5, derive_case="comp-raw-jpeg"):
    """Two CC0 CR2s (IMG_0001, IMG_0002) proposed for ``cases_of``; the JPEG derives from IMG_0001."""
    feed = json.dumps({"data": [
        pixls_row(1, "Canon - EOS 7D - a.CR2", CC0_HREF, "1" * 64),
        pixls_row(2, "Canon - EOS 7D - b.CR2", CC0_HREF, "2" * 64),
    ]})
    pages = Pages({lc.PIXLS_FEED: feed, lc.PIXLS_FILELIST: FILELIST})
    cands = [pixls_cand(direct_url=DATA + f"IMG_000{n}.CR2", case=case)
             for n, case in zip((1, 2), cases_of)]
    derived = {**pixls_cand(direct_url=DATA + "IMG_0001.CR2"), "case": derive_case,
               "derive": {"from_title": "IMG_0001.CR2", "recipe": "render_jpeg_from_raw (extract embedded)"}}
    (approved, rejected, short), _ = run(cands + [derived], {}, fetch=pages, max_per_case=max_per_case)
    return approved, rejected


def test_raw_embedded_jpeg_pairs_with_its_raw_in_companions():
    direct = DATA + "IMG_0001.CR2"
    derived = {**pixls_cand(direct_url=direct), "case": "macro",
               "derive": {"from_title": "IMG_0001.CR2", "recipe": "render_jpeg_from_raw (extract embedded)"}}
    (approved, rejected, _), _ = run([pixls_cand(direct_url=direct, case="comp-raw-jpeg"), derived],
                                     {}, fetch=data_pages())
    assert rejected == []
    raw = next(e for e in approved if e["kind"] == "download")
    jpeg = next(e for e in approved if e["kind"] == "derived")
    assert raw["scored"] is False and raw["companion_of"] == jpeg["id"] and raw["cases"] == ["comp-raw-jpeg"]
    stem = jpeg["path"].rsplit(".", 1)[0]
    assert stem.startswith("companions/") and jpeg["path"].endswith(".jpg") and raw["path"] == stem + ".cr2"
    assert jpeg["recipe"] == "raw_embedded_jpeg" and "sha256" not in jpeg and jpeg["format"] == "jpeg"


def test_companion_raw_needed_by_its_case_is_unavailable():
    approved, rejected = raw_pair_run(["raw-cr2", "raw-cr2"])
    assert [r["reason"] for r in rejected] == ["companion_base_unavailable"]
    assert not any(e.get("scored") is False for e in approved)
    assert all(e["cases"] == ["raw-cr2"] for e in approved)


def test_companion_raw_prefers_a_case_full_sample():
    approved, rejected = raw_pair_run(["raw-cr2", "raw-cr2"], max_per_case=1)
    assert rejected == []
    raw = next(e for e in approved if e.get("scored") is False)
    kept = next(e for e in approved if e["kind"] == "download" and e is not raw)
    assert raw["sha256"] == "2" * 64 and raw["cases"] == ["comp-raw-jpeg"]
    assert kept["sha256"] == "1" * 64 and kept["cases"] == ["raw-cr2"] and "scored" not in kept


def test_companion_raw_strips_non_companion_cases_when_surplus(monkeypatch):
    manifest = copy.deepcopy(MANIFEST)
    manifest["cases"]["raw-cr2"]["min_photos"] = 1
    monkeypatch.setitem(globals(), "MANIFEST", manifest)
    approved, rejected = raw_pair_run(["raw-cr2", "raw-cr2"])
    assert rejected == []
    raw = next(e for e in approved if e.get("scored") is False)
    other = next(e for e in approved if e["kind"] == "download" and e is not raw)
    assert raw["cases"] == ["comp-raw-jpeg"] and other["cases"] == ["raw-cr2"]


def test_raw_embedded_jpeg_needs_raw_base():
    (_, rejected, _), _ = run([cand("File:A.jpg"), derived_of("raw_embedded_jpeg")], A_FILES)
    assert rejected[0]["reason"] == "recipe_invalid"


SEQ = "seq-panorama-ge8"


def seq_cand(title, set_id, case=SEQ, **extra):
    return cand(title, case, sequence={"set_id": set_id, "role": title, "expected_kind": "panorama"},
                **extra)


def seq_files(names):
    return {f"File:{n}.jpg": {"meta": meta("CC0")} for n in names}


def test_sequence_set_kept_whole_beyond_the_frame_cap():
    names = [f"S{i}" for i in range(12)]
    candidates = [seq_cand(f"File:{n}.jpg", "pano") for n in names]
    (approved, rejected, _), _ = run(candidates, seq_files(names), max_per_case=5)
    assert len(approved) == 12 and rejected == []
    assert {e["sequence"]["set_id"] for e in approved} == {"pano"}


def test_one_bad_frame_rejects_the_whole_set():
    names = [f"S{i}" for i in range(4)]
    files = seq_files(names)
    files["File:S2.jpg"] = {"meta": meta("CC BY-NC 4.0")}
    candidates = [seq_cand(f"File:{n}.jpg", "pano") for n in names] + [cand("File:Z.jpg")]
    files["File:Z.jpg"] = {"meta": meta("CC0")}
    (approved, rejected, _), _ = run(candidates, files)
    assert [e["cases"] for e in approved] == [[CASE]]
    reasons = [r["reason"] for r in rejected]
    assert reasons.count("set_member_rejected") == 3
    assert all("S2" in r["detail"] for r in rejected if r["reason"] == "set_member_rejected")


def test_sequence_cap_counts_sets_not_frames():
    names = [f"{s}{i}" for s in "ABC" for i in range(3)]
    candidates = [seq_cand(f"File:{n}.jpg", n[0]) for n in names]
    (approved, rejected, _), _ = run(candidates, seq_files(names), max_per_case=2)
    assert sorted({e["sequence"]["set_id"] for e in approved}) == ["A", "B"]
    assert len(approved) == 6
    assert [r["reason"] for r in rejected] == ["set_member_rejected"] * 3
    assert "case_full" in rejected[0]["detail"]


def test_comp_raw_jpeg_counts_pairs_for_the_cap_and_reports_photos():
    direct = DATA + "IMG_0001.CR2"
    derived = {**pixls_cand(direct_url=direct), "case": "macro",
               "derive": {"from_title": "IMG_0001.CR2", "recipe": "render_jpeg_from_raw (extract embedded)"}}
    (approved, _, short), _ = run([pixls_cand(direct_url=direct, case="comp-raw-jpeg"), derived], {},
                                  fetch=data_pages(), max_per_case=5)
    assert sorted(e["kind"] for e in approved) == ["derived", "download"]
    assert short["comp-raw-jpeg"] == 2  # one pair is two photos against min_photos
