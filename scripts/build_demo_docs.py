"""Build the demo company document and the parser test fixtures.

    uv run python scripts/build_demo_docs.py

Writes data/demo/demo_company.{docx,pdf} and tests/fixtures/sample.{docx,pdf}.
The demo leaves out the price and the marketing budget on purpose (to test
missing_info) and contains a "trap": the most enthusiastic group (vegans) is
a very small share of the market.
"""

from pathlib import Path

from docx import Document
from fpdf import FPDF
from fpdf.fonts import FontFace

ROOT = Path(__file__).resolve().parent.parent

DEMO = [
    ("title", "Verdo Foods - Company and Product Brief"),
    ("p", "Launch of Proteo Crisps in France. Internal document, prepared for the launch planning team. "
          "All companies, people and figures in this document are fictional and used for demonstration only."),

    ("h", "1. Company overview"),
    ("p", "Verdo Foods S.r.l. is an Italian food company founded in 2020 in Bologna by Giulia Ferri, a food "
          "technologist, and Marco Bassi, former category manager at a large Italian retailer. The company "
          "develops savoury snacks made from legumes, with a focus on high protein content, short ingredient "
          "lists and sustainable packaging."),
    ("p", "In 2024 Verdo Foods had 28 employees and a turnover of 4.2 million euros, almost entirely in Italy. "
          "Its products are sold in about 2,300 points of sale in Italy (supermarkets, organic shops and a "
          "selection of gyms) and through its own online shop, which accounts for 9% of sales. The company "
          "closed its first profitable year in 2024 and raised a second funding round in early 2025 to finance "
          "its first international launch."),
    ("p", "Mission: make plant-based protein an everyday snack, not a niche product for athletes or vegans."),

    ("h", "2. The product: Proteo Crisps"),
    ("p", "Proteo Crisps are oven-baked crisps made from chickpea flour and pea protein. They were launched in "
          "Italy in 2022 and are now the company's best-selling line, with 61% of its turnover."),
    ("bullets", [
        "15 g of protein per 40 g bag, about 30% more than the leading plant-based protein crisps in Italy.",
        "Three flavours: Sea Salt, Rosemary, and Smoked Paprika. A fourth flavour (Herbes de Provence) is being "
        "developed specifically for France.",
        "Only six ingredients, no palm oil, no additives; vegan and gluten-free certified.",
        "Nutri-Score A for Sea Salt and Rosemary, B for Smoked Paprika.",
        "Compostable packaging, introduced in 2024.",
        "Shelf life of 9 months, which allows distribution through standard supermarket logistics.",
    ]),
    ("p", "In Italian blind taste tests run by the company in 2024 (420 participants), Proteo Crisps were "
          "preferred to the leading conventional potato crisps by 47% of participants, a tie for 21%, and less "
          "preferred by 32%. Texture was the most appreciated attribute; the Smoked Paprika flavour was judged "
          "too strong by a quarter of participants."),

    ("h", "3. Why France, and launch goals"),
    ("p", "France is the second largest savoury snack market in Europe and the fastest growing market for "
          "protein snacks in Southern Europe. French consumers are familiar with Nutri-Score, which was created "
          "in France, and the company sees its Nutri-Score A rating as a strong argument on the shelf."),
    ("p", "Goals for the French launch, approved by the board in June 2025:"),
    ("bullets", [
        "Reach a 2% value share of the French protein snack category within 24 months of launch.",
        "Be listed in at least 1,500 points of sale in the first year.",
        "Generate 25% of company turnover from France by the end of 2027.",
        "Reach break-even on the French operation in the third year.",
    ]),
    ("p", "The launch is planned for March 2026, starting with the Paris, Lyon and Lille regions."),

    ("h", "4. Market context"),
    ("p", "The figures below come from the NutriMarket Insights report 'Protein snacks in France 2025' and "
          "from the France Snack Panel 2024 consumer survey (both fictional sources for this demo)."),
    ("table", [
        ["Indicator", "Value", "Source"],
        ["Savoury snack market in France (2024)", "2.9 billion euros", "NutriMarket Insights 2025"],
        ["Protein snack category in France (2024)", "480 million euros", "NutriMarket Insights 2025"],
        ["Protein snack category growth 2021-2024", "+11% per year", "NutriMarket Insights 2025"],
        ["Plant-based share of protein snacks", "18%", "NutriMarket Insights 2025"],
        ["Adults buying protein snacks (last 3 months)", "27%", "France Snack Panel 2024"],
    ]),
    ("p", "In short, the protein snack category is worth 480 million euros and grows by 11% per year; "
          "plant-based products are 18% of it, and 27% of French adults bought a protein snack in the last "
          "three months."),
    ("p", "Supermarkets and hypermarkets account for 68% of protein snack sales in France, specialised "
          "sport and organic shops for 17%, online for 9%, and gyms and vending for 6% (NutriMarket "
          "Insights 2025)."),

    ("h", "5. Consumer groups"),
    ("p", "The France Snack Panel 2024 measured purchase intent for a high-protein, plant-based crisp after "
          "showing a product concept similar to Proteo Crisps. Group sizes refer to adults aged 18 to 64 in "
          "France (about 51 million people)."),
    ("table", [
        ["Group", "Size (adults)", "Share of adults", "Purchase intent"],
        ["Vegans and strict vegetarians", "1.3 million", "2.5%", "72%"],
        ["Weekly sport practitioners", "17.5 million", "34%", "41%"],
        ["Health-conscious office workers", "9.0 million", "18%", "38%"],
        ["Parents of school-age children", "7.1 million", "14%", "22%"],
    ]),
    ("p", "Reading the table: vegans and strict vegetarians are the most enthusiastic group (72% purchase "
          "intent) but only 1.3 million adults, 2.5% of the adult population. Weekly sport practitioners are "
          "the largest group, 17.5 million adults (34%), with 41% purchase intent. Health-conscious office "
          "workers are 9.0 million (18%) with 38% intent, and parents of school-age children 7.1 million "
          "(14%) with 22% intent."),
    ("p", "Groups overlap: for example, many sport practitioners are also office workers. Source: France "
          "Snack Panel 2024."),
    ("p", "The founders' first instinct is to target vegans, because they show by far the highest enthusiasm "
          "for the concept and are the most active group on social media. The team has not yet decided on the "
          "target group."),

    ("h", "6. Competitive landscape"),
    ("p", "The main competitors identified by the team in France are:"),
    ("bullets", [
        "Barebells: protein bars and snacks, strong presence in gyms and supermarkets, sport-oriented image.",
        "Gerble: French brand of health and wellness foods, widely available in supermarkets, with some "
        "protein products.",
        "Supermarket private labels, which entered the protein snack category in 2023 with lower prices.",
    ]),
    ("p", "The team has not yet carried out a detailed price comparison of competitors in France."),

    ("h", "7. Production and distribution"),
    ("p", "Proteo Crisps are produced in the company's plant near Bologna, which currently runs at 55% of its "
          "capacity and can supply the French launch without new investment. For France, Verdo Foods plans "
          "to work with a national food distributor for supermarkets and to sell directly to gyms and organic "
          "shops in the launch regions. The online shop will be translated and will ship to France from launch "
          "day."),
    ("p", "Packaging will be adapted to French labelling rules, with Nutri-Score shown on the front of the pack."),

    ("h", "8. Open points"),
    ("bullets", [
        "Choice of the target group and of the positioning for France.",
        "Launch campaign concept and channel plan.",
        "Name of the national distributor (negotiations ongoing with two candidates).",
    ]),
]

SAMPLE = [
    ("title", "Sample document"),
    ("p", "This is a small test fixture for the PremortemAI parser."),
    ("p", "Acme Snacks sells crunchy chickpea snacks in Italy."),
]


def _to_latin1(text: str) -> str:
    # fpdf2 core fonts only cover latin-1
    return text.encode("latin-1", "replace").decode("latin-1")


def write_docx(blocks, path: Path) -> None:
    doc = Document()
    for kind, content in blocks:
        if kind == "title":
            doc.add_heading(content, level=0)
        elif kind == "h":
            doc.add_heading(content, level=1)
        elif kind == "p":
            doc.add_paragraph(content)
        elif kind == "bullets":
            for item in content:
                doc.add_paragraph(item, style="List Bullet")
        elif kind == "table":
            table = doc.add_table(rows=0, cols=len(content[0]), style="Light Grid Accent 1")
            for row in content:
                cells = table.add_row().cells
                for cell, value in zip(cells, row):
                    cell.text = value
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def write_pdf(blocks, path: Path) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    for kind, content in blocks:
        if kind == "title":
            pdf.set_font("Helvetica", "B", 18)
            pdf.multi_cell(0, 9, _to_latin1(content), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
        elif kind == "h":
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 7, _to_latin1(content), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif kind == "p":
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, _to_latin1(content), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "bullets":
            pdf.set_font("Helvetica", "", 11)
            for item in content:
                pdf.multi_cell(0, 6, _to_latin1(f"-  {item}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "table":
            pdf.set_font("Helvetica", "", 9)
            # Wide first column so labels do not wrap: wrapped cells break the text extraction
            first = 80 if len(content[0]) == 3 else 65
            rest = (170 - first) / (len(content[0]) - 1)
            widths = (first, *[rest] * (len(content[0]) - 1))
            with pdf.table(col_widths=widths, headings_style=FontFace(emphasis="BOLD")) as table:
                for row in content:
                    table.row([_to_latin1(v) for v in row])
            pdf.ln(3)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def main() -> None:
    write_docx(DEMO, ROOT / "data/demo/demo_company.docx")
    write_pdf(DEMO, ROOT / "data/demo/demo_company.pdf")
    write_docx(SAMPLE, ROOT / "tests/fixtures/sample.docx")
    write_pdf(SAMPLE, ROOT / "tests/fixtures/sample.pdf")


if __name__ == "__main__":
    main()
