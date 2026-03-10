"""
Generate NRP_ROS_FEATURE_DOCUMENTATION.pdf from the markdown file.
Design: Modern, professional, white/light color palette.
"""

import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether, NextPageTemplate
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ─── Colour Palette ────────────────────────────────────────────────────────────
C_WHITE        = colors.HexColor("#FFFFFF")
C_BG_PAGE      = colors.HexColor("#FFFFFF")
C_ACCENT       = colors.HexColor("#3D7EBF")      # medium professional blue
C_ACCENT_LIGHT = colors.HexColor("#EBF3FB")      # very light blue tint
C_ACCENT_MID   = colors.HexColor("#BDD7EE")      # medium-light blue
C_SECTION_BG   = colors.HexColor("#3D7EBF")      # section header background
C_SECTION_FG   = colors.HexColor("#FFFFFF")      # section header text
C_H3_FG        = colors.HexColor("#2A5F9E")      # subsection heading
C_BODY         = colors.HexColor("#2D2D2D")      # main body text
C_SUBTLE       = colors.HexColor("#6B7A8D")      # muted/caption text
C_TABLE_HEAD   = colors.HexColor("#EBF3FB")      # table header fill
C_TABLE_ALT    = colors.HexColor("#F7FAFD")      # table alternate row fill
C_TABLE_BORDER = colors.HexColor("#C5DAF0")      # table border
C_CODE_BG      = colors.HexColor("#F5F7FA")      # code block background
C_CODE_BORDER  = colors.HexColor("#D8E3EE")      # code block border
C_RULE         = colors.HexColor("#D0E4F4")      # horizontal rule
C_COVER_DARK   = colors.HexColor("#1E3F6E")      # cover title dark blue
C_COVER_BAND   = colors.HexColor("#3D7EBF")      # cover band
C_TAG_BG       = colors.HexColor("#E8F2FB")      # status tag background
C_TAG_FG       = colors.HexColor("#2A5F9E")      # status tag text
C_PENDING_BG   = colors.HexColor("#FFF3E0")      # pending tag background
C_PENDING_FG   = colors.HexColor("#B45309")      # pending tag text

PAGE_W, PAGE_H = A4

# ─── Custom Flowables ──────────────────────────────────────────────────────────

class SectionHeader(Flowable):
    """A full-width section header bar with a number badge and title."""
    HEIGHT = 1.1 * cm

    def __init__(self, number, title, width):
        super().__init__()
        self.number = number
        self.title = title
        self._width = width

    def wrap(self, aW, aH):
        return self._width, self.HEIGHT

    def draw(self):
        c = self.canv
        w, h = self._width, self.HEIGHT

        # Background bar
        c.setFillColor(C_SECTION_BG)
        c.roundRect(0, 0, w, h, 5, fill=1, stroke=0)

        # Number badge (darker pill on the left)
        badge_w = 1.1 * cm
        c.setFillColor(colors.HexColor("#1E3F6E"))
        c.roundRect(0.3 * cm, h * 0.18, badge_w, h * 0.64, 4, fill=1, stroke=0)

        c.setFillColor(C_WHITE)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(0.3 * cm + badge_w / 2, h * 0.33, self.number)

        # Title
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1.7 * cm, h * 0.32, self.title)


class ColoredLine(Flowable):
    """A coloured horizontal rule."""
    def __init__(self, width, color=C_RULE, thickness=0.5):
        super().__init__()
        self._width = width
        self._color = color
        self._thickness = thickness

    def wrap(self, aW, aH):
        return self._width, self._thickness + 2

    def draw(self):
        self.canv.setStrokeColor(self._color)
        self.canv.setLineWidth(self._thickness)
        self.canv.line(0, 0, self._width, 0)


class CoverPage(Flowable):
    """Full cover page with geometric accent bands."""
    def __init__(self, width, height, title, subtitle):
        super().__init__()
        self._width = width
        self._height = height
        self.title = title
        self.subtitle = subtitle

    def wrap(self, aW, aH):
        return self._width, self._height

    def draw(self):
        c = self.canv
        w, h = self._width, self._height

        # White background
        c.setFillColor(C_WHITE)
        c.rect(0, 0, w, h, fill=1, stroke=0)

        # Bottom accent band
        c.setFillColor(C_ACCENT)
        c.rect(0, 0, w, 1.8 * cm, fill=1, stroke=0)

        # Secondary lighter band above
        c.setFillColor(C_ACCENT_LIGHT)
        c.rect(0, 1.8 * cm, w, 0.5 * cm, fill=1, stroke=0)

        # Top accent band
        c.setFillColor(C_ACCENT)
        c.rect(0, h - 2.5 * cm, w, 2.5 * cm, fill=1, stroke=0)

        # Decorative right-side rectangle
        c.setFillColor(C_ACCENT_MID)
        c.rect(w - 1.8 * cm, 2.3 * cm, 1.8 * cm, h - 4.8 * cm, fill=1, stroke=0)

        # Title block area (white card feel – just use background)
        mid_y = h * 0.45

        # Main title
        c.setFillColor(C_COVER_DARK)
        c.setFont("Helvetica-Bold", 36)
        c.drawString(2 * cm, mid_y + 2.0 * cm, "NRP_ROS")

        # Accent line under title
        c.setStrokeColor(C_ACCENT)
        c.setLineWidth(3)
        c.line(2 * cm, mid_y + 1.65 * cm, 10 * cm, mid_y + 1.65 * cm)

        # Subtitle
        c.setFillColor(C_ACCENT)
        c.setFont("Helvetica-Bold", 17)
        c.drawString(2 * cm, mid_y + 0.9 * cm, "Autonomous Rover Control System")

        # Description
        c.setFillColor(C_SUBTLE)
        c.setFont("Helvetica", 10)
        lines = [
            "Navigation & Robotics Platform",
            "Jetson Orin Nano  ·  FastAPI + Socket.IO  ·  ROS2 / MAVROS",
            "RTK GPS  ·  Obstacle Avoidance  ·  Real-time Telemetry",
        ]
        for i, line in enumerate(lines):
            c.drawString(2 * cm, mid_y - 0.1 * cm - i * 0.55 * cm, line)

        # Feature documentation label
        c.setFillColor(C_ACCENT_LIGHT)
        c.roundRect(2 * cm, mid_y - 1.9 * cm, 8 * cm, 0.85 * cm, 4, fill=1, stroke=0)
        c.setFillColor(C_ACCENT)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2.4 * cm, mid_y - 1.56 * cm, "FEATURE DOCUMENTATION  ·  February 2026")

        # Bottom band text
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, 0.6 * cm, "NRP_ROS  ·  Confidential Technical Reference")
        c.setFont("Helvetica", 9)
        c.drawRightString(w - 2.2 * cm, 0.6 * cm, "Jetson Orin Nano Super")

        # Top band text
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, h - 1.5 * cm, "NRP — Navigation & Robotics Platform")


# ─── Styles ───────────────────────────────────────────────────────────────────

def make_styles():
    s = {}

    s["body"] = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=C_BODY,
        spaceAfter=4,
    )
    s["body_small"] = ParagraphStyle(
        "body_small",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=C_BODY,
        spaceAfter=3,
    )
    s["h2"] = ParagraphStyle(
        "h2",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=18,
        textColor=C_H3_FG,
        spaceBefore=10,
        spaceAfter=6,
    )
    s["h3"] = ParagraphStyle(
        "h3",
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=15,
        textColor=C_H3_FG,
        spaceBefore=8,
        spaceAfter=4,
        leftIndent=2,
    )
    s["code"] = ParagraphStyle(
        "code",
        fontName="Courier",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#3A4A5C"),
        leftIndent=6,
        spaceAfter=2,
    )
    s["bullet"] = ParagraphStyle(
        "bullet",
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=C_BODY,
        leftIndent=14,
        firstLineIndent=-8,
        spaceAfter=2,
        bulletIndent=6,
    )
    s["caption"] = ParagraphStyle(
        "caption",
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=C_SUBTLE,
        spaceAfter=4,
        alignment=TA_CENTER,
    )
    s["toc_title"] = ParagraphStyle(
        "toc_title",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=26,
        textColor=C_COVER_DARK,
        spaceAfter=6,
        spaceBefore=4,
    )
    s["toc_entry"] = ParagraphStyle(
        "toc_entry",
        fontName="Helvetica",
        fontSize=10,
        leading=16,
        textColor=C_BODY,
        leftIndent=12,
    )
    s["toc_entry_pending"] = ParagraphStyle(
        "toc_entry_pending",
        fontName="Helvetica-Oblique",
        fontSize=10,
        leading=16,
        textColor=C_SUBTLE,
        leftIndent=12,
    )
    return s


# ─── Helpers ──────────────────────────────────────────────────────────────────

def clean_md(text):
    """Strip markdown bold/italic markers for plain text rendering."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text.strip()


def rich_para(text, style):
    """Return a Paragraph with bold/code inline markup converted."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
    text = text.replace('&', '&amp;').replace('<b>', '<b>').replace('</b>', '</b>')
    # Re-apply after entity escaping (simple guard)
    return Paragraph(text, style)


def status_cell(text):
    """Render status text with a subtle colored background tag look."""
    text = clean_md(text)
    if "Pending" in text or "pending" in text:
        return Paragraph(
            f'<font color="#B45309"><b>{text}</b></font>',
            ParagraphStyle("sc", fontName="Helvetica-Bold", fontSize=8.5,
                           textColor=C_PENDING_FG, leading=12)
        )
    if "Complete" in text or "complete" in text:
        return Paragraph(
            f'<font color="#1A6E3C"><b>{text}</b></font>',
            ParagraphStyle("sc", fontName="Helvetica-Bold", fontSize=8.5,
                           textColor=colors.HexColor("#1A6E3C"), leading=12)
        )
    return Paragraph(text, ParagraphStyle("sc", fontName="Helvetica", fontSize=8.5,
                                          textColor=C_BODY, leading=12))


def build_table(headers, rows, col_widths, avail_w):
    """Build a styled reportlab Table from parsed markdown table data."""
    styles_p = make_styles()
    small = styles_p["body_small"]

    # Scale col widths to fill available width
    total = sum(col_widths)
    scale = avail_w / total if total > 0 else 1.0
    col_widths = [w * scale for w in col_widths]

    def cell(text, is_header=False, is_status=False):
        text = text.strip()
        if is_header:
            return Paragraph(
                f'<b>{clean_md(text)}</b>',
                ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9,
                               textColor=C_COVER_DARK, leading=12)
            )
        if is_status:
            return status_cell(text)
        # Detect bold
        if '**' in text or '`' in text:
            return rich_para(clean_md(text.replace('**', '')), small)
        return Paragraph(clean_md(text), small)

    # Determine which column index might be "status" by header name
    status_idx = None
    for i, h in enumerate(headers):
        if h.strip().lower() in ("status", "state"):
            status_idx = i

    tdata = []
    # Header row
    tdata.append([cell(h, is_header=True) for h in headers])

    for row in rows:
        # Pad/trim row to header length
        while len(row) < len(headers):
            row.append("")
        row = row[:len(headers)]
        tdata.append([
            cell(row[i], is_status=(i == status_idx))
            for i in range(len(headers))
        ])

    # TableStyle
    ts = [
        # Header
        ("BACKGROUND",  (0, 0), (-1, 0),  C_TABLE_HEAD),
        ("LINEBELOW",   (0, 0), (-1, 0),  1.0, C_ACCENT_MID),
        ("TOPPADDING",  (0, 0), (-1, 0),  6),
        ("BOTTOMPADDING",(0,0), (-1, 0),  6),
        # All cells
        ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
        ("TOPPADDING",  (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING",(0,1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",(0, 0), (-1, -1), 7),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        # Grid
        ("GRID",        (0, 0), (-1, -1), 0.4, C_TABLE_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_TABLE_ALT]),
    ]
    t = Table(tdata, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(ts))
    return t


def heuristic_col_widths(headers):
    """Guess column widths based on header names."""
    widths = []
    for h in headers:
        h_l = h.strip().lower()
        if h_l in ("feature", "topic/service", "topic", "service", "endpoint", "event", "component"):
            widths.append(3.5)
        elif h_l in ("technical details", "purpose", "details"):
            widths.append(5.0)
        elif h_l in ("status",):
            widths.append(1.8)
        elif h_l in ("last modified", "data", "value", "meaning", "zone", "range", "action",
                     "color", "state", "interface"):
            widths.append(2.0)
        else:
            widths.append(2.8)
    return widths


# ─── Markdown Parser → Story ──────────────────────────────────────────────────

def parse_md_to_story(md_text, avail_w):
    story = []
    styles = make_styles()

    lines = md_text.splitlines()
    i = 0
    section_counter = 0

    # Section number → title map for TOC
    toc_entries = []

    # First pass: collect section info for TOC
    for line in lines:
        m = re.match(r'^#{1,2}\s+(.+)', line)
        if m and line.startswith("## "):
            toc_entries.append(m.group(1).strip())

    # ── TOC ──────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Contents", styles["toc_title"]))
    story.append(ColoredLine(avail_w, C_ACCENT, 2))
    story.append(Spacer(1, 0.4 * cm))

    toc_sections = [
        ("System Architecture", False),
        ("FastAPI Server", False),
        ("MAVROS Integration", False),
        ("Mission Controller", False),
        ("Manual Control (Virtual Joystick)", False),
        ("RTK GPS & LoRa Corrections", False),
        ("GPS Failsafe Monitor", False),
        ("Obstacle Detection (Ultrasonic)", False),
        ("LED Feedback System (WS2812)", False),
        ("Text-to-Speech (TTS)", False),
        ("Telemetry Aggregation", False),
        ("Network Monitoring", False),
        ("Socket.IO API", False),
        ("REST API Endpoints", False),
        ("Hardware Summary", False),
        ("Pending Features", True),
    ]
    for idx, (title, pending) in enumerate(toc_sections, 1):
        num_str = f"{idx:02d}."
        st = styles["toc_entry_pending"] if pending else styles["toc_entry"]
        label = f'<font color="#6B7A8D">{num_str}</font>  {title}'
        if pending:
            label += '  <font color="#B45309" size="8"><i>(Pending)</i></font>'
        story.append(Paragraph(label, st))

    story.append(PageBreak())

    # ── Main parse ────────────────────────────────────────────────────────────
    in_code = False
    code_buf = []
    in_table = False
    table_headers = []
    table_rows = []

    code_style_bg = ParagraphStyle(
        "code_bg",
        fontName="Courier",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#3A4A5C"),
        leftIndent=10,
        rightIndent=6,
        spaceBefore=0,
        spaceAfter=0,
        backColor=C_CODE_BG,
    )

    def flush_code():
        nonlocal code_buf
        if not code_buf:
            return []
        result = []

        # Top border line (thin accent bar)
        result.append(ColoredLine(avail_w, C_CODE_BORDER, 0.8))
        result.append(Spacer(1, 3))

        # Each code line as its own paragraph – allows page breaks inside block
        for cl in code_buf:
            cl_safe = cl.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if not cl_safe.strip():
                result.append(Spacer(1, 3))
            else:
                result.append(Paragraph(cl_safe, code_style_bg))

        result.append(Spacer(1, 3))
        result.append(ColoredLine(avail_w, C_CODE_BORDER, 0.8))
        result.append(Spacer(1, 0.25 * cm))
        code_buf = []
        return result

    def flush_table():
        nonlocal table_headers, table_rows, in_table
        result = []
        if table_headers and table_rows:
            # Filter out separator rows (---|---...)
            real_rows = [r for r in table_rows if not all(
                re.match(r'^[-: ]+$', c.strip()) for c in r if c.strip()
            )]
            if real_rows:
                cws = heuristic_col_widths(table_headers)
                result.append(build_table(table_headers, real_rows, cws, avail_w))
                result.append(Spacer(1, 0.25 * cm))
        table_headers = []
        table_rows = []
        in_table = False
        return result

    while i < len(lines):
        line = lines[i]

        # ── Code fences ───────────────────────────────────────────────────────
        if line.strip().startswith("```"):
            if in_code:
                story.extend(flush_code())
                in_code = False
            else:
                if in_table:
                    story.extend(flush_table())
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # ── Table rows ────────────────────────────────────────────────────────
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not in_table:
                # First row = headers
                table_headers = cells
                in_table = True
            else:
                table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                story.extend(flush_table())

        # ── Headings ──────────────────────────────────────────────────────────
        if line.startswith("# ") and not line.startswith("## "):
            # H1 → skip (used as cover title)
            i += 1
            continue

        if line.startswith("## "):
            section_counter += 1
            title_text = line[3:].strip()
            # Remove numbering like "1. " or "15. "
            title_clean = re.sub(r'^\d+\.\s+', '', title_text)
            num_str = f"{section_counter:02d}"
            story.append(Spacer(1, 0.3 * cm))
            story.append(SectionHeader(num_str, title_clean, avail_w))
            story.append(Spacer(1, 0.25 * cm))
            i += 1
            continue

        if line.startswith("### "):
            title_text = line[4:].strip()
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(clean_md(title_text), styles["h3"]))
            i += 1
            continue

        # ── Horizontal rules ──────────────────────────────────────────────────
        if re.match(r'^---+$', line.strip()):
            story.append(Spacer(1, 0.1 * cm))
            story.append(ColoredLine(avail_w, C_RULE, 0.5))
            story.append(Spacer(1, 0.15 * cm))
            i += 1
            continue

        # ── Bullet points ─────────────────────────────────────────────────────
        if line.strip().startswith("- ") or line.strip().startswith("* "):
            bullet_text = line.strip()[2:].strip()
            bullet_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', bullet_text)
            bullet_text = re.sub(r'`(.+?)`',
                                 r'<font name="Courier">\1</font>', bullet_text)
            story.append(Paragraph(f'<bullet>•</bullet>{bullet_text}',
                                   styles["bullet"]))
            i += 1
            continue

        # ── Bold "Achieves" / "Commands" standalone lines ─────────────────────
        if line.strip().startswith("**") and line.strip().endswith("**"):
            inner = line.strip()[2:-2]
            story.append(Paragraph(f'<b>{clean_md(inner)}</b>', styles["h3"]))
            i += 1
            continue

        # ── Regular paragraph / achieves text ─────────────────────────────────
        if line.strip():
            text = line.strip()
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
            story.append(Paragraph(text, styles["body"]))
            i += 1
            continue

        # ── Blank lines → small spacer ────────────────────────────────────────
        story.append(Spacer(1, 0.05 * cm))
        i += 1

    # Flush any remaining
    if in_code:
        story.extend(flush_code())
    if in_table:
        story.extend(flush_table())

    return story


# ─── Page Template ────────────────────────────────────────────────────────────

def on_cover_page(canvas, doc):
    """No header/footer on cover page."""
    pass


def on_content_page(canvas, doc):
    """Draw header/footer on content pages."""
    w, h = A4
    margin = 1.8 * cm
    pn = doc.page  # page 1 = cover, page 2 = TOC, etc.

    # Header bar
    canvas.setFillColor(C_ACCENT_LIGHT)
    canvas.rect(0, h - 1.2 * cm, w, 1.2 * cm, fill=1, stroke=0)
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, h - 1.2 * cm, w, 0.18 * cm, fill=1, stroke=0)
    canvas.setFillColor(C_SUBTLE)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(margin, h - 0.80 * cm, "NRP_ROS — Feature Documentation")
    canvas.drawRightString(w - margin, h - 0.80 * cm, "Navigation & Robotics Platform")

    # Footer rule + page number
    canvas.setStrokeColor(C_RULE)
    canvas.setLineWidth(0.5)
    canvas.line(margin, 1.2 * cm, w - margin, 1.2 * cm)
    canvas.setFillColor(C_SUBTLE)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(w / 2, 0.75 * cm, f"— {pn - 1} —")
    canvas.drawString(margin, 0.75 * cm, "Confidential Technical Reference  ·  Feb 2026")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    INPUT_MD = "/home/flash/NRP_ROS/NRP_ROS_FEATURE_DOCUMENTATION.md"
    OUTPUT   = "/home/flash/NRP_ROS/docs/NRP_ROS_FEATURE_DOCUMENTATION.pdf"

    with open(INPUT_MD, "r", encoding="utf-8") as f:
        md_text = f.read()

    # Page geometry
    L_MARGIN = R_MARGIN = 1.8 * cm
    T_MARGIN = 1.6 * cm
    B_MARGIN = 1.8 * cm
    avail_w = PAGE_W - L_MARGIN - R_MARGIN

    # Build a BaseDocTemplate with two page templates:
    #   "cover"   – full-bleed frame (no margins) for the cover page
    #   "content" – normal margins + header/footer for all other pages

    cover_frame = Frame(
        0, 0, PAGE_W, PAGE_H,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="cover_frame",
    )
    content_frame = Frame(
        L_MARGIN,
        B_MARGIN + 0.6 * cm,
        PAGE_W - L_MARGIN - R_MARGIN,
        PAGE_H - T_MARGIN - 1.2 * cm - B_MARGIN - 0.6 * cm,
        leftPadding=0, rightPadding=0, topPadding=4, bottomPadding=4,
        id="content_frame",
    )

    cover_template   = PageTemplate(id="cover",   frames=[cover_frame],
                                    onPage=on_cover_page)
    content_template = PageTemplate(id="content", frames=[content_frame],
                                    onPage=on_content_page)

    doc = BaseDocTemplate(
        OUTPUT,
        pagesize=A4,
        pageTemplates=[cover_template, content_template],
        title="NRP_ROS Feature Documentation",
        author="NRP Engineering",
        subject="Autonomous Rover Control System",
    )

    story = []

    # Cover page on the "cover" template
    story.append(NextPageTemplate("content"))
    story.append(CoverPage(PAGE_W, PAGE_H, "NRP_ROS", "Feature Documentation"))

    # All content pages on the "content" template
    story.extend(parse_md_to_story(md_text, avail_w))

    doc.build(story)
    print(f"PDF created: {OUTPUT}")


if __name__ == "__main__":
    main()
