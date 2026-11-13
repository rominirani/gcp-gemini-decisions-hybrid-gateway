#!/usr/bin/env python3
"""Generates sample_invoice_8812.pdf for testing Stage 03 Multimodal PDF Upload."""

from pathlib import Path


def build_sample_invoice_pdf() -> bytes:
    content = (
        b"BT /F1 14 Tf 50 750 Td (INVOICE #INV-8812 - ACME CLOUD SERVICES) Tj "
        b"0 -30 Td (Customer: Jane Doe | Order Date: 2026-11-05) Tj "
        b"0 -30 Td (Line 1: Pro Plan Monthly Subscription .......... $45.00) Tj "
        b"0 -25 Td (Line 2: Pro Plan Monthly Subscription [DUPLICATE] $45.00) Tj "
        b"0 -30 Td (TOTAL CHARGED TO VISA ENDING 4242: ............ $90.00) Tj ET"
    )
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        ),
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(content)} >> stream\n".encode()
        + content
        + b"\nendstream endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)


if __name__ == "__main__":
    out_path = Path(__file__).parent / "sample_invoice_8812.pdf"
    out_path.write_bytes(build_sample_invoice_pdf())
    print(f"Generated {out_path} ({out_path.stat().st_size} bytes)")
