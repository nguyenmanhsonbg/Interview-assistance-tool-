# Bundled Poppler extractor

This directory contains the Windows Poppler runtime used by ClawCV to extract
text from native-text PDF files without requiring a machine-wide installation.

- Version: 25.07.0
- Entry point: `Library/bin/pdftotext.exe`
- Configuration: `.env` → `PDF_TEXT_EXTRACTOR_PATH`

The DLLs are kept beside `pdftotext.exe` so the extractor can run from a
portable copy of the repository. See the files under `share/poppler/` for the
upstream license notices included with this bundle.

Scanned/image-only PDFs still require OCR and are outside the current MVP.
