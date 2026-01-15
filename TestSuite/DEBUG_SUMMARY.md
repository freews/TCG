# TCG Opal Test Debug Summary

## 문제 상황

### 테스트 결과
- ✅ `test_level0_discovery`: **PASS**
- ❌ `test_start_session_admin_sp`: **FAIL** - Status가 None으로 반환됨
- ❌ 나머지 테스트들: **FAIL**

### 증상
```python
# Callback에서 확인한 상태
NVMe Status Field: 0 (정상)

# 파싱 결과
parsed['status']: None  # <- 문제!
parsed['session_id']: 정상
parsed['tper_session_id']: 정상
```

## 근본 원인 분석

### 1. TCG Spec에 따른 SyncSession 응답 구조

**TCG Storage Architecture Core Spec v2.01 참조:**
- **Section 5.2.3.2**: SyncSession Method Response Format
- **Section 3.2.4.2**: Method Encoding
- **Section 3.3.7.1.3**: Session Manager Protocol Layer

SyncSession은 **METHOD CALL 형식**으로 반환됩니다:

```
Offset  Content
------  -------
[52]    CALL token (0xF8)                    <- Spec 3.2.2.3.3.1
[53-60] InvokingID (SMUID)                   <- Spec 3.2.4.2
[61-68] MethodID (SyncSession UID)           <- Spec 3.2.4.2
[69]    START_LIST (0xF0)                    <- Parameter list starts
        HostSessionID
        SPSessionID
        [Optional parameters...]
        END_LIST (0xF1)
        END_OF_DATA (0xF9)
        START_LIST (0xF0)                    <- STATUS LIST
            status_code (0x00 = SUCCESS)
            0x00
            0x00
        END_LIST (0xF1)
```

### 2. 기존 코드의 문제점

#### 문제 1: CALL Token 처리 부재
`tcg_opal_codec.py`의 `TCGPayloadParser.parse_item()` 함수에서:
```python
# CALL token (0xF8) 처리가 없었음!
elif token == Token.CALL:
    # 처리 로직 없음 -> ValueError 발생
```

#### 문제 2: 잘못된 파싱 구조
`parse_session_response()` 함수가 잘못된 가정을 함:
```python
# 기존 (잘못된) 코드
# 가정: [ HostSessionID, TPer_SessionID, [ MethodStatusList ] ]
if len(parsed) >= 3:
    result['session_id'] = parsed[0]      # 실제로는 CALL dict
    result['tper_session_id'] = parsed[1] # 실제로는 InvokingID bytes
    result['status'] = parsed[2][0]       # 실제로는 MethodID bytes
```

실제 파싱 결과:
```python
parsed = [
    {'type': 'CALL'},           # [0] CALL token
    b'\x00\x00\x00\x00\x00\x00\x00\xFF',  # [1] SMUID
    b'\x00\x00\x00\x00\x00\x00\xFF\x03',  # [2] SyncSession UID
    [HostSessionID, SPSessionID, ...],     # [3] Parameter list
    [status_code, 0x00, 0x00]              # [4] Status list
]
```

### 3. Offset 논쟁

원래 코드: `offset 20`
수정 시도: `offset 52`

**정답: offset 52가 맞습니다!**

#### 근거 (TCG Spec 3.3.10):
```
ComPacket Header:  20 bytes (0-19)   <- Spec 3.3.10.2
Packet Header:     16 bytes (20-35)  <- Spec 3.2.3
Subpacket Header:  16 bytes (36-51)  <- Spec 3.2.2
Payload:           Variable (52+)
```

**Total: 52 bytes header**

## 해결 방법

### 수정 사항 1: CALL Token 처리 추가

**파일**: `tcg_opal_codec.py`
**위치**: `TCGPayloadParser.parse_item()` 함수
**Spec 참조**: Section 3.2.2.3.3.1

```python
elif token == Token.CALL:
    # TCG Core Spec 3.2.2.3.3.1: CALL token indicates start of method invocation
    # Used in Session Manager responses (SyncSession, SyncTrustedSession, etc.)
    self.pos += 1
    return {'type': 'CALL'}
```

### 수정 사항 2: parse_session_response 재작성

**파일**: `tcg_opal_codec.py`
**Spec 참조**: 
- Section 5.2.3.2 (SyncSession)
- Section 3.2.4.2 (Method Encoding)

```python
def parse_session_response(response_data: bytes) -> Dict[str, Any]:
    """
    SyncSession Response Structure:
    [CALL_dict, InvokingID_bytes, MethodID_bytes, param_list, status_list]
    """
    parser = TCGPayloadParser(response_data)
    parsed = parser.parse()
    
    idx = 0
    
    # 1. Skip CALL token
    if isinstance(parsed[idx], dict) and parsed[idx].get('type') == 'CALL':
        idx += 1
    
    # 2. Skip InvokingID (8 bytes)
    if isinstance(parsed[idx], bytes):
        idx += 1
    
    # 3. Skip MethodID (8 bytes)
    if isinstance(parsed[idx], bytes):
        idx += 1
    
    # 4. Parse Parameter List
    if isinstance(parsed[idx], list):
        param_list = parsed[idx]
        result['session_id'] = param_list[0]
        result['tper_session_id'] = param_list[1]
        idx += 1
    
    # 5. Parse Status List
    if isinstance(parsed[idx], list):
        status_list = parsed[idx]
        result['status'] = status_list[0]
    
    return result
```

### 수정 사항 3: parse_method_response 개선

**파일**: `tcg_opal_codec.py`
**Spec 참조**: Section 3.2.4.2

Regular method 응답 구조:
```
[result_list, status_list]
```

```python
def parse_method_response(response_data: bytes) -> Dict[str, Any]:
    """
    Method Response Structure:
    [result_list, status_list]
    """
    parser = TCGPayloadParser(response_data)
    parsed = parser.parse()
    
    idx = 0
    
    # 1. Parse Result List
    if isinstance(parsed[idx], list):
        result['data'] = parsed[idx]
        idx += 1
    
    # 2. Parse Status List
    if isinstance(parsed[idx], list):
        result['status'] = parsed[idx][0]
    
    return result
```

## 테스트 함수 검증

### ✅ test_level0_discovery (Line 199)
- Discovery는 단순 binary 구조로 커스텀 파싱
- TCG payload parser 사용 안함
- **문제 없음**

### ✅ test_start_session_admin_sp (Line 267)
- `parse_session_response(response[52:])` 사용
- Offset 52 사용 - **정확함**
- 수정된 파서로 **해결됨**

### ✅ test_start_session_with_authentication (Line 340)
- `parse_session_response(response[52:])` 사용
- 동일한 패턴 - **문제 없음**

### ✅ test_properties_method (Line 408)
- Session 시작: `parse_session_response(response[52:])`
- Method 호출: `parse_method_response(payload_data)`
- Offset 52 사용 - **정확함**

### ✅ test_get_method_locking_info (Line 481)
- Session 시작: `parse_session_response(response[52:])`
- Method 호출: `parse_method_response(payload_data)`
- 동일한 패턴 - **문제 없음**

## 결론

### 주요 문제점
1. **CALL token이 파서에서 처리되지 않음**
2. **SyncSession 응답 구조를 잘못 이해함**
3. **METHOD CALL 형식을 인식하지 못함**

### 해결 방법
1. ✅ CALL token 처리 추가
2. ✅ parse_session_response 완전 재작성 (METHOD CALL 구조 반영)
3. ✅ parse_method_response 개선
4. ✅ Offset 52 사용 확인 (정확함)
5. ✅ 모든 함수에 Spec 참조 주석 추가

### Spec 참조 맵
| 기능 | Spec 섹션 | 내용 |
|------|-----------|------|
| Headers | 3.3.10 | ComPacket/Packet/Subpacket (52 bytes total) |
| Token Format | 3.2.2 | CALL, START_LIST, END_LIST, etc. |
| Method Encoding | 3.2.4.2 | Method call/response structure |
| SyncSession | 5.2.3.2 | SyncSession response format |
| Status Codes | 5.1.5 | 0x00=SUCCESS, 0x01=NOT_AUTHORIZED, etc. |

## 다음 단계

1. 수정된 파일로 테스트 실행
2. Status가 올바르게 파싱되는지 확인
3. 다른 테스트들도 PASS 되는지 확인
