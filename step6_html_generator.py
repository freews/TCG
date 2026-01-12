import json
from pathlib import Path
from typing import List, Dict, Optional
import markdown
import re


class HTMLGenerator:
    """section_content.json을 사용해 인터랙티브 HTML 생성"""
    
    def __init__(self, 
                 json_file: str = "./tcg_output/section_content.json",
                 output_dir: str = "./tcg_output/html"):
        
        self.json_file = Path(json_file)
        self.output_dir = Path(output_dir)
        
        # 디렉토리 생성
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # JSON 데이터 로드
        with open(self.json_file, "r", encoding="utf-8") as f:
            self.sections = json.load(f)
    
    def markdown_to_html(self, md_text: str) -> str:
        """마크다운을 HTML로 변환"""
        if not md_text:
            return ""
        return markdown.markdown(
            md_text,
            extensions=['tables', 'fenced_code', 'codehilite', 'nl2br', 'sane_lists']
        )
    
    def get_section_hierarchy(self) -> List[Dict]:
        """섹션을 계층 구조로 변환"""
        hierarchy = []
        
        for section in self.sections:
            section_id = section.get("section_id", "")
            section_key = section.get("section_key", "")
            title = section.get("title", "")
            level = section.get("level", 1)
            start_page = section.get("start_page", 0)
            end_page = section.get("end_page", 0)
            
            # 안전한 ID 생성 (section_id가 비어있으면 section_key 사용)
            if section_id:
                safe_id = str(section_id).replace(".", "_")
            else:
                safe_id = str(section_key).replace(" ", "_").replace(".", "_")
            
            hierarchy.append({
                "number": section_id if section_id else section_key,
                "title": title,
                "level": level,
                "start_page": start_page,
                "end_page": end_page,
                "id": safe_id
            })
        
        return hierarchy
    
    def create_section_sidebar_html(self, hierarchy: List[Dict], current_section_id: str = None) -> str:
        """좌측 섹션 리스트 HTML 생성 (폴딩 구조)"""
        html = '<ul class="section-tree">'
        
        prev_level = 0
        for item in hierarchy:
            level = item['level']
            section_id = item['id']
            number = item['number']
            title = item['title']
            
            # 레벨 변경 처리
            if level > prev_level:
                html += '<ul class="subsection">'
            elif level < prev_level:
                for _ in range(prev_level - level):
                    html += '</ul></li>'
            elif prev_level > 0:
                html += '</li>'
            
            # 현재 섹션 하이라이트
            active_class = ' class="active"' if section_id == current_section_id else ''
            
            html += f'''
            <li{active_class}>
                <div class="section-item" onclick="loadSection('{section_id}')">
                    <span class="section-number">{number}</span>
                    <span class="section-title">{title}</span>
                </div>
            '''
            
            prev_level = level
        
        # 닫는 태그들
        for _ in range(prev_level):
            html += '</ul></li>'
        
        html += '</ul>'
        return html
    
    def create_main_html(self):
        """메인 index.html 생성"""
        hierarchy = self.get_section_hierarchy()
        
        # about_this_document.txt 파일 확인 및 Section 0 추가
        about_file = self.output_dir / "about_this_document.txt"
        has_about_section = about_file.exists()
        
        if has_about_section:
            # Section 0을 hierarchy 맨 앞에 추가
            about_section = {
                "number": "0",
                "title": "About This Document",
                "level": 1,
                "start_page": 0,
                "end_page": 0,
                "id": "section_0"
            }
            hierarchy.insert(0, about_section)
        
        sidebar_html = self.create_section_sidebar_html(hierarchy)
        
        # 섹션별 데이터를 JSON으로 생성
        sections_data = {}
        
        # Section 0 추가 (about_this_document.txt 내용)
        if has_about_section:
            try:
                with open(about_file, 'r', encoding='utf-8') as f:
                    about_content = f.read()
                sections_data["section_0"] = {
                    "number": "0",
                    "title": "About This Document",
                    "pages": "-",
                    "summary": self.markdown_to_html(about_content),
                    "page_images": []
                }
            except Exception as e:
                print(f"⚠️  Warning: Could not read about_this_document.txt: {e}")
        
        for section in self.sections:
            section_id = section.get("section_id", "")
            section_key = section.get("section_key", "")
            
            # 안전한 ID 생성
            if section_id:
                safe_id = str(section_id).replace(".", "_")
            else:
                safe_id = str(section_key).replace(" ", "_").replace(".", "_")
            
            # summary 추출
            summary = section.get("summary", "")
            
            # 페이지 정보
            start_page = section.get("start_page", 0)
            end_page = section.get("end_page", 0)
            
            # 페이지 이미지 경로 생성 (html/PNG 디렉토리 사용)
            page_images = []
            for page_num in range(start_page, end_page + 1):
                page_filename = f"page_{page_num:04d}.png"
                page_images.append({
                    "page_num": page_num,
                    "path": f"PNG/{page_filename}"
                })
            
            sections_data[safe_id] = {
                "number": section_id if section_id else section_key,
                "title": section.get("title", ""),
                "pages": f"{start_page}-{end_page}",
                "summary": self.markdown_to_html(summary),
                "page_images": page_images
            }
        
        
        # JSON 데이터를 JavaScript 변수로
        sections_json = json.dumps(sections_data, ensure_ascii=False, indent=2)
        
        html_content = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TCG Storage Opal SSC 문서</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
            background: white;
        }}
        
        /* 좌측 사이드바 */
        .sidebar {{
            width: 350px;
            background: #f8f9fa;
            border-right: 1px solid #dee2e6;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        
        .sidebar-header {{
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        
        .sidebar-header h1 {{
            font-size: 1.5em;
            margin-bottom: 10px;
        }}
        
        .search-box {{
            padding: 15px;
            background: white;
            border-bottom: 1px solid #dee2e6;
        }}
        
        .search-box input {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ced4da;
            border-radius: 5px;
            font-size: 14px;
        }}
        
        .section-list {{
            flex: 1;
            overflow-y: auto;
            padding: 10px;
        }}
        
        .section-tree {{
            list-style: none;
        }}
        
        .subsection {{
            list-style: none;
            margin-left: 20px;
        }}
        
        .section-item {{
            padding: 10px;
            cursor: pointer;
            border-radius: 5px;
            margin: 2px 0;
            transition: background 0.2s;
            display: flex;
            align-items: center;
        }}
        
        .section-item:hover {{
            background: #e9ecef;
        }}
        
        .section-tree > li.active > .section-item,
        .subsection > li.active > .section-item {{
            background: #667eea;
            color: white;
        }}
        
        .section-number {{
            background: #667eea;
            color: white;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            margin-right: 10px;
            min-width: 50px;
            text-align: center;
        }}
        
        .active .section-number {{
            background: white;
            color: #667eea;
        }}
        
        .section-title {{
            flex: 1;
            font-size: 14px;
        }}
        
        /* 메인 컨텐츠 */
        .main-content {{
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        
        .content-header {{
            padding: 20px 30px;
            background: white;
            border-bottom: 2px solid #e9ecef;
        }}
        
        .content-header h2 {{
            color: #2c3e50;
            margin-bottom: 5px;
        }}
        
        .content-meta {{
            color: #6c757d;
            font-size: 14px;
        }}
        
        .content-body {{
            flex: 1;
            overflow-y: auto;
            padding: 30px;
        }}
        
        .summary-section {{
            background: #f0f8ff;
            padding: 25px;
            border-left: 4px solid #667eea;
            border-radius: 5px;
            margin-bottom: 30px;
        }}
        
        .summary-section h3 {{
            color: #2980b9;
            margin-bottom: 15px;
        }}
        
        .content-section {{
            margin-top: 30px;
        }}
        
        .content-section h3 {{
            color: #2c3e50;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e9ecef;
        }}
        
        /* 페이지 이미지 스타일 */
        .page-image {{
            margin: 30px 0;
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        
        .page-image h4 {{
            color: #495057;
            margin-bottom: 15px;
            font-size: 1.1em;
        }}
        
        .page-image img {{
            width: 100%;
            height: auto;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            cursor: pointer;
            transition: transform 0.2s;
        }}
        
        .page-image img:hover {{
            transform: scale(1.02);
        }}

        
        /* 표 스타일 */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        
        th {{
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
        }}
        
        td {{
            padding: 10px;
            border: 1px solid #dee2e6;
        }}
        
        tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        
        /* 코드 스타일 */
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        
        /* 웰컴 메시지 */
        .welcome {{
            text-align: center;
            padding: 50px;
            color: #6c757d;
        }}
        
        .welcome h2 {{
            color: #667eea;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <!-- 좌측 사이드바 -->
    <div class="sidebar">
        <div class="sidebar-header">
            <h1>📚 TCG Opal SSC</h1>
            <p>섹션별 요약 및 내용</p>
        </div>
        
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="🔍 섹션 검색..." onkeyup="searchSections()">
        </div>
        
        <div class="section-list" id="sectionList">
            {sidebar_html}
        </div>
    </div>
    
    <!-- 메인 컨텐츠 -->
    <div class="main-content">
        <div class="content-header" id="contentHeader">
            <h2>TCG Storage Opal SSC v2.30</h2>
            <div class="content-meta">좌측 목차에서 섹션을 선택하세요</div>
        </div>
        
        <div class="content-body" id="contentBody">
            <div class="welcome">
                <h2>환영합니다!</h2>
                <p>좌측 목차에서 섹션을 선택하면 요약과 내용을 볼 수 있습니다.</p>
                <p style="margin-top: 20px; color: #999;">← → 키로 섹션 이동 가능</p>
            </div>
        </div>
    </div>
    
    <script>
        // 섹션 데이터
        const sectionsData = {sections_json};
        
        // 현재 섹션 추적 변수
        let currentSectionId = null;
        let sectionKeys = [];
        
        // 섹션 로드
        function loadSection(sectionId) {{
            const data = sectionsData[sectionId];
            if (!data) return;
            
            currentSectionId = sectionId;
            
            // 헤더 업데이트
            document.getElementById('contentHeader').innerHTML = `
                <h2>${{data.number}} ${{data.title}}</h2>
                <div class="content-meta">Pages: ${{data.pages}}</div>
            `;
            
            // 요약 HTML 생성
            let summaryHtml = '';
            if (data.summary) {{
                summaryHtml = `
                    <div class="summary-section">
                        <h3>📝 요약</h3>
                        <div>${{data.summary}}</div>
                    </div>
                `;
            }}
            
            // 페이지 이미지 HTML 생성
            let imagesHtml = '';
            if (data.page_images && data.page_images.length > 0) {{
                imagesHtml = '<div class="content-section"><h3>📄 원본 페이지</h3>';
                data.page_images.forEach(img => {{
                    imagesHtml += `
                        <div class="page-image">
                            <h4>Page ${{img.page_num}}</h4>
                            <img src="${{img.path}}" alt="Page ${{img.page_num}}" onclick="openImage('${{img.path}}')">
                        </div>
                    `;
                }});
                imagesHtml += '</div>';
            }}
            
            // 컨텐츠 업데이트
            document.getElementById('contentBody').innerHTML = summaryHtml + imagesHtml;
            
            // 사이드바 active 상태 업데이트
            document.querySelectorAll('.section-tree li').forEach(li => li.classList.remove('active'));
            document.querySelectorAll('.subsection li').forEach(li => li.classList.remove('active'));
            
            const activeItems = document.querySelectorAll(`[onclick="loadSection('${{sectionId}}')"]`);
            activeItems.forEach(item => item.parentElement.classList.add('active'));
            
            // 컨텐츠를 맨 위로 스크롤
            document.getElementById('contentBody').scrollTop = 0;
        }}
        
        // 이미지 새 탭에서 열기
        function openImage(path) {{
            window.open(path, '_blank');
        }}

        
        // 이전/다음 섹션으로 이동
        function navigateSection(direction) {{
            if (!currentSectionId || sectionKeys.length === 0) return;
            
            const currentIndex = sectionKeys.indexOf(currentSectionId);
            let newIndex;
            
            if (direction === 'prev') {{
                newIndex = currentIndex - 1;
                if (newIndex < 0) newIndex = sectionKeys.length - 1;
            }} else {{
                newIndex = currentIndex + 1;
                if (newIndex >= sectionKeys.length) newIndex = 0;
            }}
            
            loadSection(sectionKeys[newIndex]);
        }}
        
        // 키보드 이벤트
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'ArrowLeft') {{
                e.preventDefault();
                navigateSection('prev');
            }} else if (e.key === 'ArrowRight') {{
                e.preventDefault();
                navigateSection('next');
            }}
        }});
        
        // 검색 기능
        function searchSections() {{
            const input = document.getElementById('searchInput');
            const filter = input.value.toLowerCase().trim();
            
            const allItems = document.querySelectorAll('.section-tree li, .subsection li');
            
            if (filter === '') {{
                allItems.forEach(li => {{
                    li.style.display = '';
                }});
                return;
            }}
            
            allItems.forEach(li => {{
                li.style.display = 'none';
            }});
            
            document.querySelectorAll('.section-item').forEach(item => {{
                const number = item.querySelector('.section-number').textContent.toLowerCase();
                const title = item.querySelector('.section-title').textContent.toLowerCase();
                const fullText = number + ' ' + title;
                
                if (fullText.indexOf(filter) > -1) {{
                    const li = item.parentElement;
                    li.style.display = '';
                    
                    let parent = li.parentElement;
                    while (parent && parent.tagName === 'UL') {{
                        parent.style.display = '';
                        if (parent.parentElement && parent.parentElement.tagName === 'LI') {{
                            parent.parentElement.style.display = '';
                        }}
                        parent = parent.parentElement.parentElement;
                    }}
                }}
            }});
        }}
        
        // 첫 번째 섹션 자동 로드
        window.onload = function() {{
            sectionKeys = Object.keys(sectionsData);
            const firstSection = sectionKeys[0];
            if (firstSection) {{
                loadSection(firstSection);
            }}
        }};
    </script>
</body>
</html>
'''
        
        # index.html 저장
        output_file = self.output_dir / "index.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print(f"✅ HTML generated: {output_file}")
        print(f"📁 Total sections: {len(sections_data)}")
        
        return output_file


# 실행
if __name__ == "__main__":
    generator = HTMLGenerator(
        json_file="./tcg_output/section_content.json",
        output_dir="./tcg_output/html"
    )
    
    html_file = generator.create_main_html()
    
    print(f"\n🚀 서버 시작 방법:")
    print(f"   cd {generator.output_dir}")
    print(f"   python3 -m http.server 8000")
    print(f"\n📖 브라우저에서 http://localhost:8000/index.html 접속")
