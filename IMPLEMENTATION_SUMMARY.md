# TCG Parser - Implementation Summary

## 완료된 작업

### 1. PDF Structure Extraction 수정 (`step2_doc2toc_TCG.py`)
- ✅ 잘못된 섹션 필터링 (front matter 및 테이블 헤더)
- ✅ 페이지 스킵 범위를 argument로 변경 (`skip_pages` 파라미터)
- ✅ 기본값: `skip_pages=(2, 11)` - 페이지 2-11 건너뛰기

**결과:**
- 이전: 171개 섹션 (5개 잘못된 항목 포함)
- 현재: 168개 섹션 (모두 정상)

### 2. PDF to Text Extraction에 Crop 옵션 추가 (`step1_pdf2txt_TCG.py`)
- ✅ `USE_CROP` 설정 상수 추가 (파일 상단)
- ✅ `pdf_to_png()` 함수에 `use_crop` 파라미터 추가
- ✅ `process_page()` 및 `main()` 함수에 파라미터 전파
- ✅ 크롭 활성화 시: `png_crop/` 디렉토리에 저장
- ✅ 크롭 비활성화 시: `png_full/` 디렉토리에 저장

**테스트 결과:**
- Cropped image: 253,746 bytes
- Full image: 284,372 bytes
- Difference: 30,626 bytes (12.1% larger)

## 사용 방법

### step2_doc2toc_TCG.py
```python
# 기본값 사용 (페이지 2-11 건너뛰기)
extract_structure()

# 다른 범위 건너뛰기
extract_structure(skip_pages=(1, 5))

# 페이지 건너뛰기 없음
extract_structure(skip_pages=None)
```

### step1_pdf2txt_TCG.py
```python
# 파일 상단에서 설정 변경
USE_CROP = True   # 헤더/푸터 제거 (기본값)
# USE_CROP = False  # 전체 페이지 사용

# 또는 프로그래밍 방식으로
main(use_crop=True)   # 크롭 활성화
main(use_crop=False)  # 크롭 비활성화
```

## 생성된 파일
- `CROP_OPTION_GUIDE.md` - Crop 옵션 사용 가이드
- `test_crop_option.py` - Crop 옵션 테스트 스크립트
- `example_usage.py` - step2 사용 예시

## 검증 완료
- ✅ step2: PDF structure extraction 정상 작동 (168개 섹션)
- ✅ step1: Crop 옵션 테스트 통과 (모든 테스트 성공)
