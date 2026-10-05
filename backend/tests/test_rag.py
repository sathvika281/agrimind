"""Local knowledge base: manifest metadata, ingestion, de-duplication, BM25 + crop/topic filtering, citation,
empty/inaccessible/malformed/irrelevant sources, retrieval failure, source validation, and that no source is ever
fabricated. Network is never used: pages come from a fake fetch (synthetic test pages, not shipped data)."""
import json

import pytest

from app.services.agents import knowledge
from app.services.graph.state import CropAnalysis
from app.services.rag import discovery, ingestion, retrieval
from app.services.rag.ingestion import IngestError
from app.services.rag.models import SourceEntry

AGRI = ("Tomato early blight is a fungal disease. Symptoms appear on the lower leaves as brown spots with concentric rings. "
        "The disease spreads in warm humid weather and affects the plant yield. Infected leaves turn yellow and drop. "
        "Scout the crop regularly and note how many plants show the symptoms. A soil and nutrient deficiency can look similar, "
        "so check several plants. Pests such as insects cause holes instead of spots. Bacterial leaf spot also causes lesions. ")
RICE = ("Rice blast is a fungal disease of the rice crop. Symptoms are diamond shaped spots on the leaf with grey centres. "
        "Nitrogen excess and humid weather favour the disease. Check the seedling nursery and the plant leaves for lesions. "
        "Brown plant hopper is a pest that causes hopper burn in rice fields and reduces the yield of the crop plants. ") * 2
HTML = "<html><head><title>{t}</title></head><body><nav>menu menu</nav><script>var x=1;</script><p>{body}</p><footer>foot</footer></body></html>"


def page(body, title="Guide"):
    return "text/html", HTML.format(t=title, body=body).encode()


def fetcher(pages):
    def fetch(url):
        v = pages.get(url)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise IngestError("http_404")
        return v
    return fetch


def entry(url, **kw):
    return SourceEntry(url=url, institution="Test University", included=True, crop=kw.pop("crop", "tomato"), topics=kw.pop("topics", ["leaf spot"]), **kw)


def setup(tmp_path, entries):
    ingestion.write_manifest(tmp_path / "sources.json", entries)
    return tmp_path


T1, R1 = "https://a.example.ac.in/tomato", "https://b.example.ac.in/rice"


# ---------------- ingestion ----------------
def test_ingestion_creates_chunks_with_full_source_metadata(tmp_path):
    d = setup(tmp_path, [entry(T1, title="Tomato guide", region="Andhra Pradesh", published="2024")])
    rep = ingestion.ingest(d, fetch=fetcher({T1: page(AGRI * 3, "Tomato")}))
    assert rep.sources_ingested == 1 and rep.chunks_added >= 1 and not rep.failures
    chunks = retrieval.load_chunks(d / "documents.jsonl")
    c = chunks[0]
    assert (c.source_url, c.institution, c.crop, c.topic, c.region, c.date, c.title) == (T1, "Test University", "tomato", "leaf spot", "Andhra Pradesh", "2024", "Tomato guide")
    assert c.retrieved_at and c.content_hash and "menu" not in c.text and "var x" not in c.text and "foot" not in c.text
    m = ingestion.read_manifest(d / "sources.json")[0]
    assert m.content_hash and m.retrieved_at and m.reason == "ingested"


def test_reingesting_is_idempotent_and_duplicates_are_detected(tmp_path):
    other = "https://c.example.ac.in/copy"
    d = setup(tmp_path, [entry(T1), entry(other)])
    pages = {T1: page(AGRI * 3), other: page(AGRI * 3)}  # the same text at two URLs
    rep = ingestion.ingest(d, fetch=fetcher(pages))
    entries = {e.url: e for e in ingestion.read_manifest(d / "sources.json")}
    assert rep.sources_ingested == 1 and entries[other].included is False and entries[other].reason.startswith("duplicate_of:")
    n = len(retrieval.load_chunks(d / "documents.jsonl"))
    rep2 = ingestion.ingest(d, fetch=fetcher(pages))
    assert rep2.sources_unchanged == 1 and rep2.chunks_added == 0 and len(retrieval.load_chunks(d / "documents.jsonl")) == n


def test_a_changed_page_is_not_silently_replaced_and_old_version_is_archived_on_accept(tmp_path):
    d = setup(tmp_path, [entry(T1)])
    ingestion.ingest(d, fetch=fetcher({T1: page(AGRI * 3)}))
    before = (d / "documents.jsonl").read_text(encoding="utf-8")
    rep = ingestion.ingest(d, fetch=fetcher({T1: page(AGRI * 3 + " A new paragraph about nutrient deficiency of the crop plants and soil. " * 6)}))
    assert rep.updates_available == [T1] and (d / "documents.jsonl").read_text(encoding="utf-8") == before
    assert ingestion.read_manifest(d / "sources.json")[0].update_available is True
    ingestion.ingest(d, fetch=fetcher({T1: page(AGRI * 3 + " A new paragraph about nutrient deficiency of the crop plants and soil. " * 6)}), accept_updates=True)
    assert (d / "documents.archive.jsonl").exists() and (d / "documents.archive.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("fetch_result,reason", [
    (IngestError("http_403"), "http_403"),
    (IngestError("unreachable_ConnectError"), "unreachable_ConnectError"),
    (("text/html", b"<html><body>too little</body></html>"), "too_short"),
    (page("The football match was great and the team scored many goals in the stadium tonight. " * 20), "not_agricultural"),
    (("application/zip", b"PK\x03\x04"), "unsupported_content_type"),
    (("application/pdf", b"%PDF-1.4 broken"), None),  # malformed PDF: either unsupported or malformed, never a crash
])
def test_inaccessible_malformed_irrelevant_sources_add_nothing(tmp_path, fetch_result, reason):
    d = setup(tmp_path, [entry(T1)])
    rep = ingestion.ingest(d, fetch=fetcher({T1: fetch_result}))
    assert rep.chunks_added == 0 and T1 in rep.failures
    if reason:
        assert rep.failures[T1] == reason
    assert retrieval.load_chunks(d / "documents.jsonl") == []


def test_only_included_sources_are_fetched(tmp_path):
    seen = []
    e = entry(T1)
    e.included = False

    def fetch(url):
        seen.append(url)
        return page(AGRI * 3)

    ingestion.ingest(setup(tmp_path, [e]), fetch=fetch)
    assert seen == []


def test_default_fetch_refuses_plain_http():
    with pytest.raises(IngestError, match="not_https"):
        ingestion.default_fetch("http://example.ac.in/x")


# ---------------- retrieval ----------------
@pytest.fixture()
def corpus(tmp_path):
    d = setup(tmp_path, [entry(T1, title="Tomato guide"), entry(R1, crop="rice", topics=["blast"], title="Rice guide")])
    ingestion.ingest(d, fetch=fetcher({T1: page(AGRI * 3), R1: page(RICE)}))
    return retrieval.get_index(d)


def test_bm25_ranks_the_relevant_source_first_and_cites_its_metadata(corpus):
    hits = corpus.search("brown spots on lower leaves with rings")
    assert hits and hits[0][0].source_url == T1 and hits[0][1] > 0


def test_crop_filter_keeps_only_that_crop(corpus):
    assert {c.crop for c, _ in corpus.search("rice blast diamond shaped spots grey centres", crop="rice")} == {"rice"}
    assert all(c.crop == "tomato" for c, _ in corpus.search("fungal disease leaf spots", crop="tomato"))
    assert corpus.search("fungal disease leaf spots", crop="cotton") == [] or all(c.crop in ("", "cotton") for c, _ in corpus.search("fungal disease", crop="cotton"))


def test_topic_filter(corpus):
    assert {c.crop for c, _ in corpus.search("rice blast diamond shaped spots grey centres", topic="blast")} == {"rice"}
    assert corpus.search("fungal disease spots leaf", topic="nonexistent topic") == []


def test_irrelevant_query_and_empty_query_return_nothing(corpus):
    assert corpus.search("cricket stadium football") == [] and corpus.search("") == []


def test_empty_or_missing_knowledge_base_is_a_normal_state(tmp_path):
    idx = retrieval.get_index(tmp_path)  # no files at all
    assert len(idx) == 0 and idx.search("anything") == []
    ev = knowledge.run(idx, "Tomato", "spots", CropAnalysis(candidate_issues=["leaf spot"]))
    assert ev.retrieved_evidence == [] and ev.knowledge_gaps == ["no_knowledge_base"]


def test_malformed_corpus_lines_are_skipped_not_fatal(tmp_path):
    (tmp_path / "documents.jsonl").write_text('{"not": "a chunk"}\nnot json at all\n', encoding="utf-8")
    assert retrieval.load_chunks(tmp_path / "documents.jsonl") == []


def test_knowledge_agent_returns_source_aware_evidence_and_gaps(corpus):
    ev = knowledge.run(corpus, "Tomato", "brown spots rings", CropAnalysis(candidate_issues=["Early blight leaf spot"], observations=["brown spots"]))
    assert ev.retrieved_evidence
    top = ev.retrieved_evidence[0]
    assert top.url == T1 and top.institution == "Test University" and top.title == "Tomato guide" and top.crop == "tomato" and 0 < top.relevance < 1 and top.excerpt
    none = knowledge.run(corpus, "Tomato", "zzz", CropAnalysis(candidate_issues=["quantum chromodynamics"]))
    assert none.retrieved_evidence == [] and none.knowledge_gaps == ["nothing_relevant_found"]


def test_every_retrieved_item_comes_from_a_stored_chunk_never_fabricated(corpus):
    stored_urls = {c.source_url for c in corpus.chunks}
    for q in ("fungal", "blast rice", "brown spots", "insect holes pest"):
        for item in knowledge.run(corpus, "Tomato", q, CropAnalysis(candidate_issues=[q])).retrieved_evidence:
            assert item.url in stored_urls and item.id in {c.id for c in corpus.chunks}


# ---------------- source validation (discovery) ----------------
def test_host_gate_accepts_institutions_and_rejects_blogs_and_forums():
    assert discovery.host_ok("https://www.icar.gov.in/page") is None
    assert discovery.host_ok("https://angrau.ac.in/x") is None
    assert discovery.host_ok("https://agrifarming.example.com/x") == "not_an_authoritative_domain"
    for bad in ("https://www.quora.com/x", "https://www.reddit.com/r/x", "https://myfarm.blogspot.com/x"):
        assert discovery.host_ok(bad) in ("excluded_site_type", "not_an_authoritative_domain")
    assert discovery.host_ok("http://www.icar.gov.in/x") == "not_https"


def test_validate_records_every_candidate_with_a_reason(tmp_path):
    good = discovery.validate({"url": T1, "institution": "Test University", "crop": "Tomato", "topics": ["leaf spot"]}, fetch=fetcher({T1: page(AGRI * 3, "Tomato Guide")}))
    assert good.included and good.title == "Tomato Guide" and good.crop == "tomato" and good.retrieved_at and good.reason.startswith("verified")
    assert not discovery.validate({"url": T1}, fetch=fetcher({})).included  # institution not stated
    assert discovery.validate({"url": "https://blog.example.com/x", "institution": "x"}, fetch=fetcher({})).reason == "not_an_authoritative_domain"
    assert discovery.validate({"url": R1, "institution": "x"}, fetch=fetcher({R1: IngestError("http_404")})).reason == "rejected:http_404"
    assert discovery.validate({"url": R1, "institution": "x"}, fetch=fetcher({R1: page("sports " * 200)})).reason == "rejected:not_agricultural"


def test_discover_updates_the_manifest_without_overwriting_trusted_entries(tmp_path):
    pages = {T1: page(AGRI * 3), R1: page(RICE)}
    discovery.discover([{"url": T1, "institution": "Test University", "crop": "tomato"}], directory=tmp_path, fetch=fetcher(pages))
    out = discovery.discover([{"url": T1, "institution": "Someone Else"}, {"url": R1, "institution": "Test University", "crop": "rice"}], directory=tmp_path, fetch=fetcher(pages))
    by = {e.url: e for e in out}
    assert by[T1].institution == "Test University" and by[R1].included  # first record kept
    assert json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))[0]["url"] == T1


# ---------------- treatment text never enters the corpus ----------------
def test_strip_treatment_removes_chemical_dose_and_application_sentences_and_keeps_symptoms():
    t = ("Spots are brown with rings.\nSpray Mancozeb @ 2 g/lit at 15 day interval. Scout the field weekly.\n"
         "Apply 5 kg per acre of fertilizer. Dipping fruits in 200 ppm solution helps. Monthly sprayings are advised.\n"
         "The disease favours humid weather.")
    out = ingestion.strip_treatment(t)
    assert "Spots are brown" in out and "Scout the field weekly" in out and "humid weather" in out
    for banned in ("Mancozeb", "g/lit", "kg per acre", "ppm", "sprayings"):
        assert banned not in out


# ---------------- the shipped corpus (backend/knowledge) is audited ----------------
KB_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "knowledge"


@pytest.mark.skipif(not (KB_DIR / "documents.jsonl").exists() or not (KB_DIR / "documents.jsonl").stat().st_size, reason="no shipped corpus")
def test_shipped_corpus_is_fully_traceable_and_has_no_treatment_text():
    import re
    chunks = retrieval.load_chunks(KB_DIR / "documents.jsonl")
    manifest = {e.url: e for e in ingestion.read_manifest(KB_DIR / "sources.json")}
    assert chunks
    assert len({c.id for c in chunks}) == len(chunks) and len({c.content_hash for c in chunks}) == len(chunks)  # no duplicates
    for c in chunks:
        e = manifest[c.source_url]  # every chunk traces to a manifest entry
        assert e.included and e.institution == c.institution and c.source_url.startswith("https://") and c.retrieved_at and e.retrieved_at
        assert domain_ok(c.source_url)
        assert not re.search(r"\b(spray\w*|fungicides?|insecticides?|pesticides?|mancozeb|ppm)\b|@\s*\d|\d\s*(ml|g|kg)\s*/", c.text, re.I)
    for e in manifest.values():  # every manifest row says why it is in or out
        assert e.reason and (e.included or not e.content_hash)


def domain_ok(url):
    return discovery.host_ok(url) is None
