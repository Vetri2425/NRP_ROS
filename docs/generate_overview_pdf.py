from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

OUTPUT = "/home/flash/NRP_ROS/docs/APPLICATION_OVERVIEW.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=3*cm,
    rightMargin=3*cm,
    topMargin=3*cm,
    bottomMargin=3*cm,
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "MainTitle",
    fontSize=24,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1a1a2e"),
    spaceAfter=0.4*cm,
    alignment=1,
)

subtitle_style = ParagraphStyle(
    "SubTitle",
    fontSize=11,
    fontName="Helvetica",
    textColor=colors.HexColor("#555555"),
    spaceAfter=1.5*cm,
    alignment=1,
)

divider_style = ParagraphStyle(
    "Divider",
    fontSize=10,
    fontName="Helvetica",
    textColor=colors.HexColor("#cccccc"),
    spaceAfter=1.2*cm,
    alignment=1,
)

section_style = ParagraphStyle(
    "Section",
    fontSize=14,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1a1a2e"),
    spaceAfter=0.5*cm,
    spaceBefore=0.2*cm,
    leftIndent=0.5*cm,
    borderPad=0.3*cm,
    leading=22,
)

sections = [
    ("01", "System Architecture"),
    ("02", "FastAPI Server"),
    ("03", "MAVROS Complete Implementation"),
    ("04", "Mission Controller"),
    ("05", "Manual Control (Virtual Joystick)"),
    ("06", "RTK GPS & LoRa Corrections"),
    ("07", "GPS Failsafe Monitor"),
    ("08", "Obstacle Detection (Ultrasonic)"),
    ("09", "LED Feedback System (WS2812)"),
    ("10", "Text-to-Speech (TTS)"),
    ("11", "Telemetry Aggregation"),
    ("12", "Network Monitoring"),
    ("13", "Socket.IO API Documentation"),
    ("14", "Hardware Summary"),
    ("15", "Startup & Service Management"),
    ("16", "REST API Endpoints"),
    ("17", "Socket.IO Events"),
]

story = []

story.append(Spacer(1, 1*cm))
story.append(Paragraph("NRP_ROS", title_style))
story.append(Paragraph("Application Overview", subtitle_style))
story.append(Paragraph("─" * 55, divider_style))
story.append(Spacer(1, 0.5*cm))

for num, title in sections:
    story.append(Paragraph(f'<font color="#888888">{num} &nbsp;&nbsp;</font>{title}', section_style))

doc.build(story)
print(f"PDF created: {OUTPUT}")
