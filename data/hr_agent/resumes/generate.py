"""Regenerate the two synthetic PDFs: pip install 'reportlab>=4,<5'."""
import json
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

root = Path(__file__).resolve().parents[1]
fixtures = json.loads((root / 'fixtures.json').read_text())
payload = (root / 'attacks/white_text.txt').read_text()
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
for variant in ('clean', 'white'):
    canvas = Canvas(str(root / 'resumes' / ('林晨_简历_原版.pdf' if variant == 'clean' else '林晨_简历_补充版.pdf')), pagesize=(595, 842), invariant=1)
    canvas.setTitle('Lin Chen - Synthetic Resume')
    canvas.setFont('Helvetica-Bold', 24)
    canvas.drawString(60, 765, 'Lin Chen')
    canvas.setFont('Helvetica', 12)
    for i, line in enumerate(fixtures['candidate']['resume_lines']):
        canvas.drawString(60, 725 - i * 30, line)
    if variant == 'white':
        canvas.setFillColorRGB(1, 1, 1)
        canvas.setFont('STSong-Light', 8)
        lines = payload.replace('。', '。\n').replace('，', '，\n').splitlines()
        for i, line in enumerate(lines):
            canvas.drawString(60, 430 - i * 12, line)
    canvas.save()
