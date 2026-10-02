"""Render a :class:`TailoredResume` into a PDF that mirrors the candidate's own
layout (measured from their resume: A4, single column, Selawik, the sizes,
colours, margins and section rules below).

A small cursor-based layout engine on the canvas, rather than Platypus, keeps
exact control over the two things the template needs: a title on the left with a
muted date on the right of the same line, and section labels in tracked small
caps over a full-width rule. Text wraps by measuring glyph widths, and the page
breaks on its own when the cursor runs past the bottom margin.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from pipeline.resume_tailor.schema import Entry, TailoredResume

_FONTS_DIR = Path(__file__).parent / "fonts"
FONT_REGULAR = "Selawik"
FONT_SEMIBOLD = "Selawik-SB"
FONT_BOLD = "Selawik-Bold"

_registered = False
_register_lock = threading.Lock()

# Colours measured from the source resume.
INK = HexColor("#2f3a34")  # name, entry titles, skill labels
BODY = HexColor("#3f4d47")  # summary, bullets, headline
MUTED = HexColor("#8a8578")  # contacts, section labels, dates, subtitles
RULE = HexColor("#d6d3ca")  # section underline

PAGE_W, PAGE_H = A4  # 595.27 x 841.89 pt
M_LEFT = 43.0
M_RIGHT = 41.0
M_TOP = 32.0
M_BOTTOM = 44.0
CONTENT_W = PAGE_W - M_LEFT - M_RIGHT
RIGHT_X = PAGE_W - M_RIGHT

# Type scale measured from the source resume.
NAME_SIZE = 18.0
HEADLINE_SIZE = 11.2
CONTACT_SIZE = 9.8
SECTION_SIZE = 8.2
BODY_SIZE = 10.5
TITLE_SIZE = 10.9
META_SIZE = 9.8
BODY_LEADING = BODY_SIZE * 1.34
SECTION_TRACKING = 1.4  # letter spacing on the small-caps section labels

BULLET_MARK_X = M_LEFT + 6.0
BULLET_TEXT_X = M_LEFT + 20.0


def register_fonts() -> None:
    """Register the Selawik faces once (safe to call from many threads)."""
    global _registered
    if _registered:
        return
    with _register_lock:
        if _registered:
            return
        pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(_FONTS_DIR / "Selawik-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(FONT_SEMIBOLD, str(_FONTS_DIR / "Selawik-Semibold.ttf")))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(_FONTS_DIR / "Selawik-Bold.ttf")))
        _registered = True


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    """Greedy word wrap by measured glyph width; never drops a word."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and pdfmetrics.stringWidth(candidate, font, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


class _Cursor:
    """A top-down writing position that opens new pages as it fills them."""

    def __init__(self, canvas: Canvas) -> None:
        self.c = canvas
        self.y = PAGE_H - M_TOP

    def _ensure(self, needed: float) -> None:
        if self.y - needed < M_BOTTOM:
            self.c.showPage()
            self.y = PAGE_H - M_TOP

    def space(self, amount: float) -> None:
        self.y -= amount

    def paragraph(
        self,
        text: str,
        font: str,
        size: float,
        color: HexColor,
        *,
        x: float = M_LEFT,
        max_width: float = CONTENT_W,
        leading: float | None = None,
        centered: bool = False,
    ) -> None:
        if not text:
            return
        leading = leading or size * 1.34
        lines = _wrap(text, font, size, max_width)
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        for line in lines:
            self._ensure(leading)
            if centered:
                self.c.drawCentredString(PAGE_W / 2, self.y - size, line)
            else:
                self.c.drawString(x, self.y - size, line)
            self.y -= leading

    def section(self, label: str) -> None:
        """Tracked small-caps label over a full-width rule."""
        self._ensure(SECTION_SIZE + 10)
        # save/restore so the tracking (a PDF text-state Tc) does not leak into
        # the body text that follows.
        self.c.saveState()
        text = self.c.beginText(M_LEFT, self.y - SECTION_SIZE)
        text.setFont(FONT_SEMIBOLD, SECTION_SIZE)
        text.setFillColor(MUTED)
        text.setCharSpace(SECTION_TRACKING)
        text.textOut(label.upper())
        self.c.drawText(text)
        self.c.restoreState()
        rule_y = self.y - SECTION_SIZE - 4.5
        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.8)
        self.c.line(M_LEFT, rule_y, RIGHT_X, rule_y)
        self.y = rule_y - 8.0

    def title_row(self, title: str, meta: str) -> None:
        """Bold title on the left, muted meta flush right on the same baseline."""
        self._ensure(TITLE_SIZE * 1.3)
        baseline = self.y - TITLE_SIZE
        if meta:
            self.c.setFont(FONT_REGULAR, META_SIZE)
            self.c.setFillColor(MUTED)
            self.c.drawRightString(RIGHT_X, baseline, meta)
        meta_w = pdfmetrics.stringWidth(meta, FONT_REGULAR, META_SIZE) + 10 if meta else 0
        title_lines = _wrap(title, FONT_BOLD, TITLE_SIZE, CONTENT_W - meta_w)
        self.c.setFont(FONT_BOLD, TITLE_SIZE)
        self.c.setFillColor(INK)
        self.c.drawString(M_LEFT, baseline, title_lines[0])
        self.y -= TITLE_SIZE * 1.32
        for extra in title_lines[1:]:
            self.paragraph(extra, FONT_BOLD, TITLE_SIZE, INK)

    def bullet(self, text: str) -> None:
        leading = BODY_LEADING
        lines = _wrap(text, FONT_REGULAR, BODY_SIZE, RIGHT_X - BULLET_TEXT_X)
        self.c.setFont(FONT_REGULAR, BODY_SIZE)
        self.c.setFillColor(BODY)
        for index, line in enumerate(lines):
            self._ensure(leading)
            baseline = self.y - BODY_SIZE
            if index == 0:
                self.c.setFillColor(MUTED)
                self.c.drawString(BULLET_MARK_X, baseline, "•")
                self.c.setFillColor(BODY)
            self.c.drawString(BULLET_TEXT_X, baseline, line)
            self.y -= leading


def _entry(cur: _Cursor, entry: Entry) -> None:
    cur.title_row(entry.title, entry.meta)
    if entry.subtitle:
        cur.paragraph(entry.subtitle, FONT_REGULAR, META_SIZE, MUTED, leading=META_SIZE * 1.3)
    cur.space(2.0)
    for line in entry.bullets:
        cur.bullet(line)
    cur.space(8.0)


def _entries_section(cur: _Cursor, label: str, entries: list[Entry]) -> None:
    if not entries:
        return
    cur.section(label)
    for entry in entries:
        _entry(cur, entry)


def render_pdf(resume: TailoredResume) -> bytes:
    """Render the tailored resume to PDF bytes."""
    register_fonts()
    buffer = io.BytesIO()
    c = Canvas(buffer, pagesize=A4)
    c.setTitle(resume.name or "Curriculo")
    cur = _Cursor(c)

    # Header (centred): name, headline, contact lines.
    if resume.name:
        cur.paragraph(
            resume.name, FONT_BOLD, NAME_SIZE, INK, centered=True, leading=NAME_SIZE * 1.2
        )
    if resume.headline:
        cur.space(2.0)
        cur.paragraph(resume.headline, FONT_SEMIBOLD, HEADLINE_SIZE, BODY, centered=True)
    if resume.contact_lines:
        cur.space(2.0)
        for line in resume.contact_lines:
            cur.paragraph(
                line, FONT_REGULAR, CONTACT_SIZE, MUTED, centered=True, leading=CONTACT_SIZE * 1.4
            )
    cur.space(14.0)

    if resume.summary:
        cur.section("SUMMARY")
        cur.paragraph(resume.summary, FONT_REGULAR, BODY_SIZE, BODY, leading=BODY_LEADING)
        cur.space(10.0)

    if resume.skills:
        cur.section("SKILLS")
        for group in resume.skills:
            label = f"{group.label}: "
            label_w = pdfmetrics.stringWidth(label, FONT_SEMIBOLD, BODY_SIZE)
            baseline_lines = _wrap(
                ", ".join(group.items), FONT_REGULAR, BODY_SIZE, CONTENT_W - label_w
            )
            cur._ensure(BODY_LEADING)
            baseline = cur.y - BODY_SIZE
            c.setFont(FONT_SEMIBOLD, BODY_SIZE)
            c.setFillColor(INK)
            c.drawString(M_LEFT, baseline, label)
            c.setFont(FONT_REGULAR, BODY_SIZE)
            c.setFillColor(BODY)
            c.drawString(M_LEFT + label_w, baseline, baseline_lines[0])
            cur.y -= BODY_LEADING
            for extra in baseline_lines[1:]:
                cur.paragraph(extra, FONT_REGULAR, BODY_SIZE, BODY, leading=BODY_LEADING)
            cur.space(3.0)
        cur.space(7.0)

    _entries_section(cur, "PROFESSIONAL EXPERIENCE", resume.experience)
    _entries_section(cur, "PROJECTS", resume.projects)
    _entries_section(cur, "EDUCATION", resume.education)

    if resume.languages:
        cur.section("LANGUAGES")
        cur.paragraph(resume.languages, FONT_REGULAR, BODY_SIZE, BODY, leading=BODY_LEADING)

    c.showPage()
    c.save()
    return buffer.getvalue()
