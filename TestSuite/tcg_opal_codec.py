"""
TCG Opal Protocol Codec
=======================

Token 인코딩/디코딩 및 Payload 파싱
"""

import struct
from typing import List, Dict, Any, Tuple, Optional
from enum import IntEnum


# ==========================================
# Token Definitions (TCG Core Spec)
# ==========================================

class Token(IntEnum):
    """TCG Storage Token 정의"""
    # Atoms
    TINY_ATOM_START = 0x00      # 0x00-0x3F: Tiny Atom (unsigned)
    TINY_ATOM_SIGNED = 0x40     # 0x40-0x7F: Signed Tiny Atom
    SHORT_ATOM = 0x80           # 0x80-0xBF: Short Atom
    MEDIUM_ATOM = 0xC0          # 0xC0-0xDF: Medium Atom
    LONG_ATOM = 0xE0            # 0xE0-0xE3: Long Atom
    
    # Special tokens
    START_LIST = 0xF0           # List 시작
    END_LIST = 0xF1             # List 종료
    START_NAME = 0xF2           # Name 시작 (키-값 쌍)
    END_NAME = 0xF3             # Name 종료
    CALL = 0xF8                 # Method 호출
    END_OF_DATA = 0xF9          # 데이터 종료
    END_OF_SESSION = 0xFA       # 세션 종료
    START_TRANSACTION = 0xFB    # 트랜잭션 시작
    END_TRANSACTION = 0xFC      # 트랜잭션 종료
    EMPTY_ATOM = 0xFF           # 빈 Atom


# ==========================================
# Payload Builder
# ==========================================

class TCGPayloadBuilder:
    """TCG Payload 생성 헬퍼"""
    
    def __init__(self):
        self.payload = bytearray()
    
    def add_token(self, token: int) -> 'TCGPayloadBuilder':
        """Token 추가"""
        self.payload.append(token)
        return self
    
    def add_tiny_atom(self, value: int) -> 'TCGPayloadBuilder':
        """Tiny Atom 추가 (0-63)"""
        if 0 <= value <= 63:
            self.payload.append(value)
        else:
            raise ValueError(f"Tiny atom value out of range: {value}")
        return self
    
    def add_short_atom(self, data: bytes) -> 'TCGPayloadBuilder':
        """Short Atom 추가 (1-63 bytes)"""
        length = len(data)
        if 1 <= length <= 63:
            self.payload.append(Token.SHORT_ATOM | length)
            self.payload.extend(data)
        else:
            raise ValueError(f"Short atom length out of range: {length}")
        return self
    
    def add_medium_atom(self, data: bytes) -> 'TCGPayloadBuilder':
        """Medium Atom 추가 (64-2047 bytes)"""
        length = len(data)
        if 64 <= length <= 2047:
            # Medium atom: 110xxxxx xxxxxxxx
            byte1 = Token.MEDIUM_ATOM | ((length >> 8) & 0x1F)
            byte2 = length & 0xFF
            self.payload.extend([byte1, byte2])
            self.payload.extend(data)
        else:
            raise ValueError(f"Medium atom length out of range: {length}")
        return self
    
    def add_bytes(self, data: bytes) -> 'TCGPayloadBuilder':
        """바이트 데이터 추가 (길이에 따라 자동 선택)"""
        length = len(data)
        if length == 0:
            self.add_token(Token.EMPTY_ATOM)
        elif length <= 63:
            self.add_short_atom(data)
        elif length <= 2047:
            self.add_medium_atom(data)
        else:
            raise ValueError(f"Data too large: {length} bytes")
        return self
    
    def add_uid(self, uid: bytes) -> 'TCGPayloadBuilder':
        """UID 추가 (8 bytes)"""
        if len(uid) != 8:
            raise ValueError(f"UID must be 8 bytes, got {len(uid)}")
        return self.add_bytes(uid)
    
    def add_integer(self, value: int) -> 'TCGPayloadBuilder':
        """정수 추가"""
        if 0 <= value <= 63:
            # Tiny atom (unsigned)
            self.add_tiny_atom(value)
        elif -32 <= value <= 31:
            # Tiny atom (signed)
            if value >= 0:
                self.payload.append(Token.TINY_ATOM_SIGNED | value)
            else:
                self.payload.append(Token.TINY_ATOM_SIGNED | (value & 0x3F))
        else:
            # Short/Medium atom으로 인코딩
            if value >= 0:
                data = value.to_bytes((value.bit_length() + 7) // 8, 'big')
            else:
                # 음수는 2의 보수
                byte_count = (value.bit_length() + 8) // 8
                data = value.to_bytes(byte_count, 'big', signed=True)
            self.add_bytes(data)
        return self
    
    def start_list(self) -> 'TCGPayloadBuilder':
        """List 시작"""
        self.add_token(Token.START_LIST)
        return self
    
    def end_list(self) -> 'TCGPayloadBuilder':
        """List 종료"""
        self.add_token(Token.END_LIST)
        return self
    
    def start_name(self) -> 'TCGPayloadBuilder':
        """Name 시작"""
        self.add_token(Token.START_NAME)
        return self
    
    def end_name(self) -> 'TCGPayloadBuilder':
        """Name 종료"""
        self.add_token(Token.END_NAME)
        return self
    
    def add_call(self) -> 'TCGPayloadBuilder':
        """Method Call token"""
        self.add_token(Token.CALL)
        return self
    
    def add_end_of_data(self) -> 'TCGPayloadBuilder':
        """End of Data token"""
        self.add_token(Token.END_OF_DATA)
        return self
    
    def get_payload(self) -> bytes:
        """최종 Payload 반환"""
        return bytes(self.payload)


# ==========================================
# Payload Parser
# ==========================================

class TCGPayloadParser:
    """TCG Payload 파싱"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def parse(self) -> List[Any]:
        """Payload 전체 파싱"""
        result = []
        while self.pos < len(self.data):
            item = self.parse_item()
            if item is None:
                break
            result.append(item)
        return result
    
    def parse_item(self) -> Optional[Any]:
        """단일 아이템 파싱"""
        if self.pos >= len(self.data):
            return None
        
        token = self.data[self.pos]
        
        # Tiny Atom (unsigned)
        if token <= 0x3F:
            self.pos += 1
            return token
        
        # Tiny Atom (signed)
        elif 0x40 <= token <= 0x7F:
            self.pos += 1
            value = token & 0x3F
            if value & 0x20:  # 음수
                value = value - 0x40
            return value
        
        # Short Atom
        elif 0x80 <= token <= 0xBF:
            length = token & 0x3F
            self.pos += 1
            data = self.data[self.pos:self.pos + length]
            self.pos += length
            return data
        
        # Medium Atom
        elif 0xC0 <= token <= 0xDF:
            byte1 = token
            byte2 = self.data[self.pos + 1]
            length = ((byte1 & 0x1F) << 8) | byte2
            self.pos += 2
            data = self.data[self.pos:self.pos + length]
            self.pos += length
            return data
        
        # Long Atom
        elif 0xE0 <= token <= 0xE3:
            # 구현 생략 (거의 사용 안 됨)
            raise NotImplementedError("Long atom not implemented")
        
        # Special tokens
        elif token == Token.START_LIST:
            self.pos += 1
            return self.parse_list()
        
        elif token == Token.START_NAME:
            self.pos += 1
            return self.parse_name()
        
        elif token == Token.EMPTY_ATOM:
            self.pos += 1
            return b''
        
        elif token == Token.END_OF_DATA:
            self.pos += 1
            return None
        
        elif token in [Token.END_LIST, Token.END_NAME]:
            # List/Name 종료는 parse_list/parse_name에서 처리
            return None
        
        else:
            raise ValueError(f"Unknown token: 0x{token:02X}")
    
    def parse_list(self) -> List[Any]:
        """List 파싱"""
        items = []
        while self.pos < len(self.data):
            if self.data[self.pos] == Token.END_LIST:
                self.pos += 1
                break
            item = self.parse_item()
            if item is not None:
                items.append(item)
        return items
    
    def parse_name(self) -> Tuple[Any, Any]:
        """Name (키-값 쌍) 파싱"""
        key = self.parse_item()
        value = self.parse_item()
        
        if self.pos < len(self.data) and self.data[self.pos] == Token.END_NAME:
            self.pos += 1
        
        return (key, value)


# ==========================================
# Response Parser
# ==========================================

class TCGResponseParser:
    """TCG 응답 파싱"""
    
    @staticmethod
    def parse_session_response(response_data: bytes) -> Dict[str, Any]:
        """Session 응답 파싱"""
        parser = TCGPayloadParser(response_data)
        parsed = parser.parse()
        
        result = {
            'raw': parsed,
            'session_id': None,
            'tper_session_id': None,
            'status': None
        }
        
        # 일반적인 Session 응답 구조:
        # [ HostSessionID, TPer_SessionID, [ MethodStatusList ] ]
        if len(parsed) >= 3:
            result['session_id'] = TCGResponseParser._bytes_to_int(parsed[0])
            result['tper_session_id'] = TCGResponseParser._bytes_to_int(parsed[1])
            
            if isinstance(parsed[2], list) and len(parsed[2]) >= 1:
                result['status'] = TCGResponseParser._bytes_to_int(parsed[2][0])
        
        return result
    
    @staticmethod
    def parse_method_response(response_data: bytes) -> Dict[str, Any]:
        """Method 응답 파싱"""
        parser = TCGPayloadParser(response_data)
        parsed = parser.parse()
        
        result = {
            'raw': parsed,
            'status': None,
            'data': None
        }
        
        # Method 응답 구조:
        # [ [ StatusCode, ... ], [ ResultData, ... ] ]
        if len(parsed) >= 1:
            if isinstance(parsed[0], list) and len(parsed[0]) >= 1:
                result['status'] = TCGResponseParser._bytes_to_int(parsed[0][0])
            
            if len(parsed) >= 2 and isinstance(parsed[1], list):
                result['data'] = parsed[1]
        
        return result
    
    @staticmethod
    def _bytes_to_int(data: Any) -> int:
        """bytes를 int로 변환"""
        if isinstance(data, int):
            return data
        elif isinstance(data, bytes):
            if len(data) == 0:
                return 0
            return int.from_bytes(data, 'big')
        else:
            return 0


# ==========================================
# ComPacket Builder
# ==========================================

class TCGComPacketBuilder:
    """TCG ComPacket 생성"""
    
    @staticmethod
    def build(
        com_id: int,
        payload: bytes,
        extended_com_id: int = 0
    ) -> bytes:
        """
        ComPacket 생성
        
        Structure:
        - Reserved: 4 bytes
        - ComID: 2 bytes (big-endian)
        - ComID Extension: 2 bytes (big-endian)
        - OutstandingData: 4 bytes
        - MinTransfer: 4 bytes
        - Length: 4 bytes (big-endian)
        - Payload: variable
        """
        header = struct.pack(
            '>I H H I I I',
            0,                      # Reserved
            com_id,                 # ComID
            extended_com_id,        # ComID Extension
            0,                      # OutstandingData
            0,                      # MinTransfer
            len(payload)            # Length
        )
        
        return header + payload


# ==========================================
# UIDs (TCG Opal Spec)
# ==========================================

class UID:
    """TCG Opal 표준 UID"""
    
    # Session Manager
    SM_UID = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF])
    
    # Methods
    PROPERTIES = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x01])
    START_SESSION = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x02])
    SYNC_SESSION = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x03])
    
    # SPs
    ADMIN_SP = bytes([0x00, 0x00, 0x02, 0x05, 0x00, 0x00, 0x00, 0x01])
    LOCKING_SP = bytes([0x00, 0x00, 0x02, 0x05, 0x00, 0x00, 0x00, 0x02])
    
    # Authorities
    SID = bytes([0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x06])
    ADMIN1 = bytes([0x00, 0x00, 0x00, 0x09, 0x00, 0x01, 0x00, 0x01])
    
    # Tables
    C_PIN_TABLE = bytes([0x00, 0x00, 0x00, 0x0B, 0x00, 0x00, 0x00, 0x00])
    LOCKING_INFO_TABLE = bytes([0x00, 0x00, 0x08, 0x01, 0x00, 0x00, 0x00, 0x00])
    
    # Methods
    REVERT = bytes([0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x02])
    ACTIVATE = bytes([0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x03])
    GET = bytes([0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x16])
    SET = bytes([0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x17])
    AUTHENTICATE = bytes([0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x0C])
