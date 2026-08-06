import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
import pytest

from pii_detector import PIIMatch
from src.services.deidentification_service import (
    DeidentificationService,
    DeidentifyRequest,
    KEY_FILE_NAME,
    LOG_FILE_NAME,
)


def _make_pdf(path, lines):
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 20
    doc.save(str(path))
    doc.close()


def _match(text, category='Student name', page_num=1, line_num=1):
    return PIIMatch(text=text, category=category, confidence=0.95,
                    page_num=page_num, line_num=line_num, context=text)


def _request(tmp, doc, matches, page_text, **kwargs):
    """Build a request whose detection cache mimics what the API layer passes."""
    detected = {
        doc: {
            'matches': matches,
            'text_data': {
                'pages': {1: {'text': page_text, 'method': 'native'}},
                'ocr_pages': kwargs.pop('ocr_pages', []),
                'total_pages': 1,
            },
        }
    }
    selections = {f"{doc}_{i}": True for i in range(len(matches))}
    selections.update(kwargs.pop('selections', {}))
    return DeidentifyRequest(
        folder_path=Path(tmp),
        student_name=kwargs.pop('student_name', 'Billy Bob'),
        documents=[doc],
        detected_pii=detected,
        user_selections=selections,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_produces_text_file_with_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )

            assert results.successfully_deidentified == 1
            out = results.document_results[0].output_path
            assert out.suffix == ".txt"
            body = out.read_text(encoding='utf-8')
            assert "[Student]" in body
            assert "Billy" not in body
            assert "Bob" not in body

    def test_output_filename_strips_pii(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "Billy Bob report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            name = results.document_results[0].output_path.name
            assert "Billy" not in name
            assert name.endswith("_deidentified.txt")

    def test_labels_are_consistent_across_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_a = Path(tmp) / "a.pdf"
            doc_b = Path(tmp) / "b.pdf"
            text_a = "Billy Bob met Sarah Williams."
            text_b = "Sarah Williams wrote about Billy Bob."
            _make_pdf(doc_a, [text_a])
            _make_pdf(doc_b, [text_b])

            matches_a = [_match("Billy Bob"), _match("Sarah Williams", "Person name (NER)")]
            matches_b = [_match("Sarah Williams", "Person name (NER)"), _match("Billy Bob")]
            detected = {
                doc_a: {'matches': matches_a,
                        'text_data': {'pages': {1: {'text': text_a, 'method': 'native'}},
                                      'ocr_pages': []}},
                doc_b: {'matches': matches_b,
                        'text_data': {'pages': {1: {'text': text_b, 'method': 'native'}},
                                      'ocr_pages': []}},
            }
            selections = {}
            for d, ms in ((doc_a, matches_a), (doc_b, matches_b)):
                selections.update({f"{d}_{i}": True for i in range(len(ms))})

            results = DeidentificationService().execute(DeidentifyRequest(
                folder_path=Path(tmp), student_name="Billy Bob",
                documents=[doc_a, doc_b], detected_pii=detected,
                user_selections=selections,
            ))

            bodies = [r.output_path.read_text(encoding='utf-8')
                      for r in results.document_results]
            assert all("[Other person]" in b for b in bodies)
            assert all("Sarah" not in b for b in bodies)

    def test_deselected_item_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob and Riverside Primary School."
            _make_pdf(doc, [text])

            matches = [_match("Billy Bob"),
                       _match("Riverside Primary School", "Organisation name")]
            req = _request(tmp, doc, matches, text,
                           organisation_names=["Riverside Primary School"])
            req.user_selections[f"{doc}_1"] = False

            results = DeidentificationService().execute(req)
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "Riverside" in body
            assert "Billy" not in body

    def test_multiple_students_get_distinct_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob sat next to Billy Chen during the test."
            _make_pdf(doc, [text])

            matches = [_match("Billy Bob"), _match("Billy Chen", "Person name (NER)")]
            results = DeidentificationService().execute(
                _request(tmp, doc, matches, text)
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "[Student]" in body
            assert "[Other person]" in body
            assert "Chen" not in body


# ---------------------------------------------------------------------------
# The key file
# ---------------------------------------------------------------------------

class TestKeyFile:

    def test_key_file_written_next_to_originals_not_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )

            assert results.key_file_path == Path(tmp) / KEY_FILE_NAME
            assert results.key_file_path.exists()
            # Nothing in the output folder may re-identify anyone.
            assert not (results.output_folder / KEY_FILE_NAME).exists()

    def test_key_file_name_carries_the_warning(self):
        assert "DO-NOT-UPLOAD" in KEY_FILE_NAME

    def test_key_file_maps_labels_to_real_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         parent_names=["Mary Bloggs"])
            )
            key = results.key_file_path.read_text(encoding='utf-8')
            assert "DO NOT UPLOAD" in key
            assert "[Student]" in key and "Billy Bob" in key
            assert "[Parent]" in key and "Mary Bloggs" in key

    def test_key_file_records_shared_name_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob sat with Billy Chen."
            _make_pdf(doc, [text])

            matches = [_match("Billy Bob"), _match("Billy Chen", "Person name (NER)")]
            results = DeidentificationService().execute(
                _request(tmp, doc, matches, text)
            )
            key = results.key_file_path.read_text(encoding='utf-8')
            assert "SHARED BY MORE THAN ONE PERSON" in key
            assert "Billy Chen" in key


# ---------------------------------------------------------------------------
# The audit log must never become a second key file
# ---------------------------------------------------------------------------

class TestAuditLogCarriesNoNames:

    def test_log_contains_labels_not_real_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob and Mary Bloggs attended Riverside Primary School."
            _make_pdf(doc, [text])

            matches = [
                _match("Billy Bob"),
                _match("Mary Bloggs", "Parent/Guardian (user-provided)"),
                _match("Riverside Primary School", "Organisation name"),
            ]
            results = DeidentificationService().execute(
                _request(tmp, doc, matches, text,
                         parent_names=["Mary Bloggs"],
                         organisation_names=["Riverside Primary School"])
            )

            log = results.log_content
            for leaked in ("Billy", "Bob", "Mary", "Bloggs", "Riverside"):
                assert leaked not in log, f"audit log leaked {leaked!r}"
            assert "[Student]" in log
            assert "[Parent]" in log

    def test_log_saved_under_its_own_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert results.log_path.name == LOG_FILE_NAME
            assert results.log_path.exists()


# ---------------------------------------------------------------------------
# Header/footer, images, verification, cancel
# ---------------------------------------------------------------------------

class TestHeaderFooterZones:

    def test_header_text_dropped_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72, 20), "Riverside Primary School Letterhead", fontsize=10)
            page.insert_text((72, 400), "Billy Bob is in Year 3.", fontsize=12)
            pdf.save(str(doc))
            pdf.close()

            page_text = "Riverside Primary School Letterhead\nBilly Bob is in Year 3."
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], page_text,
                         redact_header_footer=True)
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "Letterhead" not in body
            assert "Year 3" in body

    def test_header_text_kept_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72, 20), "Riverside Primary School Letterhead", fontsize=10)
            page.insert_text((72, 400), "Billy Bob is in Year 3.", fontsize=12)
            pdf.save(str(doc))
            pdf.close()

            page_text = "Riverside Primary School Letterhead\nBilly Bob is in Year 3."
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], page_text,
                         redact_header_footer=False)
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "Letterhead" in body

    def test_scanned_pages_report_the_header_footer_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "scan.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         ocr_pages=[1], redact_header_footer=True)
            )
            warnings = " ".join(results.document_results[0].ocr_warnings)
            assert "Header/footer" in warnings


class TestVerification:

    def test_clean_run_is_not_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert results.document_results[0].quarantine_path is None
            assert results.document_results[0].success

    def test_ocr_misread_quarantines_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "scan.pdf"
            _make_pdf(doc, ["placeholder"])

            # OCR produced a near-miss of the student's name, so exact
            # replacement could not catch it.
            page_text = "Sarnh Williams attended today."
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Sarah Williams")], page_text,
                         student_name="Sarah Williams", ocr_pages=[1])
            )
            doc_result = results.document_results[0]
            assert not doc_result.success
            assert doc_result.quarantine_path is not None
            assert doc_result.quarantine_path.name.endswith(".UNVERIFIED.txt")
            assert doc_result.verification_failures


class TestImagesAndCancel:

    def test_embedded_images_are_reported_as_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72, 400), "Billy Bob is in Year 3.", fontsize=12)
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
            pix.set_rect(pix.irect, (200, 200, 200))
            page.insert_image(fitz.Rect(72, 60, 112, 100), pixmap=pix)
            pdf.save(str(doc))
            pdf.close()

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], "Billy Bob is in Year 3.")
            )
            warnings = " ".join(results.document_results[0].image_warnings)
            assert "not included" in warnings

    def test_cancel_stops_between_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_a = Path(tmp) / "a.pdf"
            doc_b = Path(tmp) / "b.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc_a, [text])
            _make_pdf(doc_b, [text])

            detected = {
                d: {'matches': [_match("Billy Bob")],
                    'text_data': {'pages': {1: {'text': text, 'method': 'native'}},
                                  'ocr_pages': []}}
                for d in (doc_a, doc_b)
            }
            selections = {f"{d}_0": True for d in (doc_a, doc_b)}

            calls = {'n': 0}

            def should_cancel():
                calls['n'] += 1
                return calls['n'] > 1

            results = DeidentificationService().execute(
                DeidentifyRequest(
                    folder_path=Path(tmp), student_name="Billy Bob",
                    documents=[doc_a, doc_b], detected_pii=detected,
                    user_selections=selections,
                ),
                should_cancel=should_cancel,
            )
            assert results.cancelled
            assert len(results.document_results) == 1
            assert results.total_documents == 2
            assert "CANCELLED" in results.log_content


class TestCustomOutput:

    def test_custom_filename_honoured_for_single_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_filename="my summary.txt")
            )
            assert results.document_results[0].output_path.name == "my summary.txt"

    def test_custom_filename_forced_to_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_filename="my summary.pdf")
            )
            assert results.document_results[0].output_path.name == "my summary.txt"

    def test_custom_filename_cannot_escape_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_filename="../../escaped.txt")
            )
            out = results.document_results[0].output_path
            assert out.name == "escaped.txt"
            assert out.parent == results.output_folder

    def test_custom_output_path_used_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])
            target = Path(tmp) / "elsewhere"

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_path=target)
            )
            assert results.output_folder == target
            assert results.document_results[0].output_path.parent == target

    def test_missing_text_data_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            _make_pdf(doc, ["Billy Bob is here."])

            results = DeidentificationService().execute(DeidentifyRequest(
                folder_path=Path(tmp), student_name="Billy Bob",
                documents=[doc], detected_pii={}, user_selections={},
            ))
            assert not results.document_results[0].success
            assert "detection" in results.document_results[0].error_message.lower()


class TestSourceFilenameNeverLeaks:
    """
    Regression: assessment documents are routinely NAMED after the student
    ("Billy Bob Support Report.pdf"). Writing that filename into the output
    header or the audit log printed the very name everything else removed.
    """

    def test_output_file_does_not_name_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "Billy Bob Support Report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "Billy" not in body
            assert "Bob" not in body

    def test_audit_log_does_not_name_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "Billy Bob Support Report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert "Billy" not in results.log_content
            assert "Bob" not in results.log_content

    def test_quarantine_log_entry_does_not_name_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "Sarah Williams Report.pdf"
            _make_pdf(doc, ["placeholder"])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Sarah Williams")],
                         "Sarnh Williams attended today.",
                         student_name="Sarah Williams", ocr_pages=[1])
            )
            assert results.document_results[0].quarantine_path is not None
            assert "Sarah" not in results.log_content

    def test_ui_still_sees_the_real_document_name(self):
        """Only what's written to disk is sanitised — the local UI needs the
        real name so the user can recognise their file."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "Billy Bob Support Report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert results.document_results[0].document_name == "Billy Bob Support Report.pdf"

    def test_key_file_maps_originals_to_outputs(self):
        """The only place the two filenames can be matched up — and it belongs
        in the file that is already private."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "Billy Bob Support Report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])

            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            key = results.key_file_path.read_text(encoding='utf-8')
            assert "WHICH FILE CAME FROM WHICH" in key
            assert "Billy Bob Support Report.pdf" in key
            assert results.document_results[0].output_path.name in key


class TestLayoutFormatting:
    """The output text is rebuilt from block geometry: paragraphs reflowed,
    table rows reconstructed, header/footer dropped by position not string."""

    def _run(self, build, matches=None, student="Billy Bob", **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            pdf = fitz.open(); page = pdf.new_page()
            build(page)
            pdf.save(str(doc)); pdf.close()
            # Cached text as detection would have seen it.
            import sys as _s
            _s.path.insert(0, 'src/core')
            from text_extractor import TextExtractor
            text_data = TextExtractor().extract_text_from_pdf(doc)
            page_text = text_data['pages'][1]['text']
            req = _request(tmp, doc, matches or [], page_text,
                           student_name=student, **kwargs)
            results = DeidentificationService().execute(req)
            r = results.document_results[0]
            return (r.output_path or r.quarantine_path).read_text(encoding='utf-8'), results

    def test_hard_wrapped_paragraph_reflows_to_one_line(self):
        para = ("Results indicate that verbal comprehension skills fall within "
                "the average range for his age across all assessed domains.")
        def build(page):
            page.insert_textbox(fitz.Rect(55, 300, 400, 500), para, fontsize=10)
        body, _ = self._run(build)
        assert para in body.replace("\n", " ")
        # No mid-sentence hard wrap survives.
        assert "comprehension skills fall" in body

    def test_table_row_reconstructs_with_pipes(self):
        def build(page):
            for x, cell in zip([55, 230, 300, 380],
                               ["Working Memory", "79", "8", "Below average"]):
                page.insert_text((x, 400), cell, fontsize=10)
        body, _ = self._run(build)
        assert "Working Memory | 79 | 8 | Below average" in body

    def test_header_block_dropped_by_geometry_body_twin_survives(self):
        """The rule-49 guarantee, now positional: a body line identical to a
        letterhead line must survive."""
        def build(page):
            page.insert_text((55, 30), "Comments", fontsize=9)      # header zone
            page.insert_text((55, 400), "Comments", fontsize=10)    # body
            page.insert_text((55, 420), "Behaviour improved.", fontsize=10)
        body, _ = self._run(build, redact_header_footer=True)
        assert body.count("Comments") == 1
        assert "Behaviour improved." in body

    def test_footer_block_dropped_by_geometry(self):
        def build(page):
            page.insert_text((55, 400), "Body text here.", fontsize=10)
            page.insert_text((55, page.rect.height - 20), "Page 1 of 2", fontsize=8)
        body, _ = self._run(build, redact_header_footer=True)
        assert "Page 1 of 2" not in body
        assert "Body text here." in body

    def test_pii_straddling_a_cell_boundary_is_replaced_not_false_passed(self):
        """The reviewer's finding: decorate AFTER substitution, or a value split
        across two blocks on one row can neither be replaced nor verified."""
        def build(page):
            page.insert_text((55, 400), "42 Smith Street", fontsize=10)
            page.insert_text((260, 400), "Melbourne VIC 3000", fontsize=10)
        m = _match("42 Smith Street Melbourne VIC 3000", "Address")
        body, results = self._run(build, matches=[m])
        assert "Smith Street" not in body
        assert "[address]" in body
        assert results.document_results[0].success, "must not quarantine either"

    def test_widget_values_still_reach_the_output(self):
        """AcroForm values live outside the content stream; a geometry rebuild
        alone would silently drop them (reviewer finding 4)."""
        def build(page):
            page.insert_text((55, 400), "See form below.", fontsize=10)
            w = fitz.Widget()
            w.field_name = "parent"
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            w.rect = fitz.Rect(55, 430, 300, 450)
            w.field_value = "Contact Mary Bloggs on 0412 345 678"
            page.add_widget(w)
        m = _match("0412 345 678", "Phone number")
        body, _ = self._run(build, matches=[m])
        assert "Mary Bloggs" in body          # widget text made it into output
        assert "0412 345 678" not in body     # and its PII was replaced
        assert "[phone]" in body

    def test_unreadable_source_falls_back_to_cached_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])
            req = _request(tmp, doc, [_match("Billy Bob")], text)
            doc.unlink()  # source gone — cached text must still produce output
            results = DeidentificationService().execute(req)
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "[Student]" in body

    def test_output_header_names_role_labels_not_stale_parent1(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is in Year 3."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text))
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "[Parent 1]" not in body.split("=" * 70)[0]
            assert "[Teacher 1]" in body.split("=" * 70)[0]


class TestOutputFolderCollision:
    """
    The UI promises the output folder is safe to share. That is only true when
    it is a separate folder — pointing output at the source folder puts the
    originals and the key file right beside the de-identified copies. The Save
    As dialog opens in the source folder, so this is the DEFAULT path in
    single-document mode, not an edge case.
    """

    def test_flag_false_for_the_default_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert results.output_folder_holds_originals is False

    def test_flag_true_when_output_is_the_source_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_path=Path(tmp))
            )
            assert results.output_folder_holds_originals is True

    def test_key_file_says_so_when_folders_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_path=Path(tmp))
            )
            key = results.key_file_path.read_text(encoding='utf-8')
            assert "do not share the folder" in key.lower()

    def test_output_is_still_correctly_deidentified_when_folders_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text,
                         custom_output_path=Path(tmp))
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "[Student]" in body and "Billy" not in body


class TestNothingReplacedIsSaidPlainly:
    """A file with no replacements is the document verbatim. Calling it a
    de-identified copy would be a lie the filename already half-tells."""

    def test_zero_replacements_carries_a_warning_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Nothing personal in here at all."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [], text)
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "NOTHING WAS REPLACED" in body
            assert "Read it before sharing" in body

    def test_normal_run_does_not_carry_that_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is here."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            body = results.document_results[0].output_path.read_text(encoding='utf-8')
            assert "NOTHING WAS REPLACED" not in body


class TestNerSweep:
    """After replacement, the OUTPUT is swept for anything NER still reads as
    a person — the net under names detection never found."""

    def test_undetected_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = ("Billy Bob attended the session. Report prepared by "
                    "Jacinta Nguyen and reviewed the following week.")
            _make_pdf(doc, [text])
            # Only the student was detected/selected — Jacinta was missed.
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            r = results.document_results[0]
            assert r.success
            assert any("Jacinta" in w for w in r.leftover_name_warnings)

    def test_clean_output_has_no_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob is in Year 3 and enjoys reading."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert results.document_results[0].leftover_name_warnings == []

    def test_deliberately_deselected_name_is_not_nagged_about(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob met with Sarah Williams on Tuesday."
            _make_pdf(doc, [text])
            matches = [_match("Billy Bob"), _match("Sarah Williams", "Person name (NER)")]
            req = _request(tmp, doc, matches, text)
            req.user_selections[f"{doc}_1"] = False  # user KEEPS Sarah Williams
            results = DeidentificationService().execute(req)
            r = results.document_results[0]
            assert not any("Sarah" in w for w in r.leftover_name_warnings)

    def test_warnings_never_reach_the_audit_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.pdf"
            text = "Billy Bob was seen by Jacinta Nguyen."
            _make_pdf(doc, [text])
            results = DeidentificationService().execute(
                _request(tmp, doc, [_match("Billy Bob")], text)
            )
            assert "Jacinta" not in results.log_content
            assert "Nguyen" not in results.log_content
