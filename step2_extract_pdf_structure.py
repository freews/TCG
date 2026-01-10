import pymupdf
import json
import re
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

pdf_path = "./TCG-Storage-Opal-SSC-v2.30_pub.pdf"
md_folder = "./tcg_output/md"  # MD 파일이 있는 폴더 (step1 출력)
output_path = "./tcg_output/pdf_structure.json"

def extract_structure_from_toc():
    """PDF의 TOC 메타데이터에서 구조 추출 (기존 방식)"""
    try:
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found at: {pdf_path}")
            return None

        doc = pymupdf.open(pdf_path)
        toc = doc.get_toc()
        
        if not toc or len(toc) == 0:
            logger.warning("No TOC metadata found in PDF")
            return None
        
        structure = []
        id_pattern = re.compile(r'^((?:Annex\s+)?[A-Z\d][\w\.]*)\s+(.*)')
        
        logger.info("Adding manual 'Cover' section.")
        structure.append({
            "section_order": 1,
            "level": 1,
            "section_id": "Cover",
            "section_key": "Cover",
            "title": "Cover",
            "start_page": 1,
            "end_page": 1,
            "page_count": 1
        })

        seen_ids = set()
        logger.info(f"Processing {len(toc)} TOC entries...")

        for i, entry in enumerate(toc):
            lvl, title, page_num = entry
            
            # Skip pages 4-11 (불필요한 페이지)
            if 4 <= page_num <= 11:
                continue

            match = id_pattern.match(title)
            if match:
                sec_id = match.group(1).rstrip('.')
                sec_title = match.group(2)
            else:
                sec_id = "" 
                sec_title = title

            if sec_title and sec_title[0].islower() and not sec_id:
                continue

            if sec_id and sec_id in seen_ids:
                logger.warning(f"Skipping duplicate ID: {sec_id}")
                continue
            
            if sec_id:
                seen_ids.add(sec_id)

            if i < len(toc) - 1:
                next_start_page = toc[i+1][2]
                current_end_inclusive = next_start_page
            else:
                current_end_inclusive = len(doc)
            
            if current_end_inclusive < page_num:
                current_end_inclusive = page_num

            structure.append({
                "section_order": len(structure) + 1,
                "level": lvl,
                "section_id": sec_id,
                "section_key": f"{sec_id} {sec_title}" if sec_id else sec_title,
                "title": sec_title,
                "start_page": page_num,
                "end_page": current_end_inclusive,
                "page_count": current_end_inclusive - page_num + 1
            })

        logger.info(f"TOC extraction successful. Total sections: {len(structure)}")
        return structure

    except Exception as e:
        logger.error(f"Error extracting TOC: {e}")
        return None


def extract_structure_from_md():
    """MD 파일에서 직접 섹션 구조 추출 (TOC 없을 때)"""
    try:
        if not os.path.exists(md_folder):
            logger.error(f"MD folder not found at: {md_folder}")
            return None

        logger.info("Extracting structure from MD files...")
        
        structure = []
        seen_sections = {}  # {section_id: page_num}
        
        # MD 파일 목록 가져오기
        md_files = sorted([f for f in os.listdir(md_folder) if f.endswith('.md')])
        
        # 섹션 헤더 패턴
        # ## 1.2.3 Title 또는 # 1 Title 또는 1.2.3 Title
        section_pattern = re.compile(r'^(#+)?\s*(\d+(?:\.\d+)*)\s+(.+)$')
        
        for md_file in md_files:
            # page_0025.md -> 25
            page_match = re.search(r'page_(\d+)\.md', md_file)
            if not page_match:
                continue
            
            page_num = int(page_match.group(1))
            
            # 4-11 페이지 건너뛰기 (불필요한 페이지)
            if 4 <= page_num <= 11:
                continue
            
            md_path = os.path.join(md_folder, md_file)
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for line in lines:
                stripped = line.strip()
                match = section_pattern.match(stripped)
                
                if match:
                    hash_marks = match.group(1) or ''
                    section_id = match.group(2)
                    title = match.group(3).strip()
                    
                    # 레벨 계산 (# 개수 또는 점의 개수)
                    if hash_marks:
                        level = len(hash_marks.replace(' ', ''))
                    else:
                        level = len(section_id.split('.'))
                    
                    # 중복 체크
                    if section_id not in seen_sections:
                        seen_sections[section_id] = page_num
                        
                        structure.append({
                            "section_order": len(structure) + 1,
                            "level": level,
                            "section_id": section_id,
                            "section_key": f"{section_id} {title}",
                            "title": title,
                            "start_page": page_num,
                            "end_page": page_num,  # 나중에 업데이트
                            "page_count": 1
                        })
                        
                        logger.debug(f"Found section: {section_id} - {title} (Page {page_num})")
        
        # end_page 계산
        for i in range(len(structure)):
            if i < len(structure) - 1:
                structure[i]['end_page'] = structure[i+1]['start_page']
            else:
                # 마지막 섹션은 마지막 MD 파일까지
                if md_files:
                    last_file = md_files[-1]
                    last_match = re.search(r'page_(\d+)\.md', last_file)
                    if last_match:
                        structure[i]['end_page'] = int(last_match.group(1))
            
            structure[i]['page_count'] = structure[i]['end_page'] - structure[i]['start_page'] + 1
        
        logger.info(f"MD extraction successful. Total sections: {len(structure)}")
        return structure

    except Exception as e:
        logger.error(f"Error extracting from MD: {e}")
        return None


def extract_structure():
    """구조 추출 메인 함수 (TOC 우선, 없으면 MD에서 추출)"""
    
    # 1. TOC 메타데이터에서 추출 시도
    logger.info("=== Attempting TOC extraction ===")
    structure = extract_structure_from_toc()
    
    # 2. TOC 실패 시 MD 파일에서 추출
    if structure is None or len(structure) <= 1:
        logger.info("=== Falling back to MD extraction ===")
        structure = extract_structure_from_md()
    
    # 3. 결과 저장
    if structure and len(structure) > 0:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(structure, f, indent=4, ensure_ascii=False)
        
        logger.info(f"✅ Structure extracted to {output_path}. Total sections: {len(structure)}")
        
        if structure:
            logger.info(f"First Section: {structure[0]}")
            logger.info(f"Last Section: {structure[-1]}")
    else:
        logger.error("❌ Failed to extract structure from both TOC and MD files")


if __name__ == "__main__":
    extract_structure()
