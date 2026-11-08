"""AI cover letters without a database: the prompt, the worker task, the answer checks and the PDF."""
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from job_hunter.llm import FakeLlm
from job_hunter.llm.tasks import run_task
from job_hunter.preparation import cover_letter
from job_hunter.preparation.cover_letter import LetterUnusable, build_prompt, check_letter, generate, parse_own_letter, plain_text
from job_hunter.preparation.rendering import pdf_bytes

EVIDENCE = {"summary": "Backend engineer who builds data pipelines.", "skill:Python": "Python",
            "b1": "Designed incremental SQL pipelines with duplicate detection."}
JOB = {"title": "Data Engineer", "company": "Northstar", "description": "Build pipelines in Python for Northstar."}
KNOWN = " ".join([*EVIDENCE.values(), JOB["title"], JOB["company"], JOB["description"]])


def payload(**extra):
    return {"mode": "write", "tone": "formal", "job": JOB, "evidence": EVIDENCE, **extra}


def test_the_prompt_quotes_the_job_and_evidence_as_data_and_leaves_contact_details_out():
    system, user = build_prompt(payload(points="Mention my open source work."))
    assert "untrusted data" in system and "formal and professional" in system
    assert "<<<JOB" in user and "<<<EVIDENCE" in user and "<<<NOTES" in user and "<<<LETTER" not in user
    assert "Northstar" in user and "b1" in user


def test_improve_mode_sends_the_existing_letter_and_the_tone_changes_the_wording():
    system, user = build_prompt(payload(mode="improve", tone="friendly", letter="Dear team, I like data."))
    assert "<<<LETTER" in user and "I like data" in user
    assert "improve a jobseeker's existing cover letter" in system and "warm and friendly" in system


def test_an_unknown_mode_is_refused():
    with pytest.raises(LetterUnusable):
        build_prompt(payload(mode="rewrite everything"))


def test_a_long_profile_is_cut_to_what_fits():
    many = {f"b{i}": "x" * 400 for i in range(100)}
    _, user = build_prompt(payload(evidence=many))
    assert len(user) < 12000


def test_generate_returns_paragraphs_and_claims_and_rejects_a_reply_without_paragraphs():
    answer = {"paragraphs": ["One.", "Two."], "claims": [{"text": "pipelines", "evidence": ["b1"]}]}
    assert generate(FakeLlm([answer]), payload()) == answer
    with pytest.raises(LetterUnusable):
        generate(FakeLlm([{"letter": "no paragraphs key"}]), payload())


def test_the_worker_task_returns_the_letter_or_a_named_failure():
    request = {"request_id": "r1", "task": "cover_letter", "input": payload()}
    answer, outcome = run_task(FakeLlm([{"paragraphs": ["Hello."], "claims": []}]), request)
    assert outcome == "ok" and answer["paragraphs"] == ["Hello."]
    answer, outcome = run_task(FakeLlm([{"nothing": 1}]), request)
    assert outcome == "MODEL_UNAVAILABLE" and answer == {"error": "MODEL_UNAVAILABLE"}


def test_claims_with_real_evidence_are_confirmed_and_the_rest_are_flagged():
    answer = {"paragraphs": ["I built SQL pipelines in Python."],
              "claims": [{"text": "Built SQL pipelines", "evidence": ["b1"]},
                         {"text": "Led a team", "evidence": ["made-up-id"]},
                         {"text": "Knows Python", "evidence": []}]}
    paragraphs, notes = check_letter(answer, evidence=EVIDENCE, known_text=KNOWN)
    assert paragraphs == ["I built SQL pipelines in Python."]
    by_text = {note["text"].split(":")[0]: note["kind"] for note in notes if ":" in note["text"]}
    assert by_text["Built SQL pipelines"] == "ok" and by_text["Led a team"] == "warn" and by_text["Knows Python"] == "warn"
    assert "Designed incremental SQL pipelines" in notes[0]["text"]          # names the profile item it came from
    assert notes[-1]["kind"] == "info"


def test_a_claim_that_ends_with_a_full_stop_does_not_leave_a_stray_one_before_the_colon():
    answer = {"paragraphs": ["I built SQL pipelines."], "claims": [{"text": "Built SQL pipelines.", "evidence": ["b1"]}, {"text": "Led a team;", "evidence": []}]}
    _, notes = check_letter(answer, evidence=EVIDENCE, known_text=KNOWN)
    assert notes[0]["text"].startswith("Built SQL pipelines: from your profile")
    assert notes[1]["text"].startswith("Led a team: could not be matched")


def test_a_number_or_name_found_nowhere_in_the_material_is_flagged():
    answer = {"paragraphs": ["I cut costs by 40% at Globex using Kubernetes."], "claims": []}
    _, notes = check_letter(answer, evidence=EVIDENCE, known_text=KNOWN)
    texts = " ".join(note["text"] for note in notes if note["kind"] == "warn")
    assert "40" in texts and "Globex" in texts and "Kubernetes" in texts


def test_a_number_that_is_in_the_profile_is_not_flagged():
    answer = {"paragraphs": ["I have 5 years of experience."], "claims": []}
    _, notes = check_letter(answer, evidence=EVIDENCE, known_text=KNOWN + " 5 years in data")
    assert not [note for note in notes if note["kind"] == "warn"]


@pytest.mark.parametrize("bad", [None, "text", {"error": "MODEL_UNAVAILABLE"}, {"paragraphs": "one string"}, {"paragraphs": []},
                                 {"paragraphs": ["", "   ", 7]}])
def test_an_answer_with_no_usable_paragraph_is_refused(bad):
    with pytest.raises(LetterUnusable):
        check_letter(bad, evidence=EVIDENCE, known_text=KNOWN)


def test_paragraphs_are_trimmed_and_capped():
    paragraphs, _ = check_letter({"paragraphs": ["  hello   world  ", "x" * 5000] + ["p"] * 20, "claims": []}, evidence={}, known_text="")
    assert paragraphs[0] == "hello world" and len(paragraphs[1]) == cover_letter.MAX_PARAGRAPH and len(paragraphs) <= cover_letter.MAX_PARAGRAPHS


def test_at_most_six_claims_are_reported():
    claims = [{"text": f"claim {i}", "evidence": ["b1"]} for i in range(20)]
    _, notes = check_letter({"paragraphs": ["Hi."], "claims": claims}, evidence=EVIDENCE, known_text=KNOWN)
    assert len([note for note in notes if note["kind"] == "ok"]) == cover_letter.MAX_CLAIMS


def test_a_pasted_letter_is_split_into_greeting_paragraphs_and_sign_off_without_a_model():
    pasted = "Dear Ms Lim,\n\nI am applying for the data role.\r\nI have built pipelines.\n\nThank you for reading this.\n\nYours sincerely,\nAlex Tan"
    assert parse_own_letter(pasted) == {"greeting": "Dear Ms Lim,", "paragraphs": ["I am applying for the data role. I have built pipelines.", "Thank you for reading this."],
                                         "closing": "Yours sincerely,", "signature": "Alex Tan"}


def test_a_pasted_letter_without_a_greeting_or_sign_off_keeps_everything_as_paragraphs():
    assert parse_own_letter("First paragraph here.\n\nSecond one.") == {"paragraphs": ["First paragraph here.", "Second one."]}
    assert parse_own_letter("   \n\n  ") == {"paragraphs": [""]}
    assert parse_own_letter("Just one block of text with Dear in the middle.")["paragraphs"] == ["Just one block of text with Dear in the middle."]


def test_a_long_paste_is_capped_and_a_real_closing_paragraph_is_not_taken_for_a_sign_off():
    many = "\n\n".join(f"Paragraph {i}." for i in range(20))
    assert len(parse_own_letter(many)["paragraphs"]) == 12
    result = parse_own_letter("Intro.\n\nThank you for taking the time to read about my background and the work I have done over the years.")
    assert "closing" not in result and len(result["paragraphs"]) == 2


def test_plain_text_is_the_letter_without_the_header():
    content = {"greeting": "Dear Team,", "paragraphs": ["One.", "Two."], "closing": "Regards,", "signature": "Alex"}
    assert plain_text(content) == "Dear Team,\n\nOne.\n\nTwo.\n\nRegards,\nAlex\n"


def letter_doc(**content):
    base = {"name": "Alex Tan", "email": "alex@example.com", "phone": "", "location": "Singapore", "date": "25 October 2026",
            "recipient": "Hiring Team\nNorthstar", "greeting": "Dear Hiring Team,", "paragraphs": ["First paragraph.", "Second <b>one</b> & more."],
            "closing": "Yours sincerely,", "signature": "Alex Tan"}
    return SimpleNamespace(kind="cover_letter", title="Cover letter", template="classic", layout={"font_size": 11, "margin": 22},
                           content={**base, **content})


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_the_letter_renders_as_a_pdf_with_every_part_and_escapes_markup():
    data = pdf_bytes(letter_doc())
    assert data.startswith(b"%PDF")
    text = pdf_text(data)
    for expected in ("Alex Tan", "alex@example.com", "25 October 2026", "Northstar", "Dear Hiring Team,", "First paragraph.",
                     "Second <b>one</b> & more.", "Yours sincerely,"):
        assert expected in text


def test_an_empty_letter_still_renders_and_the_style_settings_apply():
    assert pdf_bytes(letter_doc(paragraphs=[""], name="")).startswith(b"%PDF")
    doc = letter_doc()
    doc.layout = {"font_size": 14, "margin": 30, "font_family": "mono", "page_size": "letter", "line_spacing": 1.6}
    assert pdf_bytes(doc).startswith(b"%PDF")


def test_evidence_ids_copied_into_the_letter_text_are_removed():
    # ornith1.5:35b (Nov 2026) cited ids inline; the letter must read cleanly and keep normal brackets and words.
    evidence = {"b_324b8bc25f5859338b23a131f321e7f8": "Built REST endpoints", "education:0": "B.Comp. at Example University",
                "summary": "Backend engineer", "skill:Python": "Python"}
    answer = {"paragraphs": [
        "I built REST endpoints used by about 40 staff (b_324b8bc25f5859338b23a131f321e7f8). I cut release time from "
        "45 minutes to 10 (b_de4e5c8038f9530b863308bc1c990406, education:0).",
        "I hold a B.Comp. (Computer Science) from Example University (education:0), and my summary is skill:Python based.",
    ], "claims": []}
    paragraphs, _ = check_letter(answer, evidence=evidence, known_text="Built REST endpoints 40 staff 45 minutes 10 B.Comp. Computer Science Example University Python")
    assert paragraphs[0] == "I built REST endpoints used by about 40 staff. I cut release time from 45 minutes to 10."
    assert paragraphs[1] == "I hold a B.Comp. (Computer Science) from Example University, and my summary is based."
    assert "b_" not in " ".join(paragraphs)
