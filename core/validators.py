import os
import zipfile
import xml.etree.ElementTree as ET
from django.core.exceptions import ValidationError

ALLOWED_DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx']
MAX_DOCUMENT_SIZE_MB = 5
MAX_DOCUMENT_SIZE_BYTES = MAX_DOCUMENT_SIZE_MB * 1024 * 1024

# Magic byte signatures
PDF_MAGIC = b'%PDF-'
DOC_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
ZIP_MAGIC = b'PK\x03\x04'

# Maximum uncompressed size limits for internal XML entries to prevent ZIP bomb denial-of-service
# Standard academic documents have [Content_Types].xml of a few KB and word/document.xml of < 1MB.
# Limits of 1 MB for content types and 10 MB for document XML allow large legitimate documents
# while protecting memory from malicious decompressive explosions.
MAX_CONTENT_TYPES_XML_BYTES = 1 * 1024 * 1024   # 1 MB
MAX_DOCUMENT_XML_BYTES = 10 * 1024 * 1024        # 10 MB


def validate_document_file(file):
    """
    BUG-10 & Phase 4: Validates uploaded document files (CVs and offer letters).
    Rules:
    - Allowed extensions: .pdf, .doc, .docx
    - Maximum size: 5 MB (5,242,880 bytes)
    - Content validation:
        * .pdf: starts with b'%PDF-'
        * .doc: starts with b'\\xd0\\xcf\\x11\\xe0\\xa1\\xb1\\x1a\\xe1' (OLE Compound File)
        * .docx: starts with b'PK\\x03\\x04' and contains valid ZIP structure with
                 valid XML in '[Content_Types].xml' and 'word/document.xml'
        * uncompressed entry size checked before reading to defend against ZIP bomb attacks.
    - Content/extension mismatch, malformed archives, and oversized entries are rejected.
    - File pointer is always restored (seek(0)).
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

    try:
        file.seek(0)
        header = file.read(8)

        if ext == '.pdf':
            if not header.startswith(PDF_MAGIC):
                raise ValidationError("Invalid PDF file content. The file does not have a valid PDF header.")
        elif ext == '.doc':
            if not header.startswith(DOC_MAGIC):
                raise ValidationError("Invalid Word (.doc) file content. The file does not have a valid Microsoft Compound Document header.")
        elif ext == '.docx':
            if not header.startswith(ZIP_MAGIC):
                raise ValidationError("Invalid Word (.docx) file content. The file is not a valid Office Open XML document.")
            file.seek(0)
            try:
                with zipfile.ZipFile(file) as zf:
                    namelist = zf.namelist()
                    if '[Content_Types].xml' not in namelist or 'word/document.xml' not in namelist:
                        raise ValidationError("Invalid Word (.docx) file structure. Missing required document components.")

                    # Inspect uncompressed entry sizes before reading to guard against ZIP bombs
                    try:
                        ct_info = zf.getinfo('[Content_Types].xml')
                        doc_info = zf.getinfo('word/document.xml')
                    except KeyError:
                        raise ValidationError("Invalid Word (.docx) file structure. Missing required document components.")

                    if ct_info.file_size > MAX_CONTENT_TYPES_XML_BYTES:
                        raise ValidationError("Invalid Word (.docx) file content. Internal package metadata exceeds allowable size limit.")

                    if doc_info.file_size > MAX_DOCUMENT_XML_BYTES:
                        raise ValidationError("Invalid Word (.docx) file content. Internal document structure exceeds allowable size limit.")

                    # Parse required XML entries in-memory to reject malformed XML
                    try:
                        content_types_data = zf.read('[Content_Types].xml')
                        ET.fromstring(content_types_data)
                        doc_xml_data = zf.read('word/document.xml')
                        ET.fromstring(doc_xml_data)
                    except (ET.ParseError, Exception):
                        raise ValidationError("Invalid Word (.docx) file content. Malformed document XML structure.")
            except zipfile.BadZipFile:
                raise ValidationError("Invalid Word (.docx) file content. Corrupted or malformed archive.")
    finally:
        file.seek(0)

    return file
