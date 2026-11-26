from openpyxl import load_workbook

from app import export_calendar


def test_export_five_companies(tmp_path, monkeypatch):
    saved = {}

    def save(workbook, path):
        saved["workbook"] = workbook

    monkeypatch.setattr("openpyxl.workbook.workbook.Workbook.save", save)

    export_calendar.main(2026)

    monkeypatch.undo()
    target = tmp_path / "export.xlsx"
    saved["workbook"].save(target)
    workbook = load_workbook(target)
    assert workbook.sheetnames == ["Компании", "1", "2", "3", "4", "5", "Правила", "Вопросы"]
    for name in "12345":
        rows = list(workbook[name].iter_rows(min_row=4, values_only=True))
        assert len(rows) > 10
        assert all(row[0].year == 2026 and row[6] for row in rows)
    assert workbook["Вопросы"].max_row > 10
