// Google Apps Script: receives the daily jobs and tailored resumes.
// - Appends jobs to a "Daily Jobs" tab
// - Saves each resume PDF in a Drive folder called "Job Radar Resumes" and links it in the sheet
// 1. Keep SECRET the same as before (it must match the SHEET_TOKEN GitHub secret).
// 2. Deploy > Manage deployments > pencil icon > Version: New version > Deploy (the web app URL stays the same).
const SECRET = "CHANGE_ME_TO_A_LONG_RANDOM_STRING";
const HEADER = ["Date", "Company", "Role", "Location", "Apply link", "Source", "Keyword match", "Link check",
  "Resume fit (AI)", "Gaps to consider", "Tailored resume", "Applied?"];

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.token !== SECRET) return out({ ok: false, error: "bad token" });
    const sh = getSheet_();
    const folder = getFolder_();
    const items = body.items || [];
    const rows = [];
    items.forEach(function (it) {
      const row = it.row.slice();
      if (it.pdf && it.pdf.b64) {
        const blob = Utilities.newBlob(Utilities.base64Decode(it.pdf.b64), "application/pdf", it.pdf.name);
        const file = folder.createFile(blob);
        row[10] = '=HYPERLINK("' + file.getUrl() + '","Open resume")';
      }
      rows.push(row);
    });
    if (rows.length) {
      const start = sh.getLastRow() + 1;
      sh.getRange(start, 1, rows.length, rows[0].length).setValues(rows);
      sh.getRange(start, 12, rows.length, 1).insertCheckboxes();
    }
    return out({ ok: true, added: rows.length });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName("Daily Jobs");
  if (sh && sh.getLastRow() > 0) {
    const existing = sh.getRange(1, 1, 1, HEADER.length).getValues()[0];
    if (existing.join("|") !== HEADER.join("|")) {   // old layout: keep it, start a fresh tab
      sh.setName("Daily Jobs (old " + Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyyMMdd-HHmm") + ")");
      sh = null;
    }
  }
  if (!sh) {
    sh = ss.insertSheet("Daily Jobs");
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEADER.length).setFontWeight("bold");
  }
  return sh;
}

function getFolder_() {
  const it = DriveApp.getFoldersByName("Job Radar Resumes");
  return it.hasNext() ? it.next() : DriveApp.createFolder("Job Radar Resumes");
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
