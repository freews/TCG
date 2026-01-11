#!/usr/bin/env python3
"""
TCG Parser - ULTRA SIMPLE VERSION
==================================
페이지 경계면에서 갈라지는 테이블 처리를 위한 프롬프트 강화
"""

import os
import fitz
import requests
import base64
import logging
from pathlib import Path
from logger import logger

PDF_PATH = "./TCG-Storage-Opal-SSC-v2.30_pub.pdf"
OUTPUT_MD_FOLDER = "./tcg_output/md"
LOG_FILE = "./tcg_output/step1_base.log"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3-vl:32b-instruct-q4_K_M"

# Crop 설정: True이면 헤더/푸터 제거, False이면 전체 페이지 사용
USE_CROP = True



def create_prompt(last_table_info: str = None) -> str:
    """프롬프트 생성 - 이전 페이지의 테이블 정보 포함"""
    if last_table_info:
        base_prompt = f"""Extract all text from this page. Follow these rules:
1. Section headings: Use ## only for numbered sections (e.g., "## 4.2.1.1 SPInfo").
2. Apply markdown format to Table, and also apply it to the table with only one row. 
   Keep the row line number in the cell of the table.  
3. Do not skip any text, table, table-like object, in other words, include everything visible on the page.
4. IMPORTANT: If you see table rows at the very top of the page (before any section header),
   these are continuation rows from the previous page's table: "{last_table_info}"
   You MUST add this title line before the table rows:
   
   ### {last_table_info} (continued)
   
   Then output the table rows.
5. CRITICAL: Output content in EXACT top-to-bottom order as it appears on the page.
   If a table is at the top, output it FIRST before any section headers or text.
"""
    else:
        base_prompt = """Extract all text from this page. Follow these rules:
1. Section headings: Use ## only for numbered sections (e.g., "## 4.2.1.1 SPInfo").
2. Apply markdown format to Table, and also apply it to the table with only one row. 
   Keep the row line number in the cell of the table.  
3. Do not skip any text, table, table-like object, in other words, include everything visible on the page.
4. CRITICAL: Output content in EXACT top-to-bottom order as it appears on the page.
   If a table is at the top, output it FIRST before any section headers or text.
"""
    
    return base_prompt


def extract_last_table_name(content: str) -> str:
    """이전 페이지의 마지막 테이블 이름 추출 (있으면)"""
    import re
    lines = content.split('\n')
    
    # 역순으로 검색하여 가장 마지막 Table 제목 찾기
    # 패턴: "### Table XX" 또는 "Table XX -"
    for line in reversed(lines):
        # "### Table 19 - Admin SP - SPTemplates Table Preconfiguration" 형식
        match = re.search(r'###?\s+(Table\s+\d+[^#\n]*)', line)
        if match:
            return match.group(1).strip()
        
        # "Table XX -" 형식  
        match = re.search(r'(Table\s+\d+)(?:\s*-|\s*$)', line)
        if match:
            return match.group(1).strip()
    
    return None

def remove_header_footer(content: str) -> str:
    """마크다운에서 문서 헤더와 푸터 제거"""
    lines = content.split('\n')
    cleaned_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # 문서 헤더 패턴 (TCG Storage... 로 시작하는 ## 헤더)
        if stripped.startswith('## TCG Storage'):
            continue
        if stripped.startswith('## Opal'):
            continue
            
        # 푸터 패턴 (다양한 형식)
        # "TCG Storage Security Subsystem Class (SSC): Opal | Version 2.30 | 1/30/2025 | PUBLISHED"
        if 'TCG Storage' in stripped and 'Version' in stripped and 'PUBLISHED' in stripped:
            continue
        # "Page 35"
        if stripped.startswith('Page ') and stripped.split()[-1].isdigit():
            continue
        # "© TCG 2025" 또는 "TCG 2025"
        if '© TCG' in stripped or (stripped.startswith('TCG') and '2025' in stripped):
            continue
        # 페이지 번호와 저작권이 함께 있는 경우
        if 'Page' in stripped and 'TCG' in stripped and '2025' in stripped:
            continue
            
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)

def add_table_title_if_missing(content: str, last_table_info: str = None) -> str:
    """테이블 제목이 누락된 경우 자동으로 추가"""
    if not last_table_info:
        return content
    
    lines = content.split('\n')
    
    # 첫 번째 비어있지 않은 줄이 테이블 행인지 확인
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        
        # 테이블 행으로 시작하는지 확인 (|로 시작)
        if stripped.startswith('|') and '|' in stripped[1:]:
            # 제목이 없으면 추가
            title_line = f"### {last_table_info} (continued)\n"
            lines.insert(i, title_line)
            break
        else:
            # 테이블이 아니면 중단
            break
    
    return '\n'.join(lines)

def fix_table_separator(content: str) -> str:
    """테이블 구분선 위치 수정 - 데이터 행이 헤더로 표시되는 것 방지(수정)"""
    lines = content.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # 테이블 행인지 확인 (|로 시작하고 데이터 포함)
        if line.strip().startswith('|') and '|' in line[1:]:
            # 다음 줄이 구분선인지 확인
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # 구분선 패턴: |---|---|
                if next_line.startswith('|') and all(c in '|-' for c in next_line.replace(' ', '')):
                    # 구분선을 데이터 행 위로 이동
                    result.append(next_line)
                    result.append(line)
                    i += 2
                    continue
        
        result.append(line)
        i += 1
    
    return '\n'.join(result)

# ==========================================
# Core Functions
# ==========================================

def pdf_to_png(pdf_path: str, page_num: int, use_crop: bool = True) -> str:
    """단일 페이지를 PNG로 변환
    
    Args:
        pdf_path: PDF 파일 경로
        page_num: 페이지 번호 (1-based)
        use_crop: True이면 헤더/푸터 제거, False이면 전체 페이지 사용
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    pix = page.get_pixmap(dpi=200)
    
    # PIL Image로 변환
    from PIL import Image
    import io
    img_data = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_data))
    
    # 헤더/푸터 영역 크롭 (선택적)
    if use_crop:
        # 원본 PDF 좌표: header y=0~58, footer y=965~
        # DPI 200 변환 (×2.78): header ~161px, footer ~2682px
        width, height = img.size
        crop_top = 180  # 헤더 제거 (여유있게)
        crop_bottom = height - 100  # 푸터 제거 (넉넉하게)
        
        img_cropped = img.crop((0, crop_top, width, crop_bottom))
        png_dir = "./tcg_output/png_crop"
    else:
        img_cropped = img
        png_dir = "./tcg_output/png_full"
    
    # PNG 저장 (디렉토리 생성)
    os.makedirs(png_dir, exist_ok=True)
    png_path = f"{png_dir}/page_{page_num:04d}.png"
    img_cropped.save(png_path)
    doc.close()
    
    return png_path

def call_llm(image_path: str, prompt: str) -> str:
    """LLM 호출"""
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    # 토큰 수 추정 (대략 1 토큰 = 4 글자)
    prompt_tokens = len(prompt) // 4
    logger.info(f"  📊 Prompt size: ~{prompt_tokens} tokens")
    
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "images": [img_b64],
        "options": {
            "temperature": 0.0,
            "num_ctx": 8192,        # 컨텍스트 윈도우 (메모리 안정성)
            "num_batch": 256,       # 배치 크기 (작을수록 안정적)
            "num_predict": 4096,    # 최대 생성 토큰 수
            "num_thread": 6         # CPU 스레드 수
        }
    }
    
    resp = requests.post(OLLAMA_URL, json=payload, timeout=900)
    result = resp.json().get("response", "")
    
    # 응답 토큰 수 추정
    response_tokens = len(result) // 4
    total_tokens = prompt_tokens + response_tokens
    logger.info(f"  📊 Response size: ~{response_tokens} tokens, Total context: ~{total_tokens} tokens")
    
    return result

def process_page(page_num: int, prev_md: str = None, use_crop: bool = True) -> str:
    """페이지 처리 (에러 처리 포함)
    
    Args:
        page_num: 페이지 번호
        prev_md: 이전 페이지 마크다운 내용
        use_crop: 헤더/푸터 크롭 적용 여부
    """
    import time
    import traceback
    
    logger.info(f"Processing page {page_num}...")
    
    try:
        # PNG 변환
        png_path = pdf_to_png(PDF_PATH, page_num, use_crop=use_crop)
        
        # 이전 페이지에 테이블이 있으면 테이블 이름 추출
        last_table_info = None
        if prev_md:
            last_table_info = extract_last_table_name(prev_md)
            if last_table_info:
                logger.info(f"  📋 Previous page has table: {last_table_info}")
        
        # 프롬프트 생성 (테이블 컨텍스트 포함)
        prompt = create_prompt(last_table_info)
        
        # LLM 호출 (시간 측정)
        start_time = time.time()
        result = call_llm(png_path, prompt)
        process_time = time.time() - start_time
        
        # 후처리 1: 테이블 제목 추가 (누락된 경우)
        result = add_table_title_if_missing(result, last_table_info)
        
        # 후처리 2: 테이블 구분선 위치 수정
        result = fix_table_separator(result)
        
        # 후처리 3: 헤더/푸터 제거
        result = remove_header_footer(result)
        
        # 저장
        os.makedirs(OUTPUT_MD_FOLDER, exist_ok=True)
        md_path = Path(OUTPUT_MD_FOLDER) / f"page_{page_num:04d}.md"
        md_path.write_text(result, encoding='utf-8')
        
        logger.info(f"  ✅ Saved: {md_path.name} ({process_time:.1f}s)")
        # os.remove(png_path)  # PNG 파일 보존 (확인용)
        
        return result
        
    except Exception as e:
        # 에러 발생 시 에러 정보를 파일로 저장
        error_msg = f"# Error occurred while processing page {page_num}\n\n"
        error_msg += f"**Error Type**: {type(e).__name__}\n\n"
        error_msg += f"**Error Message**: {str(e)}\n\n"
        error_msg += f"**Traceback**:\n```\n{traceback.format_exc()}\n```\n"
        
        os.makedirs(OUTPUT_MD_FOLDER, exist_ok=True)
        error_path = Path(OUTPUT_MD_FOLDER) / f"page_{page_num:04d}_error.md"
        error_path.write_text(error_msg, encoding='utf-8')
        
        logger.error(f"  ❌ Error on page {page_num}: {type(e).__name__} - {str(e)}")
        logger.error(f"  💾 Error saved to: {error_path.name}")
        
        return ""  # 빈 문자열 반환하여 다음 페이지 계속 처리

# ==========================================
# Main
# ==========================================

def main(use_crop: bool = True):
    """메인 함수
    
    Args:
        use_crop: True이면 헤더/푸터 크롭 적용, False이면 전체 페이지 사용
    """
    print("="*70)
    print("TCG PARSER - ULTRA SIMPLE VERSION")
    print(f"Crop Mode: {'ENABLED (header/footer removed)' if use_crop else 'DISABLED (full page)'}")
    print("="*70)
    
    # 페이지 범위
    start_page = 33
    end_page = 101

    prev_md = None
    
    for page_num in range(start_page, end_page + 1):
        # 현재 페이지의 md 파일 경로
        md_path = Path(OUTPUT_MD_FOLDER) / f"page_{page_num:04d}.md"
        
        # 이미 처리된 페이지인지 확인
        if md_path.exists():
            logger.info(f"⏭️  Page {page_num} already exists, skipping...")
            # 다음 페이지를 위해 기존 파일 내용 읽기
            prev_md = md_path.read_text(encoding='utf-8')
            continue
        
        # 이전 페이지의 md 내용 가져오기 (파일에서 읽기)
        if prev_md is None and page_num > start_page:
            prev_page_path = Path(OUTPUT_MD_FOLDER) / f"page_{page_num-1:04d}.md"
            if prev_page_path.exists():
                prev_md = prev_page_path.read_text(encoding='utf-8')
        
        # 페이지 처리
        md_content = process_page(page_num, prev_md, use_crop=use_crop)
        prev_md = md_content  # 다음 페이지를 위해 저장
    
    print("="*70)
    print(f"Complete! Check: {OUTPUT_MD_FOLDER}")
    print("="*70)

if __name__ == "__main__":
    main(use_crop=USE_CROP)
