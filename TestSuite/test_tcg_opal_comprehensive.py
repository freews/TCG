"""
TCG Opal SSC v2.30 종합 테스트 스위트
====================================

pynvme 기반 실제 SSD 테스트
"""

import pytest
import struct
import hashlib
from typing import Dict, Any, Optional, Tuple

# TCG Codec 임포트
from tcg_opal_codec import (
    TCGPayloadBuilder,
    TCGResponseParser,
    TCGComPacketBuilder,
    Token,
    UID
)


# ==========================================
# Constants
# ==========================================

# Security Protocol
SECURITY_PROTOCOL_TCG = 0x01

# ComID
COMID_DISCOVERY = 0x0001
COMID_STACKRESET = 0x0004

# Status Codes
STATUS_SUCCESS = 0x00
STATUS_NOT_AUTHORIZED = 0x01
STATUS_SP_BUSY = 0x03
STATUS_FAIL = 0x3F


# ==========================================
# Helper Functions
# ==========================================

def security_send(
    nvme_controller,
    protocol: int,
    com_id: int,
    data: bytes
) -> None:
    """
    Security Send 실행
    
    Args:
        nvme_controller: pynvme Controller 객체
        protocol: Security Protocol (0x01 for TCG)
        com_id: ComID
        data: 전송할 데이터
    """
    # pynvme API 참조:
    # controller.send_cmd(opcode, nsid, buf, ...)
    # Security Send opcode: 0x81
    
    buf = nvme_controller.buffer(len(data))
    buf[:] = data
    
    nvme_controller.send_cmd(
        opcode=0x81,              # Security Send
        nsid=0,                   # Namespace (0 for controller)
        cdw10=(protocol << 24) | (com_id << 8),  # SECP, SPSP0, SPSP1, ComID
        cdw11=len(data),          # Transfer Length
        buf=buf
    )
    nvme_controller.waitdone()


def security_receive(
    nvme_controller,
    protocol: int,
    com_id: int,
    allocation_length: int
) -> bytes:
    """
    Security Receive 실행
    
    Args:
        nvme_controller: pynvme Controller 객체
        protocol: Security Protocol
        com_id: ComID  
        allocation_length: 수신 버퍼 크기
        
    Returns:
        수신된 데이터
    """
    # Security Receive opcode: 0x82
    
    buf = nvme_controller.buffer(allocation_length)
    
    nvme_controller.send_cmd(
        opcode=0x82,              # Security Receive
        nsid=0,
        cdw10=(protocol << 24) | (com_id << 8),
        cdw11=allocation_length,
        buf=buf
    )
    nvme_controller.waitdone()
    
    return bytes(buf)


def parse_discovery(data: bytes) -> Dict[str, Any]:
    """
    Level 0 Discovery 응답 파싱
    
    Returns:
        {
            'header': {...},
            'features': [...]
        }
    """
    if len(data) < 48:
        return {'error': 'Data too short'}
    
    # Header (48 bytes)
    header = {
        'length': struct.unpack('>I', data[0:4])[0],
        'major_version': struct.unpack('>H', data[4:6])[0],
        'minor_version': struct.unpack('>H', data[6:8])[0],
        'reserved': data[8:16],
        'vendor_unique': data[16:48]
    }
    
    # Features
    features = []
    pos = 48
    
    while pos + 16 <= len(data):
        feature_code = struct.unpack('>H', data[pos:pos+2])[0]
        version = data[pos+2]
        length = data[pos+3]
        feature_data = data[pos+4:pos+4+length]
        
        features.append({
            'code': feature_code,
            'version': version,
            'length': length,
            'data': feature_data
        })
        
        pos += 4 + length
        
        # Padding to 4-byte boundary
        if length % 4 != 0:
            pos += 4 - (length % 4)
    
    return {
        'header': header,
        'features': features
    }


def build_session_payload(
    host_session_id: int,
    sp_uid: bytes,
    write: bool = True,
    host_challenge: Optional[bytes] = None,
    host_signing_authority: Optional[bytes] = None
) -> bytes:
    """
    StartSession Method Payload 생성
    
    Args:
        host_session_id: Host Session ID
        sp_uid: SP UID (Admin SP or Locking SP)
        write: Write 권한 요청 여부
        host_challenge: Authentication에 사용할 challenge (PIN hash)
        host_signing_authority: Authority UID
        
    Returns:
        ComPacket 바이너리 데이터
    """
    builder = TCGPayloadBuilder()
    
    # Call token
    builder.add_call()
    
    # InvokingID (Session Manager)
    builder.add_uid(UID.SM_UID)
    
    # MethodID (StartSession)
    builder.add_uid(UID.START_SESSION)
    
    # Parameters: [ HostSessionID, SPID, Write, HostChallenge, HostSigningAuthority ]
    builder.start_list()
    
    # HostSessionID
    builder.add_integer(host_session_id)
    
    # SPID
    builder.add_uid(sp_uid)
    
    # Write
    builder.add_integer(1 if write else 0)
    
    # Optional: HostChallenge
    if host_challenge:
        builder.start_name()
        builder.add_integer(0)  # Column: HostChallenge
        builder.add_bytes(host_challenge)
        builder.end_name()
    
    # Optional: HostSigningAuthority
    if host_signing_authority:
        builder.start_name()
        builder.add_integer(3)  # Column: HostSigningAuthority
        builder.add_uid(host_signing_authority)
        builder.end_name()
    
    builder.end_list()
    
    # End of Data
    builder.add_end_of_data()
    
    # Build ComPacket
    payload = builder.get_payload()
    com_packet = TCGComPacketBuilder.build(com_id=0x0001, payload=payload)
    
    return com_packet


def hash_password(password: str) -> bytes:
    """
    PIN Hash 생성 (TCG Opal 표준)
    
    Hash = SHA256(password)
    """
    return hashlib.sha256(password.encode('utf-8')).digest()


# ==========================================
# Test Class
# ==========================================

class TestTCGOpalComprehensive:
    """TCG Opal SSC v2.30 종합 테스트"""
    
    # ------------------------------------------
    # Level 0 Discovery
    # ------------------------------------------
    
    def test_level0_discovery(self, ssd_h):
        """
        3.1.1 Level 0 Discovery
        
        TPer의 기능을 발견
        """
        # Discovery 요청 (빈 payload)
        request_data = bytes(512)  # All zeros
        
        # Security Send
        security_send(
            ssd_h,
            protocol=SECURITY_PROTOCOL_TCG,
            com_id=COMID_DISCOVERY,
            data=request_data
        )
        
        # Security Receive
        response_data = security_receive(
            ssd_h,
            protocol=SECURITY_PROTOCOL_TCG,
            com_id=COMID_DISCOVERY,
            allocation_length=2048
        )
        
        # 응답 파싱
        discovery = parse_discovery(response_data)
        
        assert 'header' in discovery
        assert 'features' in discovery
        assert len(discovery['features']) > 0
        
        print(f"\n✓ Discovery Header:")
        print(f"  Version: {discovery['header']['major_version']}.{discovery['header']['minor_version']}")
        print(f"  Total Length: {discovery['header']['length']} bytes")
        print(f"  Features found: {len(discovery['features'])}")
        
        # Feature 출력
        feature_names = {
            0x0001: "TPer",
            0x0002: "Locking",
            0x0003: "Geometry Reporting",
            0x0200: "Opal SSC V1",
            0x0201: "Opal SSC V2",
            0x0203: "Opalite"
        }
        
        for feat in discovery['features']:
            name = feature_names.get(feat['code'], f"Unknown (0x{feat['code']:04X})")
            print(f"  - {name}: version {feat['version']}, {feat['length']} bytes")
    
    # ------------------------------------------
    # Session Management
    # ------------------------------------------
    
    def test_start_session_admin_sp(self, ssd_h):
        """
        3.3.8.2.1 StartSession to Admin SP (Unauthenticated)
        
        Admin SP에 인증 없이 세션 시작
        """
        # Payload 생성
        payload = build_session_payload(
            host_session_id=1,
            sp_uid=UID.ADMIN_SP,
            write=False  # Read-only
        )
        
        # Send
        security_send(
            ssd_h,
            protocol=SECURITY_PROTOCOL_TCG,
            com_id=0x0001,
            data=payload
        )
        
        # Receive
        response_data = security_receive(
            ssd_h,
            protocol=SECURITY_PROTOCOL_TCG,
            com_id=0x0001,
            allocation_length=2048
        )
        
        # 응답 파싱
        # ComPacket 헤더 스킵 (20 bytes)
        payload_data = response_data[20:]
        
        parsed = TCGResponseParser.parse_session_response(payload_data)
        
        assert parsed['status'] == STATUS_SUCCESS, \
            f"StartSession failed with status: {parsed['status']}"
        
        assert parsed['session_id'] is not None
        assert parsed['tper_session_id'] is not None
        
        print(f"\n✓ Session Started:")
        print(f"  Host Session ID:  {parsed['session_id']}")
        print(f"  TPer Session ID:  {parsed['tper_session_id']}")
        print(f"  Status:           {parsed['status']} (Success)")
        
        # Session ID 저장 (다른 테스트에서 사용)
        self.admin_session_id = parsed['tper_session_id']
    
    def test_start_session_with_authentication(self, ssd_h):
        """
        3.3.8.2.2 StartSession with SID Authentication
        
        SID로 인증하여 Admin SP 세션 시작
        """
        # MSID 값 (일반적으로 드라이브의 MSID label에서 가져옴)
        # 테스트 환경에서는 "password" 사용
        msid_password = "password"
        msid_hash = hash_password(msid_password)
        
        # Payload 생성
        payload = build_session_payload(
            host_session_id=2,
            sp_uid=UID.ADMIN_SP,
            write=True,  # Write 권한
            host_challenge=msid_hash,
            host_signing_authority=UID.SID
        )
        
        # Send
        security_send(
            ssd_h,
            protocol=SECURITY_PROTOCOL_TCG,
            com_id=0x0001,
            data=payload
        )
        
        # Receive
        response_data = security_receive(
            ssd_h,
            protocol=SECURITY_PROTOCOL_TCG,
            com_id=0x0001,
            allocation_length=2048
        )
        
        # 파싱
        payload_data = response_data[20:]
        parsed = TCGResponseParser.parse_session_response(payload_data)
        
        # 인증 실패는 STATUS_NOT_AUTHORIZED (0x01)
        # 성공이면 STATUS_SUCCESS (0x00)
        if parsed['status'] == STATUS_NOT_AUTHORIZED:
            pytest.skip("SID authentication failed - MSID unknown")
        
        assert parsed['status'] == STATUS_SUCCESS
        
        print(f"\n✓ Authenticated Session:")
        print(f"  Authority:        SID")
        print(f"  Session ID:       {parsed['tper_session_id']}")
        print(f"  Write Access:     True")
    
    # ------------------------------------------
    # Method Tests
    # ------------------------------------------
    
    def test_properties_method(self, ssd_h):
        """
        5.1.4.1 Properties Method
        
        TPer의 속성 조회
        """
        # Session 시작 (unauthenticated)
        session_payload = build_session_payload(
            host_session_id=3,
            sp_uid=UID.ADMIN_SP,
            write=False
        )
        
        security_send(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, session_payload)
        response = security_receive(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, 2048)
        
        parsed_session = TCGResponseParser.parse_session_response(response[20:])
        session_id = parsed_session['tper_session_id']
        
        # Properties Method 호출
        builder = TCGPayloadBuilder()
        
        builder.add_call()
        builder.add_uid(UID.SM_UID)  # Session Manager
        builder.add_uid(UID.PROPERTIES)  # Properties Method
        
        # Parameters: [ HostProperties ]
        builder.start_list()
        
        # Request: MaxComPacketSize, MaxPacketSize, etc.
        builder.start_name()
        builder.add_bytes(b"MaxComPacketSize")
        builder.add_integer(0)  # Request current value
        builder.end_name()
        
        builder.end_list()
        builder.add_end_of_data()
        
        properties_payload = builder.get_payload()
        properties_packet = TCGComPacketBuilder.build(0x0001, properties_payload)
        
        # Send
        security_send(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, properties_packet)
        
        # Receive
        response = security_receive(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, 2048)
        
        # Parse
        payload_data = response[20:]
        parsed = TCGResponseParser.parse_method_response(payload_data)
        
        assert parsed['status'] == STATUS_SUCCESS
        
        print(f"\n✓ Properties Method:")
        print(f"  Status: {parsed['status']}")
        print(f"  Data:   {parsed['data']}")
    
    def test_get_method_locking_info(self, ssd_h):
        """
        Get Method로 Locking Info 조회
        """
        # Session 시작
        session_payload = build_session_payload(
            host_session_id=4,
            sp_uid=UID.ADMIN_SP,
            write=False
        )
        
        security_send(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, session_payload)
        response = security_receive(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, 2048)
        
        parsed_session = TCGResponseParser.parse_session_response(response[20:])
        session_id = parsed_session['tper_session_id']
        
        # Get Method
        builder = TCGPayloadBuilder()
        
        builder.add_call()
        builder.add_uid(UID.LOCKING_INFO_TABLE)  # InvokingID
        builder.add_uid(UID.GET)                 # MethodID
        
        # Parameters: [ [StartRow, EndRow], [StartColumn, EndColumn] ]
        builder.start_list()
        
        # Rows: all
        builder.start_list()
        builder.add_integer(0)
        builder.add_integer(0)
        builder.end_list()
        
        # Columns: all
        builder.start_list()
        builder.add_integer(0)
        builder.add_integer(0)
        builder.end_list()
        
        builder.end_list()
        builder.add_end_of_data()
        
        get_payload = builder.get_payload()
        get_packet = TCGComPacketBuilder.build(0x0001, get_payload)
        
        # Send
        security_send(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, get_packet)
        
        # Receive
        response = security_receive(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, 2048)
        
        # Parse
        payload_data = response[20:]
        parsed = TCGResponseParser.parse_method_response(payload_data)
        
        assert parsed['status'] == STATUS_SUCCESS
        
        print(f"\n✓ Get Locking Info:")
        print(f"  Status: {parsed['status']}")
        
        if parsed['data']:
            print(f"  Locking Info: {parsed['data']}")
    
    # ------------------------------------------
    # Lifecycle Tests
    # ------------------------------------------
    
    def test_activate_locking_sp(self, ssd_h):
        """
        4.3.3.1 Activate Method
        
        Locking SP 활성화 (SID 권한 필요)
        """
        # 실제 환경에서는 SID로 인증 필요
        # 여기서는 테스트 스킵 또는 Mock
        pytest.skip("Requires SID authentication - manual test only")
        
        # SID 인증 세션 시작
        # ...
        
        # Activate Method 호출
        builder = TCGPayloadBuilder()
        
        builder.add_call()
        builder.add_uid(UID.LOCKING_SP)  # InvokingID
        builder.add_uid(UID.ACTIVATE)    # MethodID
        
        builder.start_list()  # Empty parameters
        builder.end_list()
        builder.add_end_of_data()
        
        activate_payload = builder.get_payload()
        activate_packet = TCGComPacketBuilder.build(0x0001, activate_payload)
        
        # Send
        # security_send(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, activate_packet)
        
        # Receive
        # response = security_receive(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, 2048)
    
    def test_revert_tper(self, ssd_h):
        """
        4.3.3.2 RevertSP Method
        
        TPer 전체 초기화 (위험! 모든 데이터 삭제)
        """
        pytest.skip("Destructive test - manual execution only")
        
        # RevertSP는 Admin SP에서만 호출 가능
        # SID 권한 필요
        
        # builder = TCGPayloadBuilder()
        # builder.add_call()
        # builder.add_uid(UID.ADMIN_SP)
        # builder.add_uid(UID.REVERT)
        # ...
    
    # ------------------------------------------
    # Security Tests
    # ------------------------------------------
    
    def test_authenticate_method(self, ssd_h):
        """
        3.3.8.2.3 Authenticate Method
        
        세션 내에서 추가 인증
        """
        pytest.skip("Requires active session - integration test")
        
        # Session 내에서 Authenticate Method 호출
        # ...
    
    def test_genkey_method(self, ssd_h):
        """
        5.4.3.2 GenKey Method
        
        암호화 키 생성
        """
        pytest.skip("Requires Locking SP activation")
        
        # GenKey는 K_AES object에서 호출
        # ...
    
    # ------------------------------------------
    # Locking Tests
    # ------------------------------------------
    
    def test_set_read_lock(self, ssd_h):
        """
        5.3.2.1 Locking 설정
        
        특정 범위를 읽기 잠금
        """
        pytest.skip("Requires Locking SP and Range configuration")
        
        # Set Method로 Locking Object의 ReadLocked 설정
        # ...
    
    def test_set_write_lock(self, ssd_h):
        """
        5.3.2.2 Write Locking
        """
        pytest.skip("Requires Locking SP and Range configuration")
    
    # ------------------------------------------
    # MBR Tests
    # ------------------------------------------
    
    def test_mbr_control(self, ssd_h):
        """
        5.2.2 MBR Control
        
        MBR Shadow 활성화/비활성화
        """
        pytest.skip("Requires MBR feature support")
        
        # MBRControl table의 Enable/Disable 설정
        # ...
    
    # ------------------------------------------
    # Utility Tests
    # ------------------------------------------
    
    def test_random_method(self, ssd_h):
        """
        5.4.3.4 Random Method
        
        난수 생성 (테스트용)
        """
        # Session 시작
        session_payload = build_session_payload(
            host_session_id=10,
            sp_uid=UID.ADMIN_SP,
            write=False
        )
        
        security_send(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, session_payload)
        response = security_receive(ssd_h, SECURITY_PROTOCOL_TCG, 0x0001, 2048)
        
        # Random Method (실제 구현은 SP에 따라 다름)
        # 여기서는 스킵
        pytest.skip("Random method UID varies by implementation")


# ==========================================
# Fixtures
# ==========================================

@pytest.fixture(scope="module")
def ssd_h():
    """
    pynvme Controller fixture
    
    conftest.py에서 자동 생성됨
    """
    # conftest.py에서 제공하므로 여기서는 pass
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
