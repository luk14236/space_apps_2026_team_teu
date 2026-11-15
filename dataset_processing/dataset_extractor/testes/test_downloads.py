import csv

from firms_pipeline import SOURCE_COLUMNS


def test_report_and_source_files_are_complete(sample_dataset):
    with sample_dataset["report"].open(newline="", encoding="utf-8") as handle:
        report = list(csv.DictReader(handle))
    assert report
    assert {row["status"] for row in report} == {"downloaded"}
    for row, path in zip(report, sample_dataset["source_files"]):
        assert path.is_file()
        assert path.stat().st_size == int(row["expected_size"]) == int(row["local_size"])
        with path.open(encoding="utf-8") as source:
            assert SOURCE_COLUMNS <= set(next(csv.reader(source)))
    assert not list(sample_dataset["root"].rglob("*.part"))


def test_only_selected_source_ids_in_fixture(sample_dataset):
    allowed = {"modis", "viirs-snpp", "viirs-jpss1"}
    assert {path.parent.parent.name for path in sample_dataset["source_files"]} <= allowed
