"""Write backend/samples/sample-gem-bid.pdf by hand (no extra packages). Run: python -m backend.samples.make_sample_pdf"""

from pathlib import Path

PAGES = [
    [
        "Bid Number GeM/2026/B/6841207",
        "Supply of 80 Business Laptops for District Offices",
        "Buyer: Office of the Deputy Commissioner, Mandya (synthetic sample)",
        "",
        "Cl. 4.1 Minimum Average Annual Turnover",
        "The average annual turnover of the bidder during the last three financial",
        "years shall be at least Rs. 35 Lakh. A CA certificate with UDIN is required.",
        "",
        "Cl. 4.2 Past Performance",
        "The bidder must have executed at least 2 similar orders each of value not",
        "less than Rs. 12 Lakh in the last three years to Government buyers.",
    ],
    [
        "Cl. 6.3 OEM Authorisation",
        "The bidder shall submit a valid OEM authorisation certificate from Lenovo",
        "for the offered make and model, addressed to the buyer.",
        "",
        "Cl. 7.1 Earnest Money Deposit",
        "EMD of Rs. 70,000 is payable. MSEs registered for the tendered item as",
        "manufacturers are exempted from EMD. Traders are not eligible for exemption.",
    ],
]


def _escape(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build():
    objs = []  # object bodies, numbered from 1
    n_pages = len(PAGES)
    # 1 catalog, 2 pages, 3 font, then (page, content) pairs
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(PAGES):
        ops = ["BT", "/F1 11 Tf", "14 TL", "56 780 Td"]
        for line in lines:
            ops.append(f"({_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


if __name__ == "__main__":
    path = Path(__file__).with_name("sample-gem-bid.pdf")
    path.write_bytes(build())
    print(path)
