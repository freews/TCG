import json
import os
import re
import logging
import base64
import io
from functools import lru_cache
from pdf2image import convert_from_path
from PIL import Image
from html.parser import HTMLParser

# --- Configuration ---
STRUCTURE_FILE = "./tcg_output/pdf_structure.json"
MD_FOLDER = "./tcg_output/md"
OUTPUT_JSON = "./tcg_output/section_content.json"
PDF_PATH = "./TCG-Storage-Opal-SSC-v2.30_pub.pdf"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = None


class TableToMarkdownParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.in_th_td = False
        self.current_row_is_header = True
        self.row_types = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == 'tr':
            self.current_row = []
            self.current_row_is_header = True
        elif tag_lower in ('th', 'td'):
            self.in_th_td = True
            self.current_cell = []
            if tag_lower == 'td':
                self.current_row_is_header = False

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == 'tr':
            if self.current_row:
                self.rows.append(self.current_row)
                self.row_types.append('header' if self.current_row_is_header else 'data')
        elif tag_lower in ('td', 'th'):
            self.in_th_td = False
            cell_content = " ".join(self.current_cell).strip()
            cell_content = re.sub(r'\s+', ' ', cell_content)
            self.current_row.append(cell_content)

    def handle_data(self, data):
        if self.in_th_td:
            self.current_cell.append(data)

    def get_markdown(self):
        if not self.rows:
            return ""
        md_lines = []
        for i, row in enumerate(self.rows):
            md_line = "| " + " | ".join(row) + " |"
            md_lines.append(md_line)
            if self.row_types[i] == 'header':
                sep = "| " + " | ".join(['---'] * len(row)) + " |"
                md_lines.append(sep)
        return "\n".join(md_lines)


def process_html_tables(content):
    processed_content = content
    start_search_idx = 0
    while True:
        table_start = re.search(r'<table', processed_content[start_search_idx:], re.IGNORECASE)
        if not table_start:
            break
        start_idx = start_search_idx + table_start.start()
        table_end = re.search(r'</table>', processed_content[start_idx:], re.IGNORECASE)
        if not table_end:
            start_search_idx = start_idx + 1
            continue
        end_idx = start_idx + table_end.end()
        table_html = processed_content[start_idx:end_idx]
        parser = TableToMarkdownParser()
        parser.feed(table_html)
        md_table = parser.get_markdown()
        processed_content = (processed_content[:start_idx] + "\n" + md_table + "\n" + processed_content[end_idx:])
        start_search_idx = start_idx + len(md_table) + 2
    return processed_content


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_page_md(page_num):
    path = os.path.join(MD_FOLDER, f"page_{page_num:04d}.md")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content_raw = f.read()
        return process_html_tables(content_raw)
    return ""


@lru_cache(maxsize=5)
def get_page_image(pdf_path, page_num, dpi=200):
    try:
        images = convert_from_path(pdf_path, dpi=dpi, first_page=page_num, last_page=page_num)
        return images[0] if images else None
    except Exception as e:
        logger.error(f"Failed to render page {page_num}: {e}")
        return None


def crop_and_encode_image(pdf_path, page_num, coords):
    try:
        img = get_page_image(pdf_path, page_num)
        if not img:
            return None
        width, height = img.size
        x1 = int(coords[0] * width / 1000)
        y1 = int(coords[1] * height / 1000)
        x2 = int(coords[2] * width / 1000)
        y2 = int(coords[3] * height / 1000)
        if x1 >= x2 or y1 >= y2:
            return None
        cropped_img = img.crop((x1, y1, x2, y2))
        buffered = io.BytesIO()
        cropped_img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"Image crop failed on page {page_num}: {e}")
        return None


def find_section_in_lines(lines, section_key):
    """라인 리스트에서 섹션 시작 위치 찾기 (section_key 사용)"""
    if not section_key:
        return None
    
    # section_key에서 section_id 추출 (예: "1.1 Overview" -> "1.1")
    section_id = section_key.split()[0] if section_key else None
    if not section_id:
        return None
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # 마크다운 헤더 제거 (##, #)
        if stripped.startswith('#'):
            stripped = re.sub(r'^#+\s*', '', stripped)
        
        # section_id로 시작하고, 그 다음이 공백인 경우
        if stripped.startswith(section_id):
            if len(stripped) > len(section_id):
                next_char = stripped[len(section_id)]
                if next_char == ' ':
                    return i
            elif len(stripped) == len(section_id):
                return i
    return None


def is_table_content(line):
    stripped = line.strip()
    if '|' not in line:
        return False
    if set(stripped) - {'|', '-', ':', ' '}:
        return True
    if set(stripped).issubset({'|', '-', ':', ' '}) and len(stripped) > 2:
        return True
    return False


def extract_figure_caption(line):
    stripped = line.strip()
    match = re.match(r'^(Figure|Table)\s+(\d+)', stripped, re.IGNORECASE)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return None


def extract_section_full_text(section, next_section, page_cache):
    start_page = section['start_page']
    end_page = section['end_page']
    sec_key = section.get('section_key', section.get('section_id', ''))
    next_sec_key = next_section.get('section_key', next_section.get('section_id', '')) if next_section else None
    
    full_text_parts = []
    page_line_map = []
    
    for page_num in range(start_page, end_page + 1):
        if page_num not in page_cache:
            page_cache[page_num] = read_page_md(page_num)
        
        page_content = page_cache[page_num]
        if not page_content:
            continue
        
        lines = page_content.split('\n')
        
        if page_num == start_page:
            start_line = find_section_in_lines(lines, sec_key)
            if start_line is not None:
                lines = lines[start_line:]
        
        if page_num == end_page and next_sec_key:
            end_line = find_section_in_lines(lines, next_sec_key)
            if end_line is not None:
                lines = lines[:end_line]
        
        for line in lines:
            page_line_map.append((page_num, len(full_text_parts)))
            full_text_parts.append(line)
    
    full_text = "\n".join(full_text_parts)
    return full_text, page_line_map


def extract_assets_from_full_text(full_text, page_line_map, section):
    section_images = {}
    section_tables = {}
    lines = full_text.split('\n')
    current_figure_name = None
    current_table_rows = []
    
    for line_idx, line in enumerate(lines):
        current_page = None
        for page_num, mapped_line_idx in page_line_map:
            if mapped_line_idx == line_idx:
                current_page = page_num
                break
        
        # 이미지 메타데이터 체크
        img_match = re.search(
            r'<!--\s*(Figure\s*[\d\.]+|Embeded_Image\s*\d+).*?'
            r'coordinate:\((\d+),(\d+),(\d+),(\d+)\).*?-->', 
            line
        )
        
        if img_match:
            img_name = img_match.group(1)
            coords = tuple(int(img_match.group(j)) for j in range(2, 6))
            # 테이블이 없으면 이미지로 처리 (나중에 판단)
            if img_name not in section_images and current_page and img_name not in section_tables:
                b64_img = crop_and_encode_image(PDF_PATH, current_page, coords)
                if b64_img:
                    section_images[img_name] = b64_img
            continue
        
        # 테이블 라인 체크
        if is_table_content(line):
            current_table_rows.append(line)
            continue
        
        # 테이블 아닌 라인 - 테이블 종료
        if len(current_table_rows) > 1:
            if current_figure_name:
                if current_figure_name in section_tables:
                    existing_rows = section_tables[current_figure_name]
                    start_idx = 2 if len(current_table_rows) > 1 and \
                                set(current_table_rows[1].strip()).issubset({'|', '-', ':', ' '}) else 1
                    existing_rows.extend(current_table_rows[start_idx:])
                else:
                    section_tables[current_figure_name] = current_table_rows.copy()
            current_table_rows = []
        
        # Figure 캡션 체크
        fig_caption = extract_figure_caption(line)
        if fig_caption:
            current_figure_name = fig_caption
    
    # 마지막 테이블
    if len(current_table_rows) > 1 and current_figure_name:
        section_tables[current_figure_name] = current_table_rows.copy()
    
    return section_images, section_tables


def create_content_md(full_text):
    lines = full_text.split('\n')
    content_lines = []
    in_table = False
    
    for line in lines:
        if re.search(r'<!--\s*Figure.*?-->', line):
            continue
        if is_table_content(line):
            in_table = True
            continue
        else:
            if in_table:
                in_table = False
            content_lines.append(line)
    
    content_md = "\n".join(content_lines)
    content_md = re.sub(r'\n{3,}', '\n\n', content_md)
    return content_md.strip()


def extract_section_content_and_assets(section, next_section, page_cache):
    sec_id = section['section_id']
    start_page = section['start_page']
    end_page = section['end_page']
    
    logger.info(f"Processing Section {sec_id}: Pages {start_page}-{end_page}")
    
    full_text, page_line_map = extract_section_full_text(section, next_section, page_cache)
    
    if not full_text.strip():
        logger.warning(f"  No content found for section {sec_id}")
        return "", [], [], [], []
    
    section_images, section_tables = extract_assets_from_full_text(full_text, page_line_map, section)
    content_md = create_content_md(full_text)
    
    image_names = list(section_images.keys())
    image_data = list(section_images.values())
    table_names = list(section_tables.keys())
    table_data = list(section_tables.values())
    
    logger.info(f"  -> Images: {len(image_names)}, Tables: {len(table_names)}")
    
    return content_md, image_names, image_data, table_names, table_data


def main():
    logger.info("=== STEP 3: Section Aggregation (Full Run) ===")
    
    if not os.path.exists(STRUCTURE_FILE):
        logger.error("Structure file missing.")
        return

    structure = load_json(STRUCTURE_FILE)
    output_data = []
    page_cache = {}
    
    total = len(structure)
    for i, section in enumerate(structure):
        title = section.get('title', 'Unknown')
        start_page = section.get('start_page', 0)
        
        # Skip pages 4-11 (불필요한 페이지)
        if 4 <= start_page <= 11:
            logger.info(f"[{i+1}/{total}] Skipping: {title} (Page {start_page})")
            continue
        
        logger.info(f"[{i+1}/{total}] Aggregating: {title}")

        next_sec = structure[i+1] if i < len(structure) - 1 else None
        content, img_names, imgs, tbl_names, tbls = extract_section_content_and_assets(
            section, next_sec, page_cache
        )
        
        section_entry = section.copy()
        section_entry.update({
            'content_md': content,
            'section_image_name_list': img_names,
            'section_image': imgs,
            'section_table_list': tbl_names,
            'section_table': tbls,
            'summary': ""
        })
        
        output_data.append(section_entry)

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
    
    logger.info(f"Saved to {OUTPUT_JSON}")
    logger.info(f"Processed {len(output_data)} sections")


if __name__ == "__main__":
    main()
