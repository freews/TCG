import json
import requests
import os
import logging
import time

# --- Configuration ---
INPUT_JSON = "./tcg_output/section_content.json"
OUTPUT_JSON = "./tcg_output/section_content.json"  # Save back to the same file
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen3-vl:32b-instruct-q4_K_M"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def format_tables_for_prompt(table_names, table_data):
    """테이블들을 프롬프트용 텍스트로 변환"""
    if not table_names:
        return ""
    
    formatted = "\n\n### 테이블:\n"
    for i, name in enumerate(table_names):
        formatted += f"\n**{name}:**\n"
        if i < len(table_data):
            # 테이블의 각 행을 연결
            table_rows = table_data[i]
            formatted += "\n".join(table_rows[:50])  # 최대 50행까지만
            if len(table_rows) > 50:
                formatted += f"\n... (총 {len(table_rows)}개 행)"
        formatted += "\n"
    
    return formatted

def generate_summary(section_data):
    """섹션 데이터(content + tables + images)를 기반으로 한국어 요약 생성"""
    
    section_title = section_data.get('title', 'Unknown')
    section_id = section_data.get('section_id', 'Unknown')
    content = section_data.get('content_md', '')
    table_names = section_data.get('section_table_list', [])
    table_data = section_data.get('section_table', [])
    image_names = section_data.get('section_image_name_list', [])
    images_base64 = section_data.get('section_image', [])
    
    # 콘텐츠가 너무 짧으면 그대로 반환
    total_content_length = len(content) + sum(len(str(t)) for t in table_data)
    if total_content_length < 200:
        return content if content else "(내용 없음)"
    
    # 프롬프트 구성
    prompt = f"""당신은 TCG/OPAL 보안 전문가입니다.
TCG-Storage-Opal-SSC-v2.30_pub.pdf 문서의 내용을 section 별로 제공합니다.
섹션: {section_id} - {section_title}

아래 내용을 검토하고 이 분야 초보자에게 설명하듯이 자세히 설명해주세요.
목적, 주요 기능, 데이터 구조, 요구사항, 보안 메커니즘에 초점을 맞춰주세요.

문서에서 언급한 spec을 검증할 수 있는 Test Case를 제시해주세요.
- Python과 pytest를 사용한 테스트 코드 예시
- TCG Opal 명령어(StartSession, Revert, etc.)를 사용한 검증 방법
- 테이블 데이터 검증 방법

section 내용이 없거나 설명할 사항이 없으면 "내용없음"으로 출력하세요.

### 본문:
{content[:10000]}

{format_tables_for_prompt(table_names, table_data)}

### 이미지:
"""
    
    if image_names:
        prompt += f"{len(image_names)}개의 이미지/다이어그램이 포함되어 있습니다: {', '.join(image_names)}\n"
    else:
        prompt += "이미지 없음\n"
    
    prompt += "\n요약 (한국어, 상세하게):"
    
    # 토큰 수 추정 (대략 1 토큰 = 4 글자)
    prompt_tokens = len(prompt) // 4
    logger.info(f"  📊 Prompt size: ~{prompt_tokens} tokens")
    
    # Vision 모델을 위한 payload 구성 (step1과 동일한 옵션)
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_ctx": 8192,        # 컨텍스트 윈도우 (메모리 안정성)
            "num_batch": 256,       # 배치 크기 (작을수록 안정적)
            "num_predict": 4096,    # 최대 생성 토큰 수
            "num_thread": 6         # CPU 스레드 수
        }
    }
    
    # 이미지가 있으면 추가 (최대 3개까지)
    if images_base64:
        payload["images"] = images_base64[:3]  # Vision 모델은 보통 여러 이미지 지원
        logger.info(f"  📷 Including {min(len(images_base64), 3)} images in summary request")
    
    try:
        # LLM 호출 (시간 측정)
        start_time = time.time()
        response = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=600)
        response.raise_for_status()
        process_time = time.time() - start_time
        
        result = response.json().get("response", "").strip()
        
        # 응답 토큰 수 추정
        response_tokens = len(result) // 4
        total_tokens = prompt_tokens + response_tokens
        logger.info(f"  📊 Response size: ~{response_tokens} tokens, Total context: ~{total_tokens} tokens")
        logger.info(f"  ⏱️  Processing time: {process_time:.1f}s")
        
        return result
    except Exception as e:
        logger.error(f"요약 생성 실패: {e}")
        return "요약 생성 실패."

def main():
    logger.info("=== STEP 4: 한국어 요약 생성 (Content + Tables + Images) ===")
    
    if not os.path.exists(INPUT_JSON):
        logger.error("입력 JSON 파일이 없습니다.")
        return

    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    total_sections = len(data)
    processed = 0
    skipped = 0
    
    for i, section in enumerate(data):
        t = section.get('title', 'Unknown')
        id = section.get('section_id', 'Unknown')
        start_page = section.get('start_page', 0)
        
        # Skip pages 4-11 (불필요한 페이지)
        if 4 <= start_page <= 11:
            logger.info(f"[{i+1}/{total_sections}] 건너뛰기: {id}:{t} (Page {start_page})")
            continue
        
        # 이미 요약된 경우 건너뛰기 (resume 기능)
        existing_summary = section.get('summary', '').strip()
        if existing_summary and existing_summary != "(내용 없음)":
            skipped += 1
            logger.info(f"[{i+1}/{total_sections}] ⏭️  이미 요약됨: {id}:{t}")
            continue

        # 요약 생성
        logger.info(f"[{i+1}/{total_sections}] 요약 생성 중: {id}:{t}")
        
        # 섹션 정보 출력
        num_tables = len(section.get('section_table_list', []))
        num_images = len(section.get('section_image_name_list', []))
        logger.info(f"  -> Tables: {num_tables}, Images: {num_images}")
        
        section['summary'] = generate_summary(section)
        processed += 1
        
        # 진행 상황 저장 (매 섹션마다 - 안전성 향상)
        temp_file = OUTPUT_JSON + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(temp_file, OUTPUT_JSON)
            logger.info(f"  💾 저장 완료 ({processed}개 섹션 처리됨)")
        except Exception as e:
            logger.error(f"저장 실패: {e}")

    # 최종 저장
    try:
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"✅ 완료. 모든 요약이 {OUTPUT_JSON}에 저장되었습니다.")
        logger.info(f"📊 통계: 새로 처리 {processed}개 | 이미 완료 {skipped}개 | 총 {processed + skipped}개")
    except Exception as e:
        logger.error(f"최종 저장 실패: {e}")

if __name__ == "__main__":
    main()
