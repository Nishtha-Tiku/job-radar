// Google Apps Script: receives the daily jobs and appends them to a "Daily Jobs" tab.
// 1. Change SECRET below to a long random string (use the same value as the SHEET_TOKEN GitHub secret).
// 2. Deploy > New deployment > type "Web app" > Execute as: Me > Who has access: Anyone > Deploy.
const SECRET = "CHANGE_ME_TO_A_LONG_RANDOM_STRING";

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.token !== SECRET) return out({ ok: false, error: "bad token" });

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sh = ss.getSheetByName("Daily Jobs");
    if (!sh) sh = ss.insertSheet("Daily Jobs");
    if (sh.getLastRow() === 0) {
      sh.appendRow(["Date", "Company", "Role", "Location", "Apply link", "Source", "Match score", "Link check", "Applied?"]);
      sh.setFrozenRows(1);
      sh.getRange(1, 1, 1, 9).setFontWeight("bold");
    }
    const rows = body.rows || [];
    if (rows.length) {
      const start = sh.getLastRow() + 1;
      sh.getRange(start, 1, rows.length, rows[0].length).setValues(rows);
      sh.getRange(start, 9, rows.length, 1).insertCheckboxes();
    }
    return out({ ok: true, added: rows.length });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
