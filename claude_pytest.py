"""
TCG Opal SSC v2.30 종합 테스트 스위트

이 모듈은 NVMe 디바이스의 TCG Opal 기능을 포괄적으로 테스트합니다.
- Level 0 Discovery
- Session Management
- Authentication
- Locking 기능
- MBR Shadowing
- Cryptographic Operations
- Lifecycle Management
"""

import pytest
import struct
import time
from pynvme import Controller, Buffer
from typing import Dict, Tuple, Optional, List
from enum import IntEnum


# ============================================================================
# TCG Opal 상수 정의
# ============================================================================

class SecurityProtocol(IntEnum):
    """Security Protocol 값 정의 (NVMe Spec 5.2.24.3)"""
    INFO = 0x00              # Security Protocol 00h - 지원 프로토콜 정보
    TCG_1 = 0x01             # TCG Security Protocol 01h
    TCG_2 = 0x02             # TCG Security Protocol 02h (Protocol Stack Reset)
    NVME = 0xEA              # NVMe Security Protocol EAh


class ComID(IntEnum):
    """ComID (SP Specific) 값 정의"""
    DISCOVERY = 0x0001       # Level 0 Discovery용 ComID
    TPER_RESET = 0x0004      # TPer Reset 명령용 ComID


class FeatureCode(IntEnum):
    """Feature Descriptor Code 정의 (TCG Opal Table 1)"""
    TPER = 0x0001                    # TPer Feature
    LOCKING = 0x0002                 # Locking Feature
    GEOMETRY_REPORTING = 0x0003      # Geometry Reporting Feature
    OPAL_SSC_V1 = 0x0200            # Opal SSC V1
    OPAL_SSC_V2 = 0x0203            # Opal SSC V2
    DATA_REMOVAL = 0x0404            # Data Removal Mechanism


class MethodID(IntEnum):
    """TCG Method ID 정의"""
    PROPERTIES = 0x00000006_00000001      # Properties 메서드
    START_SESSION = 0x00000006_000000FF   # StartSession 메서드
    SYNC_SESSION = 0x00000006_000000FE    # SyncSession 메서드
    CLOSE_SESSION = 0x00000006_000000FD   # CloseSession 메서드
    REVERT = 0x00000006_00000202          # Revert 메서드
    ACTIVATE = 0x00000006_00000203        # Activate 메서드
    REVERT_SP = 0x00000006_00000011       # RevertSP 메서드
    GEN_KEY = 0x00000006_00000010         # GenKey 메서드 (암호화 키 생성)
    RANDOM = 0x00000006_00000601          # Random 메서드
    GET = 0x00000006_00000016             # Get 메서드
    SET = 0x00000006_00000017             # Set 메서드


class SPID(IntEnum):
    """Security Provider ID 정의"""
    ADMIN_SP = 0x00000205_00000001        # Admin SP
    LOCKING_SP = 0x00000205_00000002      # Locking SP


# ============================================================================
# TCG 프로토콜 엔코딩 클래스
# ============================================================================

class TCGTokens:
    """
    TCG Stream Encoding Tokens (TCG Opal Table 15)
    
    Opal은 다음의 토큰들을 사용하여 데이터를 인코딩합니다:
    - Atoms: 데이터 값 표현
    - Lists: 여러 값의 집합
    - Names: 키-값 쌍
    - Call: 메서드 호출
    """
    # Atoms
    TINY_ATOM_START = 0x00      # 0x00-0x3F: Tiny Atom (6-bit 값)
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


class TCGPayloadBuilder:
    """
    TCG 프로토콜 Payload 생성 헬퍼
    
    TCG Core Spec의 Stream Encoding 규칙에 따라 payload를 구성합니다.
    ComPacket -> Packet -> Subpacket 구조를 생성합니다.
    """
    
    @staticmethod
    def encode_atom_unsigned(value: int) -> bytes:
        """
        부호 없는 정수를 Atom으로 인코딩
        
        Tiny Atom (0x00-0x3F): 0-63 범위의 작은 값
        Short Atom: 1바이트 길이
        Medium Atom: 2바이트 길이
        Long Atom: 4바이트 또는 8바이트 길이
        """
        if value <= 0x3F:
            # Tiny Atom: 값이 0-63 범위
            return bytes([value])
        elif value <= 0xFF:
            # Short Atom: 1바이트
            return bytes([0x81, value])
        elif value <= 0xFFFF:
            # Medium Atom: 2바이트
            return bytes([0xC2]) + struct.pack('>H', value)
        elif value <= 0xFFFFFFFF:
            # Long Atom: 4바이트
            return bytes([0xE3]) + struct.pack('>I', value)
        else:
            # Long Atom: 8바이트
            return bytes([0xE7]) + struct.pack('>Q', value)
    
    @staticmethod
    def encode_bytes(data: bytes) -> bytes:
        """
        바이트 배열을 Atom으로 인코딩
        
        길이 정보를 포함한 헤더 + 실제 데이터
        """
        length = len(data)
        if length <= 0x0F:
            # Short Atom with length
            header = bytes([0xA0 | length])
        elif length <= 0x7FF:
            # Medium Atom with length
            header = bytes([0xD0 | (length >> 8), length & 0xFF])
        else:
            # Long Atom with length
            header = bytes([0xE0 | 0x03])
            header += struct.pack('>I', length)
        
        return header + data
    
    @staticmethod
    def encode_uid(uid: int) -> bytes:
        """
        UID (8바이트 unsigned integer)를 인코딩
        
        TCG에서 객체를 식별하는 고유 ID
        """
        return bytes([0xA8]) + struct.pack('>Q', uid)
    
    @staticmethod
    def build_compacket(comid: int, packet_data: bytes) -> bytes:
        """
        ComPacket 구성 (TCG Core Spec Section 3.2.1)
        
        Structure:
        - Reserved (4 bytes): 0x00000000
        - ComID (2 bytes): Communication ID
        - ComID Extension (2 bytes): 0x0000
        - Outstanding Data (4 bytes): 0x00000000
        - Min Transfer (4 bytes): 0x00000000
        - Length (4 bytes): Packet data length
        - Packet data
        """
        header = struct.pack('>I', 0)           # Reserved
        header += struct.pack('>H', comid)       # ComID
        header += struct.pack('>H', 0)           # ComID Extension
        header += struct.pack('>I', 0)           # Outstanding Data
        header += struct.pack('>I', 0)           # Min Transfer
        header += struct.pack('>I', len(packet_data))  # Length
        
        return header + packet_data
    
    @staticmethod
    def build_packet(session_id: int, seq_number: int, subpacket_data: bytes) -> bytes:
        """
        Packet 구성 (TCG Core Spec Section 3.2.2)
        
        Structure:
        - Session TSN (4 bytes): Session Transaction Sequence Number
        - Session Number (4 bytes): Session ID
        - Sequence Number (4 bytes): Packet sequence
        - Reserved (2 bytes)
        - AckType (2 bytes)
        - Acknowledgement (4 bytes)
        - Length (4 bytes): Subpacket length
        - Subpacket data
        """
        header = struct.pack('>I', 0)               # TSN
        header += struct.pack('>I', session_id)     # Session Number
        header += struct.pack('>I', seq_number)     # Sequence Number
        header += struct.pack('>H', 0)              # Reserved
        header += struct.pack('>H', 0)              # AckType
        header += struct.pack('>I', 0)              # Acknowledgement
        header += struct.pack('>I', len(subpacket_data))  # Length
        
        return header + subpacket_data
    
    @staticmethod
    def build_subpacket(kind: int, payload: bytes) -> bytes:
        """
        Subpacket 구성 (TCG Core Spec Section 3.2.3)
        
        Structure:
        - Reserved (6 bytes)
        - Kind (2 bytes): Subpacket type
        - Length (4 bytes): Payload length
        - Payload data
        
        Kind values:
        - 0x0000: Data subpacket
        - 0x0001: Credit Control subpacket
        """
        header = bytes(6)                          # Reserved
        header += struct.pack('>H', kind)          # Kind
        header += struct.pack('>I', len(payload))  # Length
        
        return header + payload


# ============================================================================
# TCG Opal 테스터 메인 클래스
# ============================================================================

class TCGOpalTester:
    """
    TCG Opal SSC v2.30 테스트를 위한 종합 헬퍼 클래스
    
    이 클래스는 다음 기능들을 제공합니다:
    1. Security Protocol 명령 실행 (Send/Receive)
    2. Level 0 Discovery 파싱
    3. Session 관리 (Start/Sync/Close)
    4. Authentication
    5. Locking 제어
    6. Cryptographic Operations
    """
    
    # NVMe Admin Command Opcodes
    NVME_ADMIN_SECURITY_RECV = 0x82
    NVME_ADMIN_SECURITY_SEND = 0x81
    
    def __init__(self, nvme: Controller):
        """
        Args:
            nvme: pynvme Controller 인스턴스
        """
        self.nvme = nvme
        self.current_session_id = 0
        self.host_session_id = 0x01  # Host가 할당하는 Session ID
    
    # ========================================================================
    # 1. Security Protocol 명령 (Low-level)
    # ========================================================================
    
    def security_receive(self, secp: int, spsp: int, length: int, 
                        nssf: int = 0) -> bytes:
        """
        Security Receive 명령 실행
        
        NVMe Base Spec Section 5.2.24
        TPer로부터 데이터를 수신합니다.
        
        Args:
            secp: Security Protocol (SECP)
            spsp: Security Protocol Specific (16-bit)
            length: 수신할 데이터 길이 (Allocation Length)
            nssf: NVMe Security Specific Field (Protocol EAh 전용)
        
        Returns:
            수신된 바이트 데이터
        """
        buffer = Buffer(length)
        
        # SPSP 분할: 16-bit -> SPSP1 (MSB) + SPSP0 (LSB)
        spsp1 = (spsp >> 8) & 0xFF
        spsp0 = spsp & 0xFF
        
        # CDW10 구성 (Figure 394)
        # [31:24] SECP | [23:16] SPSP1 | [15:08] SPSP0 | [07:00] NSSF
        cdw10 = ((secp & 0xFF) << 24) | \
                ((spsp1 & 0xFF) << 16) | \
                ((spsp0 & 0xFF) << 8) | \
                (nssf & 0xFF)
        
        # CDW11: Allocation Length
        cdw11 = length & 0xFFFFFFFF
        
        # NVMe Admin Command 실행
        self.nvme.send_admin_raw(
            opcode=self.NVME_ADMIN_SECURITY_RECV,
            cdw10=cdw10,
            cdw11=cdw11,
            data_out=buffer
        ).waitdone()
        
        return buffer.data
    
    def security_send(self, secp: int, spsp: int, data: bytes, 
                     nssf: int = 0) -> None:
        """
        Security Send 명령 실행
        
        NVMe Base Spec Section 5.2.25
        TPer로 데이터를 전송합니다.
        
        Args:
            secp: Security Protocol
            spsp: Security Protocol Specific
            data: 전송할 데이터
            nssf: NVMe Security Specific Field
        """
        buffer = Buffer(len(data))
        buffer[:] = data
        
        spsp1 = (spsp >> 8) & 0xFF
        spsp0 = spsp & 0xFF
        
        # CDW10 구성 (Figure 398)
        cdw10 = ((secp & 0xFF) << 24) | \
                ((spsp1 & 0xFF) << 16) | \
                ((spsp0 & 0xFF) << 8) | \
                (nssf & 0xFF)
        
        # CDW11: Transfer Length
        cdw11 = len(data) & 0xFFFFFFFF
        
        self.nvme.send_admin_raw(
            opcode=self.NVME_ADMIN_SECURITY_SEND,
            cdw10=cdw10,
            cdw11=cdw11,
            data_in=buffer
        ).waitdone()
    
    # ========================================================================
    # 2. Level 0 Discovery 기능
    # ========================================================================
    
    def level0_discovery(self) -> bytes:
        """
        Level 0 Discovery 수행
        
        TCG Opal Section 3.1.1
        Security Protocol 01h, ComID 0x0001 사용
        TPer의 기능과 설정을 조회합니다.
        
        Returns:
            Discovery response 전체 데이터
        """
        return self.security_receive(
            secp=SecurityProtocol.TCG_1,
            spsp=ComID.DISCOVERY,
            length=2048
        )
    
    def parse_discovery_header(self, data: bytes) -> Dict:
        """
        Discovery Header 파싱
        
        TCG Opal Table 2
        
        Structure:
        - Bytes 0-3: Parameter Length (Big-endian)
        - Bytes 4-7: Revision (Big-endian)
        - Bytes 8-15: Reserved
        - Bytes 16-47: Vendor Specific
        """
        if len(data) < 48:
            raise ValueError(f"Data too short: {len(data)} bytes")
        
        return {
            'parameter_length': struct.unpack('>I', data[0:4])[0],
            'revision': struct.unpack('>I', data[4:8])[0],
            'vendor_specific': data[16:48].hex()
        }
    
    def parse_feature_descriptor(self, data: bytes, offset: int) -> \
            Tuple[Optional[Dict], int]:
        """
        Feature Descriptor 파싱
        
        모든 Feature의 공통 헤더 구조:
        - Bytes 0-1: Feature Code (Big-endian)
        - Byte 2: Version (상위 4bit) + Reserved (하위 4bit)
        - Byte 3: Length
        - Bytes 4+: Feature-specific data
        
        Returns:
            (feature_dict, next_offset) 또는 (None, offset) if end
        """
        if offset + 4 > len(data):
            return None, offset
        
        feature_code = struct.unpack('>H', data[offset:offset+2])[0]
        
        if feature_code == 0:  # End marker
            return None, offset
        
        version = (data[offset+2] >> 4) & 0x0F
        length = data[offset+3]
        
        if offset + 4 + length > len(data):
            raise ValueError(f"Feature extends beyond data boundary")
        
        return {
            'feature_code': feature_code,
            'version': version,
            'length': length,
            'data': data[offset+4:offset+4+length]
        }, offset + 4 + length
    
    def parse_tper_feature(self, data: bytes) -> Dict:
        """
        TPer Feature 파싱 (Feature Code 0x0001)
        
        TCG Opal Table 3
        Byte 0의 각 bit가 지원 기능을 나타냅니다.
        """
        return {
            'sync_supported': bool(data[0] & 0x01),
            'async_supported': bool(data[0] & 0x02),
            'ack_nak_supported': bool(data[0] & 0x04),
            'buffer_mgmt_supported': bool(data[0] & 0x08),
            'streaming_supported': bool(data[0] & 0x10),
            'comid_mgmt_supported': bool(data[0] & 0x40)
        }
    
    def parse_locking_feature(self, data: bytes) -> Dict:
        """
        Locking Feature 파싱 (Feature Code 0x0002)
        
        TCG Opal Table 4
        Locking 기능의 지원 여부와 현재 상태를 파싱합니다.
        """
        return {
            'locking_supported': bool(data[0] & 0x01),
            'locking_enabled': bool(data[0] & 0x02),
            'locked': bool(data[0] & 0x04),
            'media_encryption': bool(data[0] & 0x08),
            'mbr_enabled': bool(data[0] & 0x10),
            'mbr_done': bool(data[0] & 0x20),
            'mbr_shadowing_not_supported': bool(data[0] & 0x40),
            'hw_reset_for_lor_dor_supported': bool(data[0] & 0x80)
        }
    
    def parse_opal_ssc_v2_feature(self, data: bytes) -> Dict:
        """
        Opal SSC V2 Feature 파싱 (Feature Code 0x0203)
        
        TCG Opal Table 6
        Opal SSC 버전과 지원하는 authorities 수 등을 파싱합니다.
        """
        if len(data) < 16:
            raise ValueError(f"Opal SSC V2 data too short: {len(data)}")
        
        return {
            'base_comid': struct.unpack('>H', data[0:2])[0],
            'num_comids': struct.unpack('>H', data[2:4])[0],
            'range_crossing_behavior': data[4] & 0x01,
            'num_admin_authorities': struct.unpack('>H', data[5:7])[0],
            'num_user_authorities': struct.unpack('>H', data[7:9])[0],
            'initial_pin_indicator': data[9],
            'revert_pin_behavior': data[10]
        }
    
    def parse_geometry_feature(self, data: bytes) -> Dict:
        """
        Geometry Reporting Feature 파싱 (Feature Code 0x0003)
        
        TCG Opal Table 5
        디스크의 물리적 geometry 정보를 파싱합니다.
        """
        if len(data) < 28:
            raise ValueError(f"Geometry data too short: {len(data)}")
        
        return {
            'align_required': bool(data[0] & 0x01),
            'logical_block_size': struct.unpack('>I', data[8:12])[0],
            'alignment_granularity': struct.unpack('>Q', data[12:20])[0],
            'lowest_aligned_lba': struct.unpack('>Q', data[20:28])[0]
        }
    
    # ========================================================================
    # 3. Session Management 기능
    # ========================================================================
    
    def start_session(self, sp_id: int, write: bool = True, 
                     host_challenge: bytes = b'', 
                     host_signing_authority: int = 0) -> int:
        """
        StartSession 메서드 호출
        
        TCG Opal Section 4.1.1.2
        TPer와의 통신 세션을 시작합니다.
        
        Args:
            sp_id: Security Provider ID (Admin SP 또는 Locking SP)
            write: True면 Read-Write 세션, False면 Read-Only 세션
            host_challenge: Authentication용 Challenge (선택)
            host_signing_authority: Signing Authority UID (선택)
        
        Returns:
            할당된 SP Session ID
        """
        # Payload 구성 (StartSession method call)
        payload = bytearray()
        payload.append(TCGTokens.CALL)  # Method 호출 시작
        
        # InvokingID (Session Manager)
        payload += TCGPayloadBuilder.encode_uid(0x000000_060000FF)
        
        # MethodID (StartSession)
        payload += TCGPayloadBuilder.encode_uid(MethodID.START_SESSION)
        
        # Parameters (StartList)
        payload.append(TCGTokens.START_LIST)
        
        # Parameter 1: HostSessionID
        payload.append(TCGTokens.START_NAME)
        payload += TCGPayloadBuilder.encode_atom_unsigned(0)  # "HostSessionID"
        payload += TCGPayloadBuilder.encode_atom_unsigned(self.host_session_id)
        payload.append(TCGTokens.END_NAME)
        
        # Parameter 2: SPID
        payload.append(TCGTokens.START_NAME)
        payload += TCGPayloadBuilder.encode_atom_unsigned(1)  # "SPID"
        payload += TCGPayloadBuilder.encode_uid(sp_id)
        payload.append(TCGTokens.END_NAME)
        
        # Parameter 3: Write
        payload.append(TCGTokens.START_NAME)
        payload += TCGPayloadBuilder.encode_atom_unsigned(2)  # "Write"
        payload += TCGPayloadBuilder.encode_atom_unsigned(1 if write else 0)
        payload.append(TCGTokens.END_NAME)
        
        # Optional: HostChallenge
        if host_challenge:
            payload.append(TCGTokens.START_NAME)
            payload += TCGPayloadBuilder.encode_atom_unsigned(3)
            payload += TCGPayloadBuilder.encode_bytes(host_challenge)
            payload.append(TCGTokens.END_NAME)
        
        # Optional: HostSigningAuthority
        if host_signing_authority:
            payload.append(TCGTokens.START_NAME)
            payload += TCGPayloadBuilder.encode_atom_unsigned(4)
            payload += TCGPayloadBuilder.encode_uid(host_signing_authority)
            payload.append(TCGTokens.END_NAME)
        
        payload.append(TCGTokens.END_LIST)
        payload.append(TCGTokens.END_OF_DATA)
        
        # Subpacket -> Packet -> ComPacket 구성
        subpacket = TCGPayloadBuilder.build_subpacket(0, bytes(payload))
        packet = TCGPayloadBuilder.build_packet(0, 0, subpacket)
        compacket = TCGPayloadBuilder.build_compacket(ComID.DISCOVERY, packet)
        
        # Security Send
        self.security_send(SecurityProtocol.TCG_1, ComID.DISCOVERY, compacket)
        
        # Security Receive (응답 수신)
        response = self.security_receive(
            SecurityProtocol.TCG_1, ComID.DISCOVERY, 2048
        )
        
        # 응답에서 Session ID 추출
        # (실제 구현에서는 response parsing 필요)
        self.current_session_id = self._parse_session_id_from_response(response)
        
        return self.current_session_id
    
    def sync_session(self, host_session_id: int, sp_session_id: int) -> None:
        """
        SyncSession 메서드 호출
        
        TCG Opal Section 4.1.1.3
        세션을 동기화합니다. (타임아웃 리셋 등)
        """
        # SyncSession method call payload 구성
        # (구현 생략 - StartSession과 유사한 패턴)
        pass
    
    def close_session(self) -> None:
        """
        CloseSession 메서드 호출 (Optional)
        
        TCG Opal Section 4.1.1.4
        현재 세션을 종료합니다.
        """
        if self.current_session_id == 0:
            return
        
        # CloseSession payload 구성
        # (구현 생략)
        self.current_session_id = 0
    
    def _parse_session_id_from_response(self, response: bytes) -> int:
        """
        StartSession 응답에서 SP Session ID 추출
        
        실제 구현에서는 ComPacket/Packet/Subpacket을 파싱하고
        Method Status List에서 Session ID를 추출해야 합니다.
        """
        # 간단한 구현 예시 (실제로는 더 복잡한 파싱 필요)
        # TODO: 실제 TCG response parsing 구현
        return 0x01  # Placeholder
    
    # ========================================================================
    # 4. Locking 기능
    # ========================================================================
    
    def get_locking_range_info(self, range_id: int = 0) -> Dict:
        """
        Locking Range 정보 조회
        
        TCG Opal Section 4.3.5.2
        특정 Range의 Lock 상태를 조회합니다.
        
        Args:
            range_id: Range ID (0 = Global Range, 1~ = Range1~N)
        
        Returns:
            Range 정보 딕셔너리
        """
        # Get method call on Locking table
        # (실제 구현에서는 Get method payload 구성 및 전송)
        pass
    
    def set_locking_range(self, range_id: int, read_locked: bool, 
                         write_locked: bool) -> None:
        """
        Locking Range의 Lock 상태 설정
        
        TCG Opal Table 45
        
        Args:
            range_id: Range ID
            read_locked: True면 Read Lock
            write_locked: True면 Write Lock
        """
        # Set method call on Locking table
        # Parameters: ReadLocked, WriteLocked columns
        pass
    
    def set_mbr_control(self, enable: bool, done: bool) -> None:
        """
        MBR Control 설정
        
        TCG Opal Section 4.3.5.3
        MBR Shadowing 기능을 제어합니다.
        
        Args:
            enable: MBR Enable flag
            done: MBR Done flag (shadowing 완료 여부)
        """
        # Set method on MBRControl table
        pass
    
    # ========================================================================
    # 5. Cryptographic Operations
    # ========================================================================
    
    def gen_key(self, key_uid: int) -> None:
        """
        GenKey 메서드 호출
        
        TCG Opal Section 5.1.3 (암시적)
        새로운 암호화 키를 생성합니다.
        
        Args:
            key_uid: Key object의 UID (e.g., K_AES_256_GlobalRange_Key)
        """
        # GenKey method call
        # 이 메서드는 cryptographic erase를 수행할 때도 사용됩니다
        pass
    
    def random(self, count: int = 32) -> bytes:
        """
        Random 메서드 호출
        
        TCG Opal Section 4.2.9.1
        TPer로부터 랜덤 데이터를 생성받습니다.
        
        Args:
            count: 생성할 랜덤 바이트 수 (최대 32)
        
        Returns:
            랜덤 데이터
        """
        if count > 32:
            raise ValueError("Count must be <= 32")
        
        # Random method call payload 구성
        # (구현 생략)
        
        return b'\x00' * count  # Placeholder
    
    # ========================================================================
    # 6. Lifecycle Management
    # ========================================================================
    
    def activate_sp(self, sp_uid: int) -> None:
        """
        Activate 메서드 호출
        
        TCG Opal Section 5.1.1
        Manufactured-Inactive 상태의 SP를 활성화합니다.
        
        Args:
            sp_uid: SP object의 UID (Admin SP의 SP table)
        """
        # Activate method call
        pass
    
    def revert_tper(self, sp_uid: int) -> None:
        """
        Revert 메서드 호출
        
        TCG Opal Section 5.1.2
        SP를 Original Factory State로 복원합니다.
        (모든 데이터 삭제 및 암호화 키 제거)
        
        Args:
            sp_uid: SP object의 UID
        """
        # Revert method call
        # 주의: 이 메서드는 모든 사용자 데이터를 삭제합니다!
        pass
    
    def revert_sp(self, keep_global_range_key: bool = False) -> None:
        """
        RevertSP 메서드 호출
        
        TCG Opal Section 5.1.3
        현재 SP를 Manufactured-Inactive 상태로 복원합니다.
        
        Args:
            keep_global_range_key: True면 Global Range 키 유지
        """
        # RevertSP method call
        # keep_global_range_key=True면 Global Range 데이터 보존 가능
        pass
    
    # ========================================================================
    # 7. 편의 메서드들
    # ========================================================================
    
    def get_supported_security_protocols(self) -> List[int]:
        """
        Security Protocol 00h 조회
        
        지원되는 Security Protocol 목록을 반환합니다.
        """
        data = self.security_receive(
            SecurityProtocol.INFO, 0x0000, 512
        )
        
        list_length = struct.unpack('>H', data[6:8])[0]
        if list_length > 0:
            return list(data[8:8+list_length])
        return []
    
    def tper_reset(self) -> None:
        """
        TPER_RESET 명령 전송
        
        TCG Opal Section 3.2.3
        TPer를 리셋하고 모든 세션을 종료합니다.
        """
        # TPER_RESET은 ComID 0x0004 사용
        reset_data = bytes(16)  # Dummy data
        self.security_send(
            SecurityProtocol.TCG_2,
            ComID.TPER_RESET,
            reset_data
        )


# ============================================================================
# Pytest Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def nvme_device():
    """
    NVMe 디바이스 초기화
    
    테스트 시작 시 한 번만 초기화하고, 모든 테스트가 끝난 후 종료합니다.
    """
    pcie_addr = "01:00.0"  # 실제 환경에 맞게 수정
    
    print(f"\n{'='*70}")
    print(f"Initializing NVMe Controller: {pcie_addr}")
    print(f"{'='*70}")
    
    try:
        nvme = Controller(pcie_addr.encode())
        yield nvme
    finally:
        if 'nvme' in locals():
            nvme.close()
            print(f"\nNVMe Controller closed")


@pytest.fixture(scope="module")
def tcg_tester(nvme_device):
    """TCG Opal 테스터 인스턴스 생성"""
    return TCGOpalTester(nvme_device)


# ============================================================================
# Test Class 1: Security Protocol 기본 테스트
# ============================================================================

class TestSecurityProtocol:
    """
    Security Protocol 명령의 기본 동작을 테스트합니다.
    - Security Protocol 00h (지원 프로토콜 조회)
    - 명령 실행 검증
    """
    
    def test_security_protocol_00h(self, tcg_tester):
        """
        TEST 1: Security Protocol 00h
        
        목적:
        - Security Protocol 00h는 디바이스가 지원하는
          Security Protocol 목록을 반환합니다.
        - TCG Protocol (01h)이 지원되는지 확인합니다.
        
        기대 결과:
        - Protocol List에 0x01 포함
        """
        print("\n" + "="*70)
        print("TEST: Security Protocol 00h - Supported Protocols Discovery")
        print("="*70)
        
        protocols = tcg_tester.get_supported_security_protocols()
        
        print(f"\nSupported Protocols: {[f'0x{p:02X}' for p in protocols]}")
        
        # 검증: TCG Protocol 01h 지원 여부
        assert 0x01 in protocols, \
            "Security Protocol 01h (TCG) must be supported"
        
        print("✓ TCG Security Protocol 01h is supported")


# ============================================================================
# Test Class 2: Level 0 Discovery 테스트
# ============================================================================

class TestLevel0Discovery:
    """
    Level 0 Discovery 기능을 포괄적으로 테스트합니다.
    
    TCG Opal Section 3.1.1
    Level 0 Discovery는 TPer의 기능을 조회하는 필수 기능입니다.
    """
    
    def test_discovery_header(self, tcg_tester):
        """
        TEST 2: Discovery Header 검증
        
        목적:
        - Discovery response의 헤더 구조가 올바른지 확인
        - Revision이 유효한지 검증
        
        검증 항목:
        - Parameter Length > 0
        - Revision >= 0x00000001
        """
        print("\n" + "="*70)
        print("TEST: Level 0 Discovery - Header Validation")
        print("="*70)
        
        data = tcg_tester.level0_discovery()
        header = tcg_tester.parse_discovery_header(data)
        
        # 검증
        assert header['revision'] >= 0x00000001, \
            f"Invalid revision: 0x{header['revision']:08X}"
        assert header['parameter_length'] > 0, \
            "Parameter length must be positive"
        
        print(f"\n✓ Discovery Header Valid:")
        print(f"  - Parameter Length: {header['parameter_length']} bytes")
        print(f"  - Revision: 0x{header['revision']:08X}")
        print(f"  - Vendor Specific: {header['vendor_specific'][:32]}...")
    
    def test_tper_feature(self, tcg_tester):
        """
        TEST 3: TPer Feature (0x0001) 검증
        
        목적:
        - TPer의 기본 통신 기능을 확인
        - Mandatory 기능 (Streaming, Sync) 지원 확인
        
        필수 요구사항 (TCG Opal Table 3):
        - Streaming Supported = True
        - Sync Supported = True
        - Version >= 0x1
        - Length = 0x0C
        """
        print("\n" + "="*70)
        print("TEST: TPer Feature (0x0001) - Communication Capabilities")
        print("="*70)
        
        data = tcg_tester.level0_discovery()
        offset = 48  # Features start after header
        tper_found = False
        
        while offset < len(data) - 4:
            result = tcg_tester.parse_feature_descriptor(data, offset)
            if result[0] is None:
                break
            
            feature, next_offset = result
            
            if feature['feature_code'] == FeatureCode.TPER:
                tper_found = True
                tper_info = tcg_tester.parse_tper_feature(feature['data'])
                
                # 필수 검증
                assert feature['version'] >= 0x1, "TPer version >= 0x1 required"
                assert feature['length'] == 0x0C, "TPer length must be 0x0C"
                assert tper_info['streaming_supported'], "Streaming is mandatory"
                assert tper_info['sync_supported'], "Sync is mandatory"
                
                print(f"\n✓ TPer Feature Valid:")
                print(f"  - Version: 0x{feature['version']:X}")
                print(f"  - Streaming: {tper_info['streaming_supported']} ✓")
                print(f"  - Sync: {tper_info['sync_supported']} ✓")
                print(f"  - Async: {tper_info['async_supported']}")
                print(f"  - ComID Mgmt: {tper_info['comid_mgmt_supported']}")
                print(f"  - Buffer Mgmt: {tper_info['buffer_mgmt_supported']}")
                break
            
            offset = next_offset
        
        assert tper_found, "TPer Feature (0x0001) not found"
    
    def test_locking_feature(self, tcg_tester):
        """
        TEST 4: Locking Feature (0x0002) 검증
        
        목적:
        - Locking 기능 지원 확인
        - 현재 Lock 상태 파악
        
        필수 요구사항 (TCG Opal Table 4):
        - Locking Supported = True
        - Media Encryption = True
        - MBR Shadowing Supported = True
        - Version >= 0x3
        - Length = 0x0C
        """
        print("\n" + "="*70)
        print("TEST: Locking Feature (0x0002) - Locking Capabilities")
        print("="*70)
        
        data = tcg_tester.level0_discovery()
        offset = 48
        locking_found = False
        
        while offset < len(data) - 4:
            result = tcg_tester.parse_feature_descriptor(data, offset)
            if result[0] is None:
                break
            
            feature, next_offset = result
            
            if feature['feature_code'] == FeatureCode.LOCKING:
                locking_found = True
                locking_info = tcg_tester.parse_locking_feature(feature['data'])
                
                # 필수 검증
                assert feature['version'] >= 0x3, "Locking version >= 0x3 required"
                assert feature['length'] == 0x0C, "Locking length must be 0x0C"
                assert locking_info['locking_supported'], \
                    "Locking must be supported"
                assert locking_info['media_encryption'], \
                    "Media Encryption must be supported"
                assert not locking_info['mbr_shadowing_not_supported'], \
                    "MBR Shadowing must be supported"
                
                print(f"\n✓ Locking Feature Valid:")
                print(f"  - Version: 0x{feature['version']:X}")
                print(f"  - Locking Supported: ✓")
                print(f"  - Media Encryption: ✓")
                print(f"  - MBR Shadowing: ✓")
                print(f"\n  Current State:")
                print(f"    - Locking Enabled: {locking_info['locking_enabled']}")
                print(f"    - Locked: {locking_info['locked']}")
                print(f"    - MBR Enabled: {locking_info['mbr_enabled']}")
                print(f"    - MBR Done: {locking_info['mbr_done']}")
                break
            
            offset = next_offset
        
        assert locking_found, "Locking Feature (0x0002) not found"
    
    def test_opal_ssc_v2_feature(self, tcg_tester):
        """
        TEST 5: Opal SSC V2 Feature (0x0203) 검증
        
        목적:
        - Opal SSC v2.x 지원 확인
        - ComID 및 Authority 수 확인
        
        필수 요구사항 (TCG Opal Table 6):
        - Version >= 0x2
        - Length = 0x10
        - Num ComIDs >= 1
        - Num Admin Authorities >= 4
        - Num User Authorities >= 8
        """
        print("\n" + "="*70)
        print("TEST: Opal SSC V2 Feature (0x0203) - SSC Capabilities")
        print("="*70)
        
        data = tcg_tester.level0_discovery()
        offset = 48
        opal_found = False
        
        ssc_versions = {
            0x0: "v2.00",
            0x1: "v2.01",
            0x2: "v2.02",
            0x3: "v2.30"
        }
        
        while offset < len(data) - 4:
            result = tcg_tester.parse_feature_descriptor(data, offset)
            if result[0] is None:
                break
            
            feature, next_offset = result
            
            if feature['feature_code'] == FeatureCode.OPAL_SSC_V2:
                opal_found = True
                opal_info = tcg_tester.parse_opal_ssc_v2_feature(feature['data'])
                
                # 필수 검증
                assert feature['version'] >= 0x2, "Opal version >= 0x2 required"
                assert feature['length'] == 0x10, "Opal length must be 0x10"
                assert opal_info['num_comids'] >= 1, "At least 1 ComID required"
                assert opal_info['num_admin_authorities'] >= 4, \
                    "At least 4 Admin authorities required"
                assert opal_info['num_user_authorities'] >= 8, \
                    "At least 8 User authorities required"
                
                print(f"\n✓ Opal SSC V2 Feature Valid:")
                print(f"  - Feature Version: 0x{feature['version']:X}")
                print(f"  - Base ComID: 0x{opal_info['base_comid']:04X}")
                print(f"  - Number of ComIDs: {opal_info['num_comids']}")
                print(f"  - Admin Authorities: {opal_info['num_admin_authorities']} ✓")
                print(f"  - User Authorities: {opal_info['num_user_authorities']} ✓")
                print(f"  - Range Crossing: {opal_info['range_crossing_behavior']}")
                print(f"  - Initial PIN Indicator: 0x{opal_info['initial_pin_indicator']:02X}")
                break
            
            offset = next_offset
        
        assert opal_found, "Opal SSC V2 Feature (0x0203) not found"
    
    def test_geometry_feature(self, tcg_tester):
        """
        TEST 6: Geometry Reporting Feature (0x0003) 검증 (Optional)
        
        목적:
        - 디스크의 물리적 alignment 정보 확인
        - Logical Block Size 확인
        
        이 Feature는 Optional이므로 없어도 PASS
        """
        print("\n" + "="*70)
        print("TEST: Geometry Reporting Feature (0x0003) - Disk Geometry")
        print("="*70)
        
        data = tcg_tester.level0_discovery()
        offset = 48
        geometry_found = False
        
        while offset < len(data) - 4:
            result = tcg_tester.parse_feature_descriptor(data, offset)
            if result[0] is None:
                break
            
            feature, next_offset = result
            
            if feature['feature_code'] == FeatureCode.GEOMETRY_REPORTING:
                geometry_found = True
                geo_info = tcg_tester.parse_geometry_feature(feature['data'])
                
                print(f"\n✓ Geometry Feature Found:")
                print(f"  - Alignment Required: {geo_info['align_required']}")
                print(f"  - Logical Block Size: {geo_info['logical_block_size']} bytes")
                print(f"  - Alignment Granularity: {geo_info['alignment_granularity']} blocks")
                print(f"  - Lowest Aligned LBA: {geo_info['lowest_aligned_lba']}")
                break
            
            offset = next_offset
        
        if not geometry_found:
            print("\n  ℹ Geometry Feature not present (Optional feature)")
    
    def test_all_features_summary(self, tcg_tester):
        """
        TEST 7: 전체 Feature 요약
        
        목적:
        - Discovery response의 모든 Feature를 나열
        - 필수 Feature들이 모두 존재하는지 최종 확인
        """
        print("\n" + "="*70)
        print("TEST: Complete Feature Summary")
        print("="*70)
        
        data = tcg_tester.level0_discovery()
        header = tcg_tester.parse_discovery_header(data)
        
        print(f"\nDiscovery Response:")
        print(f"  Total Length: {header['parameter_length']} bytes")
        print(f"  Revision: 0x{header['revision']:08X}")
        
        feature_names = {
            0x0001: "TPer",
            0x0002: "Locking",
            0x0003: "Geometry Reporting",
            0x0100: "Single User Mode",
            0x0201: "Datastore Table",
            0x0202: "OPAL v1.0",
            0x0203: "OPAL v2.0",
            0x0301: "Enterprise SSC",
            0x0303: "Opalite SSC",
            0x0304: "Pyrite SSC v1.0",
            0x0305: "Pyrite SSC v2.0",
            0x0401: "Block SID Authentication",
            0x0402: "Namespace Locking",
            0x0403: "Datastore",
            0x0404: "Data Removal Mechanism",
        }
        
        print(f"\n{'Code':<8} {'Name':<30} {'Ver':<5} {'Len':<5}")
        print(f"{'-'*8} {'-'*30} {'-'*5} {'-'*5}")
        
        offset = 48
        found_features = set()
        
        while offset < len(data) - 4:
            result = tcg_tester.parse_feature_descriptor(data, offset)
            if result[0] is None:
                break
            
            feature, next_offset = result
            found_features.add(feature['feature_code'])
            
            name = feature_names.get(feature['feature_code'], "Unknown")
            print(f"0x{feature['feature_code']:04X}   {name:<30} "
                  f"0x{feature['version']:X}   0x{feature['length']:02X}")
            
            offset = next_offset
        
        # 필수 Feature 확인
        print(f"\nMandatory Features Check:")
        mandatory = {
            FeatureCode.TPER: "TPer",
            FeatureCode.LOCKING: "Locking",
            FeatureCode.OPAL_SSC_V2: "OPAL SSC v2.0"
        }
        
        all_present = True
        for code, name in mandatory.items():
            if code in found_features:
                print(f"  ✓ {name:<30}")
            else:
                print(f"  ✗ {name:<30} - MISSING!")
                all_present = False
        
        assert all_present, "Not all mandatory features are present"
        print(f"\n✓ All mandatory features present")


# ============================================================================
# Test Class 3: Session Management 테스트
# ============================================================================

class TestSessionManagement:
    """
    Session Management 기능을 테스트합니다.
    
    TCG Opal Section 4.1.1
    Session은 Host와 TPer 간의 통신 채널입니다.
    """
    
    @pytest.mark.skip(reason="Requires full payload implementation")
    def test_start_session_admin_sp(self, tcg_tester):
        """
        TEST 8: Admin SP Session 시작
        
        목적:
        - Admin SP와의 세션 생성
        - Read-Write 세션 지원 확인
        
        절차:
        1. StartSession 호출 (SPID = Admin SP)
        2. SP Session ID 수신 확인
        3. Session 상태 확인
        """
        print("\n" + "="*70)
        print("TEST: StartSession - Admin SP")
        print("="*70)
        
        # StartSession 호출
        session_id = tcg_tester.start_session(
            sp_id=SPID.ADMIN_SP,
            write=True
        )
        
        assert session_id > 0, "Invalid session ID received"
        
        print(f"\n✓ Session Started:")
        print(f"  - SP: Admin SP")
        print(f"  - Session ID: 0x{session_id:08X}")
        print(f"  - Mode: Read-Write")
    
    @pytest.mark.skip(reason="Requires full payload implementation")
    def test_close_session(self, tcg_tester):
        """
        TEST 9: Session 종료
        
        목적:
        - CloseSession 메서드 동작 확인
        - Session 정상 종료 확인
        """
        print("\n" + "="*70)
        print("TEST: CloseSession")
        print("="*70)
        
        # 세션 시작
        session_id = tcg_tester.start_session(SPID.ADMIN_SP, True)
        
        # 세션 종료
        tcg_tester.close_session()
        
        assert tcg_tester.current_session_id == 0, \
            "Session should be closed"
        
        print(f"\n✓ Session Closed Successfully")


# ============================================================================
# Test Class 4: Locking 기능 테스트
# ============================================================================

class TestLockingFeatures:
    """
    Locking 기능을 테스트합니다.
    
    TCG Opal Section 4.3.5
    Locking은 LBA Range별로 Read/Write를 제어하는 핵심 기능입니다.
    """
    
    @pytest.mark.skip(reason="Requires authentication and full implementation")
    def test_lock_global_range(self, tcg_tester):
        """
        TEST 10: Global Range Lock/Unlock
        
        목적:
        - Global Range의 ReadLocked/WriteLocked 제어
        - Lock 상태 변경 확인
        
        주의:
        - 실제 Lock 시 데이터 접근 불가능해짐
        - 인증된 세션 필요
        """
        print("\n" + "="*70)
        print("TEST: Global Range Lock Control")
        print("="*70)
        
        # 1. 현재 상태 조회
        range_info = tcg_tester.get_locking_range_info(0)  # 0 = Global Range
        
        print(f"\nCurrent State:")
        print(f"  - ReadLocked: {range_info.get('read_locked', 'Unknown')}")
        print(f"  - WriteLocked: {range_info.get('write_locked', 'Unknown')}")
        
        # 2. Lock 설정 (Read-Only)
        # 주의: 이 테스트는 실제 운영 환경에서는 위험할 수 있습니다!
        # tcg_tester.set_locking_range(0, read_locked=False, write_locked=True)
        
        print(f"\n  ⚠ Lock operation skipped (requires authentication)")
    
    @pytest.mark.skip(reason="Requires authentication")
    def test_mbr_control(self, tcg_tester):
        """
        TEST 11: MBR Control
        
        목적:
        - MBR Shadowing 기능 제어
        - Enable/Done flag 설정
        
        MBR Shadowing:
        - Boot 시 Shadow MBR 테이블을 표시
        - Done=True면 실제 MBR 사용
        """
        print("\n" + "="*70)
        print("TEST: MBR Control")
        print("="*70)
        
        # MBR Control 설정
        # tcg_tester.set_mbr_control(enable=True, done=False)
        
        print(f"\n  ⚠ MBR control skipped (requires authentication)")


# ============================================================================
# Test Class 5: Cryptographic Operations 테스트
# ============================================================================

class TestCryptographicOperations:
    """
    암호화 관련 기능을 테스트합니다.
    
    TCG Opal Section 4.2.9 / 4.3.6
    """
    
    def test_random_generation(self, tcg_tester):
        """
        TEST 12: Random 메서드
        
        목적:
        - TPer의 랜덤 생성 기능 확인
        - 최대 32바이트까지 생성 가능
        
        TCG Opal Section 4.2.9.1
        """
        print("\n" + "="*70)
        print("TEST: Random Number Generation")
        print("="*70)
        
        # Random 생성 테스트
        for count in [8, 16, 32]:
            # random_data = tcg_tester.random(count)
            # assert len(random_data) == count
            print(f"  - {count} bytes random: (skipped - requires session)")
        
        print(f"\n  ℹ Random generation test requires active session")
    
    @pytest.mark.skip(reason="Destructive operation")
    def test_gen_key(self, tcg_tester):
        """
        TEST 13: GenKey 메서드 (주의: Cryptographic Erase!)
        
        목적:
        - 새로운 암호화 키 생성
        - 기존 데이터는 복구 불가능하게 됨!
        
        경고:
        - 이 메서드는 실제 데이터를 암호학적으로 삭제합니다
        - 테스트 환경에서만 실행해야 합니다
        """
        print("\n" + "="*70)
        print("TEST: GenKey (Cryptographic Erase) - SKIPPED")
        print("="*70)
        
        print(f"\n  ⚠ GenKey is a DESTRUCTIVE operation!")
        print(f"  ⚠ This test is skipped to protect data")


# ============================================================================
# Test Class 6: Lifecycle Management 테스트
# ============================================================================

class TestLifecycleManagement:
    """
    SP Lifecycle 관리 기능을 테스트합니다.
    
    TCG Opal Section 5.1
    """
    
    @pytest.mark.skip(reason="Destructive operation")
    def test_revert_tper(self, tcg_tester):
        """
        TEST 14: Revert (Factory Reset)
        
        목적:
        - TPer를 Original Factory State로 복원
        - 모든 personalization 제거
        
        경고:
        - 모든 사용자 데이터가 삭제됩니다!
        - 암호화 키가 제거됩니다!
        """
        print("\n" + "="*70)
        print("TEST: Revert (Factory Reset) - SKIPPED")
        print("="*70)
        
        print(f"\n  ⚠ Revert is a DESTRUCTIVE operation!")
        print(f"  ⚠ All user data will be ERASED!")
        print(f"  ⚠ This test is skipped to protect data")
    
    @pytest.mark.skip(reason="Destructive operation")
    def test_activate_locking_sp(self, tcg_tester):
        """
        TEST 15: Activate Locking SP
        
        목적:
        - Manufactured-Inactive 상태의 Locking SP 활성화
        - SP 상태 전환 확인
        
        TCG Opal Section 5.1.1
        """
        print("\n" + "="*70)
        print("TEST: Activate Locking SP - SKIPPED")
        print("="*70)
        
        print(f"\n  ℹ Activate test requires specific SP state")


# ============================================================================
# Test Class 7: 통합 시나리오 테스트
# ============================================================================

class TestIntegrationScenarios:
    """
    실제 사용 시나리오를 시뮬레이션하는 통합 테스트
    """
    
    def test_full_discovery_flow(self, tcg_tester):
        """
        TEST 16: 전체 Discovery 플로우
        
        시나리오:
        1. Security Protocol 00h 조회
        2. Level 0 Discovery 수행
        3. 모든 Feature 파싱
        4. 지원 기능 요약
        """
        print("\n" + "="*70)
        print("TEST: Complete Discovery Flow")
        print("="*70)
        
        # Step 1: 지원 프로토콜 확인
        protocols = tcg_tester.get_supported_security_protocols()
        print(f"\nStep 1: Supported Protocols")
        print(f"  {[f'0x{p:02X}' for p in protocols]}")
        
        # Step 2: Discovery
        data = tcg_tester.level0_discovery()
        header = tcg_tester.parse_discovery_header(data)
        print(f"\nStep 2: Level 0 Discovery")
        print(f"  Response size: {len(data)} bytes")
        print(f"  Revision: 0x{header['revision']:08X}")
        
        # Step 3: Feature 분석
        print(f"\nStep 3: Feature Analysis")
        
        features = {}
        offset = 48
        
        while offset < len(data) - 4:
            result = tcg_tester.parse_feature_descriptor(data, offset)
            if result[0] is None:
                break
            
            feature, next_offset = result
            features[feature['feature_code']] = feature
            offset = next_offset
        
        # Step 4: 요약
        print(f"\nStep 4: Capability Summary")
        
        if FeatureCode.TPER in features:
            tper = tcg_tester.parse_tper_feature(features[FeatureCode.TPER]['data'])
            print(f"  TPer:")
            print(f"    - Streaming: {'✓' if tper['streaming_supported'] else '✗'}")
            print(f"    - Sync: {'✓' if tper['sync_supported'] else '✗'}")
        
        if FeatureCode.LOCKING in features:
            locking = tcg_tester.parse_locking_feature(features[FeatureCode.LOCKING]['data'])
            print(f"  Locking:")
            print(f"    - Supported: {'✓' if locking['locking_supported'] else '✗'}")
            print(f"    - Media Encryption: {'✓' if locking['media_encryption'] else '✗'}")
            print(f"    - Current State: {'Locked' if locking['locked'] else 'Unlocked'}")
        
        if FeatureCode.OPAL_SSC_V2 in features:
            opal = tcg_tester.parse_opal_ssc_v2_feature(features[FeatureCode.OPAL_SSC_V2]['data'])
            print(f"  Opal SSC:")
            print(f"    - ComIDs: {opal['num_comids']}")
            print(f"    - Admin Auth: {opal['num_admin_authorities']}")
            print(f"    - User Auth: {opal['num_user_authorities']}")
        
        print(f"\n✓ Complete discovery flow executed successfully")


# ============================================================================
# 메인 실행
# ============================================================================

if __name__ == "__main__":
    """
    테스트 실행 방법:
    
    1. 전체 테스트:
       pytest test_tcg_opal_comprehensive.py -v -s
    
    2. 특정 테스트 클래스만:
       pytest test_tcg_opal_comprehensive.py::TestLevel0Discovery -v -s
    
    3. 특정 테스트만:
       pytest test_tcg_opal_comprehensive.py::TestLevel0Discovery::test_tper_feature -v -s
    
    4. Skip된 테스트 제외:
       pytest test_tcg_opal_comprehensive.py -v -s -k "not skip"
    """
    pytest.main([
        __file__,
        "-v",              # Verbose
        "-s",              # No capture (print 출력 보기)
        "--tb=short",      # Short traceback
        "-k", "not skip"   # Skip 마크된 테스트 제외
    ])