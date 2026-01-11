#!/usr/bin/env python3
"""
step2_doc2toc_TCG.py 사용 예시

이 스크립트는 skip_pages 파라미터를 사용하는 방법을 보여줍니다.
"""

from step2_doc2toc_TCG import extract_structure

# 예시 1: 기본값 사용 (페이지 2-11 건너뛰기)
print("=== Example 1: Default (skip pages 2-11) ===")
extract_structure()

# 예시 2: 다른 페이지 범위 건너뛰기 (페이지 1-5)
# print("\n=== Example 2: Skip pages 1-5 ===")
# extract_structure(skip_pages=(1, 5))

# 예시 3: 페이지 건너뛰기 없음
# print("\n=== Example 3: No pages skipped ===")
# extract_structure(skip_pages=None)
