from django.template.loader import render_to_string


def prescription_pdf(prescription) -> bytes:
    """Shared by the staff download and the patient's Telegram bot."""
    # Imported lazily: WeasyPrint needs system libraries that only the PDF path uses.
    from weasyprint import HTML

    html = render_to_string(
        "prescription_pdf.html",
        {"prescription": prescription, "clinic": prescription.clinic, "items": prescription.items.all()},
    )
    return HTML(string=html).write_pdf()
