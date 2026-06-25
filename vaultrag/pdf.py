"""
PDF 解析 — pdfplumber 表格感知 + PyMuPDF 回退
"""
from .config import VAULT_DIR


def read_pdf(filepath: str) -> str | None:
    """读取 PDF，优先 pdfplumber（保留表格），回退 PyMuPDF"""
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
                for table in page.extract_tables():
                    if not table:
                        continue
                    lines = []
                    for ri, row in enumerate(table):
                        cells = [str(c).replace("\n", " ") if c else "" for c in row]
                        lines.append("| " + " | ".join(cells) + " |")
                        if ri == 0:
                            lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
                    parts.append("\n".join(lines))
        return "\n\n".join(parts)
    except ImportError:
        pass

    # 回退 PyMuPDF
    try:
        import fitz
        doc = fitz.open(filepath)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        raise ImportError("需要 pdfplumber 或 PyMuPDF 来解析 PDF: pip install pdfplumber")


def read_file(filepath: str) -> str | None:
    """读取支持的文档格式"""
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if ext == "pdf":
        return read_pdf(filepath)
    if ext in ("txt", "md"):
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return None
