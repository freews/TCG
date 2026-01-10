#!/usr/bin/env python3
"""
Step 5: Summary Document Generator
===================================
section_content.json의 summary를 섹션 순서대로 마크다운 문서로 생성
"""

import json
import os
import logging
from datetime import datetime

# --- Configuration ---
INPUT_JSON = "./tcg_output/section_content.json"
OUTPUT_MD = "./tcg_output/TCG_Opal_Summary.md"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def generate_section_header(section):
    """섹션 헤더 생성 (레벨에 따라 # 개수 조정)"""
    level = section.get('level', 1)
    section_id = section.get('section_id', '')
    title = section.get('title', 'Unknown')
    
    # 마크다운 헤더 레벨 (최대 6)
    header_level = min(level, 6)
    header_prefix = '#' * header_level
    
    # 섹션 ID가 있으면 포함
    if section_id:
        return f"{header_prefix} {section_id} {title}"
    else:
        return f"{header_prefix} {title}"


def generate_section_metadata(section):
    """섹션 메타데이터 생성 (페이지 범위, 테이블/이미지 수)"""
    start_page = section.get('start_page', 0)
    end_page = section.get('end_page', 0)
    num_tables = len(section.get('section_table_list', []))
    num_images = len(section.get('section_image_name_list', []))
    
    metadata = f"**페이지**: {start_page}"
    if end_page != start_page:
        metadata += f"-{end_page}"
    
    if num_tables > 0 or num_images > 0:
        metadata += " | "
        if num_tables > 0:
            metadata += f"**테이블**: {num_tables}개"
        if num_images > 0:
            if num_tables > 0:
                metadata += " | "
            metadata += f"**이미지**: {num_images}개"
    
    return metadata


def main():
    logger.info("=== STEP 5: Summary Document Generation ===")
    
    if not os.path.exists(INPUT_JSON):
        logger.error(f"입력 파일이 없습니다: {INPUT_JSON}")
        return
    
    # JSON 로드
    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    logger.info(f"총 {len(data)}개 섹션 로드됨")
    
    # 마크다운 문서 생성
    md_lines = []
    
    # 문서 헤더
    md_lines.append("# TCG Storage Opal SSC v2.30 - 요약 문서")
    md_lines.append("")
    md_lines.append(f"**생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"**원본 문서**: TCG-Storage-Opal-SSC-v2.30_pub.pdf")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    
    # 통계
    total_sections = len(data)
    sections_with_summary = sum(1 for s in data if s.get('summary', '').strip())
    sections_without_summary = total_sections - sections_with_summary
    
    md_lines.append("## 📊 문서 통계")
    md_lines.append("")
    md_lines.append(f"- **총 섹션 수**: {total_sections}개")
    md_lines.append(f"- **요약 완료**: {sections_with_summary}개")
    md_lines.append(f"- **요약 미완료**: {sections_without_summary}개")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    
    # 각 섹션 처리
    processed = 0
    skipped = 0
    
    for i, section in enumerate(data):
        section_id = section.get('section_id', '')
        title = section.get('title', 'Unknown')
        summary = section.get('summary', '').strip()
        start_page = section.get('start_page', 0)
        
        # 4-11 페이지 건너뛰기
        if 4 <= start_page <= 11:
            skipped += 1
            continue
        
        # 섹션 헤더
        md_lines.append(generate_section_header(section))
        md_lines.append("")
        
        # 메타데이터
        md_lines.append(generate_section_metadata(section))
        md_lines.append("")
        
        # 요약 내용
        if summary:
            md_lines.append(summary)
            processed += 1
        else:
            md_lines.append("*요약 없음*")
        
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
    
    # 파일 저장
    os.makedirs(os.path.dirname(OUTPUT_MD), exist_ok=True)
    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines))
    
    logger.info(f"✅ 요약 문서 생성 완료: {OUTPUT_MD}")
    logger.info(f"📊 통계: 요약 포함 {processed}개 | 요약 없음 {total_sections - processed - skipped}개 | 건너뜀 {skipped}개")


if __name__ == "__main__":
    main()
