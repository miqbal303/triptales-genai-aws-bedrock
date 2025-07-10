# pdf_export.py
from fpdf import FPDF
import os

class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 16)
        self.cell(0, 10, "TripTales Travel Plan", ln=True, align="C")

    def add_section(self, title, content):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, title, ln=True)
        self.set_font("Arial", "", 12)
        self.multi_cell(0, 10, content)
        self.ln(5)

def export_to_pdf(dest, itinerary, packing, visa, food, img_paths):
    pdf = PDF()
    pdf.add_page()

    pdf.add_section("Destination", dest)
    pdf.add_section("Itinerary", itinerary)
    pdf.add_section("Packing List", packing)
    pdf.add_section("Visa Info", visa)
    pdf.add_section("Local Foods", food)

    for path in img_paths:
        pdf.image(path, w=180)

    os.makedirs("exports", exist_ok=True)
    pdf_path = f"exports/{dest}_trip_plan.pdf"
    pdf.output(pdf_path)
    return pdf_path
