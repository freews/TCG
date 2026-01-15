"""
TCG Opal Protocol Codec
=======================

Token ì¸ì½”ë”©/ë””ì½”ë”© ë° Payload íŒŒì‹±
"""

import struct
from typing import List, Dict, Any, Tuple, Optional
from enum import IntEnum


# ==========================================
# Token Definitions (TCG Core Spec)
# ==========================================

class Token(IntEnum):
    """TCG Storage Token ì •ì˜"""
    # Atoms
    TINY_ATOM_START = 0x00      # 0x00-0x3F: Tiny Atom (unsigned)
    TINY_ATOM_SIGNED = 0x40     # 0x40-0x7F: Signed Tiny Atom
    SHORT_ATOM = 0x80           # 0x80-0xBF: Short Atom
    MEDIUM_ATOM = 0xC0          # 0xC0-0xDF: Medium Atom
    LONG_ATOM = 0xE0            # 0xE0-0xE3: Long Atom
    
    # Special tokens
    START_LIST = 0xF0           # List ì‹œìž‘
    END_LIST = 0xF1             # List ì¢…ë£Œ
    START_NAME = 0xF2           # Name ì‹œìž‘ (í‚¤-ê°’ ìŒ)
    END_NAME = 0xF3             # Name ì¢…ë£Œ
    CALL = 0xF8                 # Method í˜¸ì¶œ
    END_OF_DATA = 0xF9          # ë°ì´í„° ì¢…ë£Œ
    END_OF_SESSION = 0xFA       # ì„¸ì…˜ ì¢…ë£Œ
    START_TRANSACTION = 0xFB    # íŠ¸ëžœìž­ì…˜ ì‹œìž‘
    END_TRANSACTION = 0xFC      # íŠ¸ëžœìž­ì…˜ ì¢…ë£Œ
    EMPTY_ATOM = 0xFF           # ë¹ˆ Atom


# ==========================================
# Payload Builder
# ==========================================

class TCGPayloadBuilder:
    """TCG Payload ìƒì„± í—¬í¼"""
    
    def __init__(self):
        self.payload = bytearray()
    
    def add_token(self, token: int) -> 'TCGPayloadBuilder':
        """Token ì¶”ê°€"""
        self.payload.append(token)
        return self
    
    def add_tiny_atom(self, value: int) -> 'TCGPayloadBuilder':
        """Tiny Atom ì¶”ê°€ (0-63)"""
        if 0 <= value <= 63:
            self.payload.append(value)
        else:
            raise ValueError(f"Tiny atom value out of range: {value}")
        return self
    
    def add_short_atom(self, data: bytes) -> 'TCGPayloadBuilder':
        """Short Atom ì¶”ê°€ (1-63 bytes)"""
        length = len(data)
        if 1 <= length <= 63:
            self.payload.append(Token.SHORT_ATOM | length)
            self.payload.extend(data)
        else:
            raise ValueError(f"Short atom length out of range: {length}")
        return self
    
    def add_medium_atom(self, data: bytes) -> 'TCGPayloadBuilder':
        """Medium Atom ì¶”ê°€ (64-2047 bytes)"""
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
        """ë°”ì´íŠ¸ ë°ì´í„° ì¶”ê°€ (ê¸¸ì´ì— ë”°ë¼ ìžë™ ì„ íƒ)"""
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
        """UID ì¶”ê°€ (8 bytes)"""
        if len(uid) != 8:
            raise ValueError(f"UID must be 8 bytes, got {len(uid)}")
        return self.add_bytes(uid)
    
    def add_integer(self, value: int) -> 'TCGPayloadBuilder':
        """ì •ìˆ˜ ì¶”ê°€"""
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
            # Short/Medium atomìœ¼ë¡œ ì¸ì½”ë”©
            if value >= 0:
                data = value.to_bytes((value.bit_length() + 7) // 8, 'big')
            else:
                # ìŒìˆ˜ëŠ” 2ì˜ ë³´ìˆ˜
                byte_count = (value.bit_length() + 8) // 8
                data = value.to_bytes(byte_count, 'big', signed=True)
            self.add_bytes(data)
        return self
    
    def start_list(self) -> 'TCGPayloadBuilder':
        """List ì‹œìž‘"""
        self.add_token(Token.START_LIST)
        return self
    
    def end_list(self) -> 'TCGPayloadBuilder':
        """List ì¢…ë£Œ"""
        self.add_token(Token.END_LIST)
        return self
    
    def start_name(self) -> 'TCGPayloadBuilder':
        """Name ì‹œìž‘"""
        self.add_token(Token.START_NAME)
        return self
    
    def end_name(self) -> 'TCGPayloadBuilder':
        """Name ì¢…ë£Œ"""
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
        """ìµœì¢… Payload ë°˜í™˜"""
        return bytes(self.payload)


# ==========================================
# Payload Parser
# ==========================================

class TCGPayloadParser:
    """TCG Payload íŒŒì‹±"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def parse(self) -> List[Any]:
        """Payload ì „ì²´ íŒŒì‹±"""
        result = []
        while self.pos < len(self.data):
            item = self.parse_item()
            if item is None:
                break
            result.append(item)
        return result
    
    def parse_item(self) -> Optional[Any]:
        """ë‹¨ì¼ ì•„ì´í…œ íŒŒì‹±"""
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
            if value & 0x20:  # ìŒìˆ˜
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
            # êµ¬í˜„ ìƒëžµ (ê±°ì˜ ì‚¬ìš© ì•ˆ ë¨)
            raise NotImplementedError("Long atom not implemented")
        
        # Special tokens
        elif token == Token.START_LIST:
            self.pos += 1
            return self.parse_list()
        
        elif token == Token.START_NAME:
            self.pos += 1
            return self.parse_name()
        
        elif token == Token.CALL:
            # TCG Core Spec 3.2.2.3.3.1: CALL token indicates start of method invocation
            # Used in Session Manager responses (SyncSession, SyncTrustedSession, etc.)
            self.pos += 1
            return {'type': 'CALL'}
        
        elif token == Token.EMPTY_ATOM:
            self.pos += 1
            return b''
        
        elif token == Token.END_OF_DATA:
            self.pos += 1
            return None
        
        elif token in [Token.END_LIST, Token.END_NAME]:
            # List/Name ì¢…ë£ŒëŠ” parse_list/parse_nameì—ì„œ ì²˜ë¦¬
            return None
        
        else:
            raise ValueError(f"Unknown token: 0x{token:02X}")
    
    def parse_list(self) -> List[Any]:
        """List íŒŒì‹±"""
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
        """Name (í‚¤-ê°’ ìŒ) íŒŒì‹±"""
        key = self.parse_item()
        value = self.parse_item()
        
        if self.pos < len(self.data) and self.data[self.pos] == Token.END_NAME:
            self.pos += 1
        
        return (key, value)


# ==========================================
# Response Parser
# ==========================================

class TCGResponseParser:
    """TCG ì‘ë‹µ íŒŒì‹±"""
    
    @staticmethod
    @staticmethod
    def parse_session_response(response_data: bytes) -> Dict[str, Any]:
        """
        Session Manager Response (SyncSession) Parsing
        
        TCG Core Spec References:
        - Section 5.2.3.2: SyncSession Method Response Format
        - Section 3.2.4.2: Method Encoding (for Session Manager responses)
        - Section 3.3.7.1.3: Session Manager Protocol Layer
        
        SyncSession Response Structure (returned as METHOD CALL):
        --------------------------------------------------------
        CALL token (0xF8)
        InvokingID (8 bytes) - SMUID (0x00 00 00 00 00 00 00 FF)
        MethodID (8 bytes) - SyncSession UID (0x00 00 00 00 00 00 FF 03)
        START_LIST (0xF0)
            HostSessionID : uinteger
            SPSessionID : uinteger
            [SPChallenge = bytes]           (optional - Spec 5.2.3.2.3)
            [SPExchangeCert = bytes]        (optional - Spec 5.2.3.2.4)
            [SPSigningCert = bytes]         (optional - Spec 5.2.3.2.5)
            [TransTimeout = uinteger]       (optional - Spec 5.2.3.2.6)
            [InitialCredit = uinteger]      (optional - Spec 5.2.3.2.7)
            [SignedHash = bytes]            (optional - Spec 5.2.3.2.8)
        END_LIST (0xF1)
        END_OF_DATA (0xF9)
        START_LIST (0xF0)                   <- STATUS LIST (Spec 3.2.4.2)
            status_code : uinteger (0x00 = SUCCESS, see Spec 5.1.5)
            reserved : uinteger (0x00)
            reserved : uinteger (0x00)
        END_LIST (0xF1)
        """
        parser = TCGPayloadParser(response_data)
        parsed = parser.parse()
        
        result = {
            'raw': parsed,
            'session_id': None,
            'tper_session_id': None,
            'status': None
        }
        
        # Parse METHOD CALL structure
        # Expected: [CALL_dict, InvokingID_bytes, MethodID_bytes, param_list, status_list]
        try:
            idx = 0
            
            # 1. Check CALL token (Spec 3.2.2.3.3.1)
            if idx < len(parsed) and isinstance(parsed[idx], dict) and parsed[idx].get('type') == 'CALL':
                idx += 1
            
            # 2. Skip InvokingID (8 bytes SMUID) (Spec 3.2.4.2)
            if idx < len(parsed) and isinstance(parsed[idx], bytes):
                idx += 1
            
            # 3. Skip MethodID (8 bytes SyncSession UID) (Spec 3.2.4.2)
            if idx < len(parsed) and isinstance(parsed[idx], bytes):
                idx += 1
            
            # 4. Parse Parameter List (Spec 5.2.3.2)
            # Contains: [HostSessionID, SPSessionID, optional params...]
            if idx < len(parsed) and isinstance(parsed[idx], list):
                param_list = parsed[idx]
                if len(param_list) >= 1:
                    result['session_id'] = TCGResponseParser._bytes_to_int(param_list[0])
                if len(param_list) >= 2:
                    result['tper_session_id'] = TCGResponseParser._bytes_to_int(param_list[1])
                idx += 1
            
            # 5. Parse Status List (Spec 3.2.4.2, section 5)
            # The status list appears AFTER End of Data token
            # Format: [status_code, 0x00, 0x00]
            if idx < len(parsed) and isinstance(parsed[idx], list):
                status_list = parsed[idx]
                if len(status_list) >= 1:
                    result['status'] = TCGResponseParser._bytes_to_int(status_list[0])
        
        except Exception as e:
            # If parsing fails, return what we have with error info
            result['parse_error'] = str(e)
        
        return result

    @staticmethod
    def parse_method_response(response_data: bytes) -> Dict[str, Any]:
        """
        Regular Method Response Parsing
        
        TCG Core Spec References:
        - Section 3.2.4.2: Method Response Format
        - Section 3.3.7.2: Methods (response structure)
        
        Method Response Structure:
        -------------------------
        START_LIST (0xF0)                   <- RESULT LIST
            [result values...]              (method-specific)
        END_LIST (0xF1)
        END_OF_DATA (0xF9)
        START_LIST (0xF0)                   <- STATUS LIST (Spec 3.2.4.2)
            status_code : uinteger (0x00 = SUCCESS, see Spec 5.1.5)
            reserved : uinteger (0x00)
            reserved : uinteger (0x00)
        END_LIST (0xF1)
        """
        parser = TCGPayloadParser(response_data)
        parsed = parser.parse()
        
        result = {
            'raw': parsed,
            'status': None,
            'data': None
        }
        
        # Parse response structure
        # Expected: [result_list, status_list]
        try:
            idx = 0
            
            # 1. Parse Result List (Spec 3.2.4.2, section 2-3)
            if idx < len(parsed) and isinstance(parsed[idx], list):
                result['data'] = parsed[idx]
                idx += 1
            
            # 2. Parse Status List (Spec 3.2.4.2, section 5)
            # Format: [status_code, 0x00, 0x00]
            if idx < len(parsed) and isinstance(parsed[idx], list):
                status_list = parsed[idx]
                if len(status_list) >= 1:
                    result['status'] = TCGResponseParser._bytes_to_int(status_list[0])
        
        except Exception as e:
            result['parse_error'] = str(e)
        
        return result
    
    @staticmethod
    def _bytes_to_int(data: Any) -> int:
        """bytesë¥¼ intë¡œ ë³€í™˜"""
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
    """TCG ComPacket ìƒì„±"""
    
    @staticmethod
    def build(
        com_id: int,
        payload: bytes,
        extended_com_id: int = 0
    ) -> bytes:
        """
        ComPacket ìƒì„±
        
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
    """TCG Opal í‘œì¤€ UID"""
    
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
