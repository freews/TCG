# Step1 PDF2TXT - Crop Option 사용 가이드

## 개요

`step1_pdf2txt_TCG.py`는 이제 헤더/푸터 크롭(crop) 적용 여부를 선택할 수 있습니다.

## 설정 방법

### 방법 1: 설정 상수 변경 (권장)

파일 상단의 `USE_CROP` 상수를 수정하세요:

```python
# Crop 설정: True이면 헤더/푸터 제거, False이면 전체 페이지 사용
USE_CROP = True   # 헤더/푸터 제거 (기본값)
# USE_CROP = False  # 전체 페이지 사용
```

### 방법 2: 프로그래밍 방식

직접 함수를 호출할 때 파라미터로 지정:

```python
from step1_pdf2txt_TCG import main

# 크롭 활성화
main(use_crop=True)

# 크롭 비활성화
main(use_crop=False)
```

## 동작 차이

### Crop 활성화 (`USE_CROP = True`)
- **헤더/푸터 제거**: 상단 180px, 하단 100px 크롭
- **출력 디렉토리**: `./tcg_output/png_crop/`
- **용도**: 문서 본문만 추출하고 싶을 때

### Crop 비활성화 (`USE_CROP = False`)
- **전체 페이지 사용**: 크롭 없음
- **출력 디렉토리**: `./tcg_output/png_full/`
- **용도**: 헤더/푸터 정보도 필요할 때

## 실행 예시

```bash
# 기본 실행 (USE_CROP 설정 사용)
python3 step1_pdf2txt_TCG.py
```

실행 시 콘솔에 현재 설정이 표시됩니다:

```
======================================================================
TCG PARSER - ULTRA SIMPLE VERSION
Crop Mode: ENABLED (header/footer removed)
======================================================================
```

또는

```
======================================================================
TCG PARSER - ULTRA SIMPLE VERSION
Crop Mode: DISABLED (full page)
======================================================================
```

## 출력 파일

- **마크다운 파일**: `./tcg_output/md/page_XXXX.md` (동일)
- **PNG 파일** (크롭 활성화): `./tcg_output/png_crop/page_XXXX.png`
- **PNG 파일** (크롭 비활성화): `./tcg_output/png_full/page_XXXX.png`
