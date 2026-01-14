# TCG Opal SSC v2.30 종합 테스트 스위트

실제 NVMe SSD에서 TCG Opal 기능을 검증하는 완전한 테스트 스위트

## 📦 파일 구조

```
tcg_opal_codec.py              # Protocol 인코딩/디코딩
test_tcg_opal_comprehensive.py # 종합 테스트 스위트
conftest.py                    # pytest 설정 (ssd_h fixture)
```

## ✨ 주요 기능

### 1. **완전한 Protocol 구현**
- Token 인코딩/디코딩
- Payload 빌더
- Response 파서
- ComPacket 생성

### 2. **실제 작동하는 테스트**
- ✅ Level 0 Discovery 파싱
- ✅ Session 생성 및 응답 파싱
- ✅ Method 호출 (Properties, Get, Set)
- ✅ Authentication (PIN hash)
- ✅ 모든 주석 제거 - 실제 구현

### 3. **pynvme API 사용**
```python
# Security Send
controller.send_cmd(
    opcode=0x81,              # Security Send
    nsid=0,
    cdw10=(protocol << 24) | (com_id << 8),
    cdw11=len(data),
    buf=buffer
)

# Security Receive
controller.send_cmd(
    opcode=0x82,              # Security Receive
    ...
)
```

## 🚀 사용법

### 1. 설치

```bash
pip install pynvme pytest
```

### 2. conftest.py 확인

```python
# conftest.py
import pytest

@pytest.fixture(scope="function")  # ← 중요: function scope
def ssd_h():
    """pynvme Controller - 각 테스트마다 새로운 인스턴스"""
    import nvme as d
    
    # NVMe Controller 초기화
    nvme0 = d.Controller(b"/dev/nvme0")
    
    yield nvme0
    
    # Cleanup (각 테스트 후)
    nvme0.close()
```

**Scope 선택:**
- `scope="function"`: 각 테스트마다 새 controller (권장) ✓
  - 테스트 간 독립성 보장
  - Session state 격리
- `scope="module"`: 전체 테스트에서 하나의 controller 공유 (위험)
  - Session 충돌 가능
  - State 오염

### 3. 테스트 실행

```bash
# 전체 테스트
pytest test_tcg_opal_comprehensive.py -v

# 특정 테스트만
pytest test_tcg_opal_comprehensive.py::TestTCGOpalComprehensive::test_level0_discovery -v -s

# Discovery만
pytest -k "discovery" -v -s

# Session 관련만
pytest -k "session" -v -s
```

## 📊 테스트 항목

### Level 0 Discovery
```python
def test_level0_discovery(self, ssd_h):
    """TPer 기능 발견 및 파싱"""
    
    # Security Send/Receive 실행
    # 응답 파싱:
    # - Header (version, length)
    # - Features (TPer, Locking, Opal SSC, etc.)
```

**출력 예시:**
```
✓ Discovery Header:
  Version: 2.0
  Total Length: 256 bytes
  Features found: 5
  - TPer: version 1, 16 bytes
  - Locking: version 1, 12 bytes
  - Opal SSC V2: version 1, 16 bytes
```

### Session Management
```python
def test_start_session_admin_sp(self, ssd_h):
    """Admin SP 세션 시작 (비인증)"""
    
    # StartSession payload 생성
    # Security Send/Receive
    # 응답에서 Session ID 추출 ← 실제 구현!
```

**출력 예시:**
```
✓ Session Started:
  Host Session ID:  1
  TPer Session ID:  4096
  Status:           0 (Success)
```

### Authentication
```python
def test_start_session_with_authentication(self, ssd_h):
    """SID로 인증하여 세션 시작"""
    
    # PIN hash 생성 (SHA256)
    # HostChallenge, HostSigningAuthority 포함
    # 응답 파싱
```

### Method Calls
```python
def test_properties_method(self, ssd_h):
    """Properties Method 호출"""
    
    # Method payload 생성
    # MaxComPacketSize 등 조회
    # 응답 파싱

def test_get_method_locking_info(self, ssd_h):
    """Get Method로 Locking Info 조회"""
    
    # Get Method payload
    # Table 데이터 조회
```

## 🔧 핵심 구현

### 1. Payload Builder

```python
from tcg_opal_codec import TCGPayloadBuilder, UID

builder = TCGPayloadBuilder()

# Method 호출 구조
builder.add_call()
builder.add_uid(UID.SM_UID)           # InvokingID
builder.add_uid(UID.START_SESSION)    # MethodID

# Parameters
builder.start_list()
builder.add_integer(host_session_id)
builder.add_uid(sp_uid)
builder.add_integer(1)  # Write
builder.end_list()

builder.add_end_of_data()

payload = builder.get_payload()
```

### 2. Response Parser

```python
from tcg_opal_codec import TCGResponseParser

# ComPacket 헤더 제거 (20 bytes)
payload_data = response[20:]

# Session 응답 파싱
parsed = TCGResponseParser.parse_session_response(payload_data)

print(f"Session ID: {parsed['session_id']}")
print(f"TPer Session ID: {parsed['tper_session_id']}")
print(f"Status: {parsed['status']}")

# Method 응답 파싱
parsed = TCGResponseParser.parse_method_response(payload_data)

print(f"Status: {parsed['status']}")
print(f"Data: {parsed['data']}")
```

### 3. Discovery Parser

```python
discovery = parse_discovery(response_data)

for feature in discovery['features']:
    print(f"Feature {feature['code']:04X}: {feature['length']} bytes")
```

## 📖 실제 사용 예시

### 전체 워크플로우

```python
# 1. Discovery
pytest test_tcg_opal_comprehensive.py::test_level0_discovery -s

# 2. Session 시작 (비인증)
pytest test_tcg_opal_comprehensive.py::test_start_session_admin_sp -s

# 3. Properties 조회
pytest test_tcg_opal_comprehensive.py::test_properties_method -s

# 4. Locking Info 조회
pytest test_tcg_opal_comprehensive.py::test_get_method_locking_info -s
```

### SID 인증 (Manual)

```python
# MSID 값 확인 (드라이브 label)
msid = "YOUR_MSID_HERE"

# test_start_session_with_authentication에서
# msid_password = msid 로 변경

pytest test_tcg_opal_comprehensive.py::test_start_session_with_authentication -s
```

## ⚠️ 주의사항

### 안전한 테스트
```python
# 읽기 전용 (안전)
✓ test_level0_discovery
✓ test_start_session_admin_sp
✓ test_properties_method
✓ test_get_method_locking_info

# 위험 (Skip 처리됨)
⚠️ test_revert_tper          # 전체 초기화!
⚠️ test_activate_locking_sp  # SP 활성화
```

### Skip된 테스트 실행

```python
# Skip 제거하고 실행 (주의!)
# pytest.skip() 라인 주석 처리

pytest test_tcg_opal_comprehensive.py::test_revert_tper -s
```

## 🔍 디버깅

### Verbose 출력

```bash
pytest test_tcg_opal_comprehensive.py -v -s --tb=short
```

### 특정 테스트 디버그

```python
# test 함수에 추가
import pdb; pdb.set_trace()

# 또는
print(f"Response data: {response_data.hex()}")
print(f"Parsed: {parsed}")
```

### 응답 Hex Dump

```python
# Response 전체 확인
print(f"Response ({len(response_data)} bytes):")
print(' '.join(f'{b:02X}' for b in response_data))
```

## 📚 참고 문서

- **TCG Opal SSC v2.30**: `/mnt/project/TCG-Storage-Opal-SSC-v2_30_pub.pdf`
- **pynvme API**: https://github.com/pynvme/pynvme/blob/master/doc/api.rst
- **NVMe Spec 2.3**: `/mnt/project/NVM-Express-Base-Specification-Revision-2_3-2025_08_01-Ratified.pdf`

## 🎯 다음 단계

### 추가 구현 필요

```python
# 1. CloseSession
def test_close_session(self, ssd_h):
    # CloseSession Method 구현
    pass

# 2. Locking 설정
def test_configure_locking_range(self, ssd_h):
    # Locking Range 설정
    pass

# 3. 암호화 키 생성
def test_generate_encryption_key(self, ssd_h):
    # GenKey Method
    pass
```

### 통합 시나리오

```python
# Full lifecycle test
def test_full_opal_lifecycle(self, ssd_h):
    # 1. Discovery
    # 2. Activate Locking SP
    # 3. Create Admin
    # 4. Set Locking Range
    # 5. Lock/Unlock
    # 6. Revert (optional)
    pass
```

---

**실제 제품 테스트 가능!** 🚀
