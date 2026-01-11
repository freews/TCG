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

