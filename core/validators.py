import os
from django.core.exceptions import ValidationError

ALLOWED_DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx']
MAX_DOCUMENT_SIZE_MB = 5
MAX_DOCUMENT_SIZE_BYTES = MAX_DOCUMENT_SIZE_MB * 1024 * 1024


def validate_document_file(file):
    """
    BUG-10: Validates uploaded document files (CVs and offer letters).
    Rules:
    - Allowed extensions: .pdf, .doc, .docx
    - Maximum size: 5 MB (5,242,880 bytes)
    """
    if not file:
        return file

    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        allowed = ", ".join(ALLOWED_DOCUMENT_EXTENSIONS)
        raise ValidationError(
            f"Invalid file extension '{ext}'. Only {allowed} files are allowed."
        )

    if file.size > MAX_DOCUMENT_SIZE_BYTES:
        size_mb = round(file.size / (1024 * 1024), 2)
        raise ValidationError(
            f"File size exceeds the 5 MB limit. Uploaded file is {size_mb} MB."
        )

    return file
