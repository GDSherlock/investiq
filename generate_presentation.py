"""Generate InvestIQ presentation PDF with screenshots and storyline."""

from fpdf import FPDF
from PIL import Image
import os

SCREENSHOTS_DIR = "C:/projects/new-infra-proj/screenshots"
OUTPUT_PATH = "C:/projects/new-infra-proj/InvestIQ_Presentation.pdf"

# Slide definitions: (image_file, title, bullets)
SLIDES = [
    # Title slide (no image)
    (None, None, None),

    # Login
    ("00_login.png", "Secure Authentication", [
        "Role-based access with email/password authentication",
        "Demo accounts available for quick onboarding",
        "Session management with JWT tokens",
        "Supports multiple user roles across the organization",
    ]),

    # Upload & Model Health
    ("01_upload.png", "Model Upload & Health Check", [
        "Drag-and-drop Excel financial model upload (.xlsx)",
        "Automatic parsing of 11 sheet types with smart sheet-name aliasing",
        "Instant health score (0-100) assessing model completeness",
        "63 assumptions extracted and mapped automatically",
        "AI vectorization: model data is embedded for RAG-powered Q&A",
    ]),

    # Dashboard
    ("02_dashboard.png", "Executive Dashboard — Overview", [
        "At-a-glance KPIs: IRR (12.3%), NPV ($145M), DSCR (1.45x), Payback (9.2yr)",
        "Decision Confidence score with go/no-go signal",
        "Persona-aware: view adapts to Investment Manager, CFO, Board Director, etc.",
        "Revenue waterfall, PnL trends, and returns comparison charts",
        "Live assumptions panel with key model drivers",
    ]),

    # Sensitivity
    ("03_sensitivity.png", "Sensitivity Analysis", [
        "One-way tornado chart: ranks variables by IRR impact",
        "Two-way heat map: WACC vs Throughput Fee interaction",
        "Real-time scenario sliders: adjust assumptions and see instant IRR/NPV impact",
        "Identifies key risk variables and their breakeven thresholds",
        "AI-generated interpretation tailored to selected persona",
    ]),

    # Cash Flow
    ("04_cashflows.png", "Cash Flow Simulator", [
        "Annual Free Cash Flow chart with J-curve visualization",
        "P10/P50/P90 probability bands from Monte Carlo simulation",
        "NPV distribution histogram showing value-at-risk",
        "DSCR by year vs covenant line — highlights breach risk periods",
        "Cumulative cash flow with payback period tracking",
        "AI-powered cash flow interpretation with risk period analysis",
    ]),

    # Monte Carlo
    ("05_montecarlo.png", "Monte Carlo Simulation Engine", [
        "Configurable 5,000-trial simulation with correlation matrix",
        "Six stochastic variables: Throughput, Utilisation, WACC, Carbon Tax, Capex Overrun, Opex Inflation",
        "Per-variable distribution parameters: mean, std dev, and cross-correlations",
        "Outputs: IRR distribution, NPV histogram, probability of hurdle breach",
        "Powered by NumPy/SciPy with Cholesky decomposition for correlated sampling",
    ]),

    # Monitor
    ("06_monitor.png", "DSCR Covenant Monitor", [
        "Real-time DSCR tracking against lender covenant thresholds",
        "Traffic-light alert system: Green (safe), Amber (watch), Red (breach)",
        "Debt service coverage waterfall chart",
        "Automated alert rules with configurable thresholds",
        "AI commentary on covenant risk and recommended actions",
    ]),

    # AI Assistant
    ("07_assistant.png", "AI Assistant — Persona-Toned Q&A", [
        "Natural language Q&A powered by Azure OpenAI GPT-5.2",
        "RAG (Retrieval-Augmented Generation) grounded in uploaded model data",
        "Persona-adapted responses: Investment Manager gets deal-focused answers",
        "Suggested prompts: 'Should we approve?', 'Top drivers of IRR downside?'",
        "Citation sources linked back to specific model sheets and sections",
    ]),

    # Reports
    ("08_reports.png", "AI Report Generator", [
        "One-click Investment Committee Paper generation",
        "Persona-specific report templates: IC Paper, Board Memo, Risk Report",
        "Tone and emphasis adapt to the selected persona",
        "RAG-grounded: reports cite actual model data and assumptions",
        "Export-ready formatting for stakeholder distribution",
    ]),

    # Architecture slide (no image)
    (None, "Architecture & Technology Stack", [
        "Frontend: Next.js 14 with Tailwind CSS dark theme, App Router",
        "Backend: FastAPI (Python 3.12) with SQLAlchemy ORM",
        "Database: PostgreSQL 16 with pgvector for semantic search",
        "AI: Azure AI Foundry — GPT-5.2 (chat) + text-embedding-ada-002 (embeddings)",
        "Infrastructure: Docker Compose (5 services), deployable to Azure Container Apps",
        "Orchestrator: Multi-agent system (Ingest, Cashflow, Sensitivity, Monte Carlo, Report, Monitor agents)",
        "Security: JWT auth, role-based access, audit logging",
    ]),
]

# Color palette (dark theme inspired)
BG_DARK = (11, 20, 55)       # #0B1437
CARD_BG = (17, 28, 68)       # #111C44
GOLD = (234, 179, 8)         # #EAB308
WHITE = (255, 255, 255)
MUTED = (163, 174, 208)      # #A3AED0
BORDER = (27, 43, 101)       # #1B2B65


class InvestIQPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.set_auto_page_break(auto=False)

    def _safe(self, text):
        """Replace Unicode chars that latin-1 can't encode."""
        return (text
            .replace("\u2014", "-")   # em dash
            .replace("\u2013", "-")   # en dash
            .replace("\u2018", "'")   # left single quote
            .replace("\u2019", "'")   # right single quote
            .replace("\u201c", '"')   # left double quote
            .replace("\u201d", '"')   # right double quote
            .replace("\u2022", "-")   # bullet
            .replace("\u2026", "...") # ellipsis
            .replace("\U0001f4ca", "")  # chart emoji
            .replace("\U0001f3b2", "")  # dice emoji
            .replace("\U0001f916", "")  # robot emoji
            .replace("\U0001f4a1", "")  # lightbulb emoji
            .replace("\U0001f4c4", "")  # page emoji
            .replace("\U0001f680", "")  # rocket emoji
        )

    def dark_bg(self):
        self.set_fill_color(*BG_DARK)
        self.rect(0, 0, self.w, self.h, "F")

    def add_title_slide(self):
        self.add_page()
        self.dark_bg()

        # Gold accent line
        self.set_fill_color(*GOLD)
        self.rect(40, 55, 80, 3, "F")

        # Title
        self.set_font("Helvetica", "B", 42)
        self.set_text_color(*WHITE)
        self.set_xy(40, 65)
        self.cell(0, 20, "InvestIQ", new_x="LMARGIN", new_y="NEXT")

        # Subtitle
        self.set_font("Helvetica", "", 20)
        self.set_text_color(*MUTED)
        self.set_xy(40, 88)
        self.cell(0, 12, "Capital Decision Intelligence Platform", new_x="LMARGIN", new_y="NEXT")

        # Description
        self.set_font("Helvetica", "", 14)
        self.set_text_color(*MUTED)
        self.set_xy(40, 110)
        self.cell(0, 8, "AI-powered infrastructure investment analysis", new_x="LMARGIN", new_y="NEXT")
        self.set_xy(40, 120)
        self.cell(0, 8, "From Excel upload to Investment Committee decision in minutes", new_x="LMARGIN", new_y="NEXT")

        # Bottom bar
        self.set_fill_color(*GOLD)
        self.rect(40, 155, 80, 2, "F")

        self.set_font("Helvetica", "", 11)
        self.set_text_color(*MUTED)
        self.set_xy(40, 162)
        self.cell(0, 8, "Application Walkthrough  |  May 2026")

    def add_content_slide(self, image_path, title, bullets):
        self.add_page()
        self.dark_bg()

        # Top gold accent
        self.set_fill_color(*GOLD)
        self.rect(0, 0, self.w, 2, "F")

        # Title
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(*GOLD)
        self.set_xy(10, 8)
        self.cell(0, 12, self._safe(title))

        # Divider
        self.set_fill_color(*BORDER)
        self.rect(10, 22, self.w - 20, 0.5, "F")

        if image_path and os.path.exists(image_path):
            # Layout: image on left, bullets on right
            img = Image.open(image_path)
            img_w, img_h = img.size
            aspect = img_h / img_w

            # Image area: left half
            max_img_w = 155
            max_img_h = 155
            display_w = max_img_w
            display_h = display_w * aspect
            if display_h > max_img_h:
                display_h = max_img_h
                display_w = display_h / aspect

            img_x = 8
            img_y = 27

            # Card background for image
            self.set_fill_color(*CARD_BG)
            self.set_draw_color(*BORDER)
            self.rect(img_x - 2, img_y - 2, display_w + 4, display_h + 4, "FD")

            self.image(image_path, x=img_x, y=img_y, w=display_w, h=display_h)

            # Bullets on the right
            bullet_x = img_x + display_w + 10
            bullet_y = 30
            bullet_w = self.w - bullet_x - 10
        else:
            # No image — full width bullets, centered
            bullet_x = 40
            bullet_y = 40
            bullet_w = self.w - 80

        self.set_font("Helvetica", "", 11)
        self.set_text_color(*WHITE)

        y = bullet_y
        for bullet in bullets:
            # Gold bullet dot
            self.set_fill_color(*GOLD)
            self.ellipse(bullet_x, y + 2.5, 2.5, 2.5, "F")

            self.set_xy(bullet_x + 5, y)
            self.set_text_color(*WHITE)
            self.multi_cell(bullet_w - 5, 6, self._safe(bullet))
            y = self.get_y() + 3

            if y > 185:
                break

        # Footer
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*MUTED)
        self.set_xy(10, 195)
        self.cell(0, 5, "InvestIQ  |  Capital Decision Intelligence  |  May 2026", align="C")

    def add_closing_slide(self):
        self.add_page()
        self.dark_bg()

        self.set_fill_color(*GOLD)
        self.rect(80, 60, 140, 3, "F")

        self.set_font("Helvetica", "B", 36)
        self.set_text_color(*WHITE)
        self.set_xy(80, 70)
        self.cell(140, 18, "Thank You", align="C")

        self.set_font("Helvetica", "", 16)
        self.set_text_color(*MUTED)
        self.set_xy(80, 95)
        self.cell(140, 10, "Questions & Discussion", align="C")

        self.set_fill_color(*GOLD)
        self.rect(80, 115, 140, 2, "F")

        self.set_font("Helvetica", "", 12)
        self.set_text_color(*MUTED)
        self.set_xy(80, 125)
        self.cell(140, 8, "InvestIQ - From Excel to Investment Decision", align="C")
        self.set_xy(80, 135)
        self.cell(140, 8, "Powered by Azure AI Foundry  |  GPT-5.2", align="C")


def main():
    pdf = InvestIQPDF()

    for i, (img, title, bullets) in enumerate(SLIDES):
        if i == 0:
            # Title slide
            pdf.add_title_slide()
        elif img is None and title:
            # Text-only slide (architecture)
            pdf.add_content_slide(None, title, bullets)
        else:
            img_path = os.path.join(SCREENSHOTS_DIR, img) if img else None
            pdf.add_content_slide(img_path, title, bullets)

    # Closing slide
    pdf.add_closing_slide()

    pdf.output(OUTPUT_PATH)
    print(f"PDF saved to {OUTPUT_PATH}")
    print(f"Total pages: {pdf.page_no()}")


if __name__ == "__main__":
    main()
