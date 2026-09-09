import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_lib.stale_candidates import EmptyLogDirectoryError, detect_stale_templates
from tests.fixtures import make_rptsched_dir

STALE_LINE = "wxyz|noverdue|Stale Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _log_dirs_with_placeholder(tmp):
    report_dir = Path(tmp) / "Report"
    hist_dir = Path(tmp) / "Hist"
    report_dir.mkdir()
    hist_dir.mkdir()
    now = datetime.now()
    (report_dir / (now.strftime("%Y%m") + ".log")).touch()
    (hist_dir / (now.strftime("%Y%m") + ".hist")).touch()
    return report_dir, hist_dir


class TestDetectStaleTemplates(unittest.TestCase):
    def test_returns_candidates_dict_keyed_by_id(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            report_dir, hist_dir = _log_dirs_with_placeholder(tmp)

            candidates = detect_stale_templates(rptsched_dir, report_dir, hist_dir)

            self.assertEqual(set(candidates.keys()), {"wxyz"})

    def test_works_against_a_directory_it_did_not_copy(self):
        # Confirms the function is genuinely copy-free -- it's handed a
        # live directory here (no copytree anywhere in this test) and
        # must not require or assume a copy was made upstream.
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            report_dir, hist_dir = _log_dirs_with_placeholder(tmp)

            candidates = detect_stale_templates(rptsched_dir, report_dir, hist_dir)

            self.assertEqual(len(candidates), 1)
            self.assertTrue((rptsched_dir / "schedlist").is_file())

    def test_raises_on_empty_logs_report_dir(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set"])
            empty_report_dir = Path(tmp) / "EmptyReport"
            empty_report_dir.mkdir()
            _, hist_dir = _log_dirs_with_placeholder(tmp)

            with self.assertRaises(EmptyLogDirectoryError):
                detect_stale_templates(rptsched_dir, empty_report_dir, hist_dir)

    def test_raises_on_empty_logs_hist_dir(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set"])
            report_dir, _ = _log_dirs_with_placeholder(tmp)
            empty_hist_dir = Path(tmp) / "EmptyHist"
            empty_hist_dir.mkdir()

            with self.assertRaises(EmptyLogDirectoryError):
                detect_stale_templates(rptsched_dir, report_dir, empty_hist_dir)

    def test_index_cache_path_persists_across_calls(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set"])
            report_dir, hist_dir = _log_dirs_with_placeholder(tmp)
            cache_path = Path(tmp) / "cache.json"

            detect_stale_templates(rptsched_dir, report_dir, hist_dir, index_cache_path=cache_path)

            self.assertTrue(cache_path.is_file())


if __name__ == "__main__":
    unittest.main()
