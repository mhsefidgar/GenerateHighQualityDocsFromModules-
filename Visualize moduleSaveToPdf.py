import inspect
import os
import html
import pkgutil
import importlib
from collections import deque

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Indenter, HRFlowable
)
from reportlab.lib.units import inch
from reportlab.platypus.tableofcontents import TableOfContents


# ===================== PAGE DECORATION =====================

def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica-Oblique', 8)
    canvas.setStrokeColor(colors.lightgrey)
    canvas.line(0.5 * inch, 0.75 * inch, 8 * inch, 0.75 * inch)
    canvas.drawString(0.5 * inch, 0.5 * inch, f"API Map | Page {doc.page}")
    canvas.restoreState()


# ===================== CUSTOM DOC TEMPLATE =====================

class MyDocTemplate(SimpleDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, **kw)
        self.toc = TableOfContents()
        self.last_outline_level = -1

    def afterFlowable(self, flowable):
        if hasattr(flowable, 'toc_level') and hasattr(flowable, 'toc_key'):
            text = flowable.getPlainText()
            level = flowable.toc_level
            key = flowable.toc_key

            self.canv.bookmarkPage(key)

            safe_level = min(level, self.last_outline_level + 1)
            self.last_outline_level = safe_level

            self.canv.addOutlineEntry(text, key, level=safe_level)
            self.notify('TOCEntry', (level, text, self.page, key))


# ===================== MAIN FUNCTION =====================

def create_module_pdf(module, save_dir=None, filename="api_docs.pdf", max_depth=3):

    if save_dir is None:
        save_dir = os.path.join(os.path.expanduser("~"), "Desktop")

    output_path = os.path.join(save_dir, filename)
    styles = getSampleStyleSheet()

    # ===== STYLE CONFIGURATION =====
    INDENT_PER_DEPTH = 12         
    HR_SPACE = 2                  
    HEADER_SPACE = 6              

    h_style = ParagraphStyle(
        'PathHeader',
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        spaceBefore=HEADER_SPACE,
        spaceAfter=2,
        textColor=colors.HexColor("#1e293b"),
    )

    sig_text_style = ParagraphStyle(
        'SigText',
        fontName='Courier-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#63b3ed")
    )

    doc_text_style = ParagraphStyle(
        'DocNormal',
        fontSize=9,
        leading=12,
        spaceBefore=2,
        spaceAfter=4,
        textColor=colors.black
    )

    elements = []

    # ===== TITLE PAGE =====
    elements.append(Paragraph(f"API Structure: {module.__name__}", styles['Title']))
    elements.append(Spacer(1, 12))

    # ===== TABLE OF CONTENTS =====
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            name=f'TOCLevel{i}',
            fontSize=9,
            leftIndent=i * 12,
            firstLineIndent=0,
            spaceBefore=2
        ) for i in range(max_depth + 2)
    ]

    elements.append(toc)
    elements.append(PageBreak())

    visited = set()
    root_lib = module.__name__.split('.')[0]
    item_count = [0] 

    # ===================== DFS RECURSIVE WALK =====================

    def walk_tree(curr_obj, curr_path, depth):
        if curr_path in visited or depth > max_depth:
            return
        
        if any(x in curr_path for x in ['_libs', 'tests', 'plotting', 'conftest', 'textpath']):
            return

        visited.add(curr_path)
        item_count[0] += 1
        
        if item_count[0] > 3000: # Increased limit for large libraries like Matplotlib
            return

        # --- DRAW ITEM ---
        header = Paragraph(curr_path, h_style)
        header.toc_level = depth
        header.toc_key = f"key_{item_count[0]}"
        header.keepWithNext = True

        try:
            sig = str(inspect.signature(curr_obj))
        except:
            sig = "(...)"

        sig_para = Paragraph(f"<code>{curr_path.split('.')[-1]}{sig}</code>", sig_text_style)
        sig_table = Table([[sig_para]], hAlign='LEFT')
        sig_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('ROUNDEDCORNERS', [4, 4, 4, 4])
        ]))

        raw_doc = inspect.getdoc(curr_obj) or "No description available."
        clean_doc = html.escape(raw_doc).replace('\n', '<br/>')
        doc_paragraph = Paragraph(clean_doc, doc_text_style)

        indent = INDENT_PER_DEPTH * depth
        elements.append(header)
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=HR_SPACE))
        elements.append(Indenter(left=indent))
        elements.append(sig_table)
        elements.append(Spacer(1, 4))
        elements.append(doc_paragraph)
        elements.append(Indenter(left=-indent))
        elements.append(Spacer(1, 10))

        # --- DISCOVER CHILDREN (With Submodule Inclusion) ---
        if depth < max_depth:
            children_dict = {}

            # 1. Discover via dir()
            for name in dir(curr_obj):
                if name.startswith('_'): continue
                try:
                    child = getattr(curr_obj, name)
                    if inspect.ismodule(child) or inspect.isclass(child) or inspect.isfunction(child):
                        mod_name = getattr(child, '__module__', '') or ''
                        if str(mod_name).startswith(root_lib):
                            children_dict[name] = child
                except: continue

            # 2. Discover via pkgutil (Forces submodules like pyplot to appear)
            if inspect.ismodule(curr_obj) and hasattr(curr_obj, "__path__"):
                try:
                    for info in pkgutil.iter_modules(curr_obj.__path__):
                        if info.name.startswith('_'): continue
                        try:
                            # Dynamically import the submodule so it's documented
                            full_sub_path = f"{curr_path}.{info.name}"
                            sub_mod = importlib.import_module(full_sub_path)
                            children_dict[info.name] = sub_mod
                        except: continue
                except: pass

            # Sort alphabetically for the "Normal Book" feel
            for name in sorted(children_dict.keys()):
                walk_tree(children_dict[name], f"{curr_path}.{name}", depth + 1)

    walk_tree(module, module.__name__, 0)

    doc = MyDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=0.5 * inch,
        bottomMargin=inch
    )
    doc.multiBuild(elements, onFirstPage=header_footer, onLaterPages=header_footer)
    print(f"Finished: {output_path}")


# ===================== RUN =====================

if __name__ == "__main__":
    import matplotlib
    # To ensure pyplot is found, we can also import it once here
    import matplotlib.pyplot 

    save_path = r"C:\Users\username\OneDrive\Desktop\shortVideo\TalkingAvatar"
    create_module_pdf(matplotlib, save_dir=save_path, max_depth=2) # Depth 2 is usually enough for a clean map