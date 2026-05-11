from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT_DIR = Path(__file__).resolve().parent.parent
CERTIFICATE_DIR = ROOT_DIR / "data" / "certificates"
QR_DIR = ROOT_DIR / "data" / "qr_codes"


def register_unicode_fonts() -> tuple[str, str]:
    regular = Path("C:/Windows/Fonts/arial.ttf")
    bold = Path("C:/Windows/Fonts/arialbd.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("ArialUnicode", str(regular)))
        pdfmetrics.registerFont(TTFont("ArialUnicode-Bold", str(bold)))
        return "ArialUnicode", "ArialUnicode-Bold"
    return "Helvetica", "Helvetica-Bold"


REGULAR_FONT, BOLD_FONT = register_unicode_fonts()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "certificate"


def generate_certificate_qr(certificate_id: str, verify_url: str) -> Path:
    QR_DIR.mkdir(parents=True, exist_ok=True)
    path = QR_DIR / f"{safe_filename(certificate_id)}.png"
    image = qrcode.make(verify_url)
    image.save(path)
    return path


def build_certificate_pdf(metadata: dict[str, str], qr_path: Path) -> tuple[Path, bytes]:
    CERTIFICATE_DIR.mkdir(parents=True, exist_ok=True)
    certificate_id = metadata["certificate_id"]
    path = CERTIFICATE_DIR / f"{safe_filename(certificate_id)}.pdf"

    buffer = BytesIO()
    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))

    pdf.setStrokeColor(colors.HexColor("#1959a6"))
    pdf.setLineWidth(2)
    pdf.rect(14 * mm, 14 * mm, page_width - 28 * mm, page_height - 28 * mm)

    pdf.setFillColor(colors.HexColor("#1959a6"))
    pdf.setFont(BOLD_FONT, 18)
    pdf.drawCentredString(page_width / 2, page_height - 34 * mm, "DIGITAL CERTIFICATE")

    pdf.setFillColor(colors.HexColor("#17202a"))
    pdf.setFont(REGULAR_FONT, 12)
    pdf.drawCentredString(page_width / 2, page_height - 45 * mm, "Issued and anchored on the local blockchain")

    pdf.setFont(REGULAR_FONT, 14)
    pdf.drawCentredString(page_width / 2, page_height - 66 * mm, "This certifies that")

    pdf.setFont(BOLD_FONT, 30)
    pdf.drawCentredString(page_width / 2, page_height - 84 * mm, metadata["student_name"])

    pdf.setFont(REGULAR_FONT, 14)
    pdf.drawCentredString(page_width / 2, page_height - 102 * mm, "has successfully completed")

    pdf.setFont(BOLD_FONT, 22)
    pdf.drawCentredString(page_width / 2, page_height - 118 * mm, metadata["course_name"])

    pdf.setFont(REGULAR_FONT, 11)
    details = [
        ("Student ID", metadata["student_id"]),
        ("Certificate ID", certificate_id),
        ("Issued at", metadata["issued_at"]),
        ("Issuer", metadata["issuer"]),
    ]
    x = 42 * mm
    y = 50 * mm
    for label, value in details:
        pdf.setFillColor(colors.HexColor("#667085"))
        pdf.drawString(x, y, f"{label}:")
        pdf.setFillColor(colors.HexColor("#17202a"))
        pdf.drawString(x + 30 * mm, y, value)
        y -= 8 * mm

    pdf.drawImage(str(qr_path), page_width - 58 * mm, 30 * mm, width=34 * mm, height=34 * mm)
    pdf.setFont(REGULAR_FONT, 8)
    pdf.setFillColor(colors.HexColor("#667085"))
    pdf.drawCentredString(page_width - 41 * mm, 25 * mm, "Scan to verify")

    pdf.showPage()
    pdf.save()

    data = buffer.getvalue()
    path.write_bytes(data)
    return path, data
