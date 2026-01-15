"""
TCG Opal SSC v2.30 종합 테스트 스위트
====================================

pynvme 기반 실제 SSD 테스트
정확한 API 사용: security_send(buf, spsp, secp, nssf, size, cb)
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

# ComID (used as spsp for TCG)
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
    # Setup/Teardown
    # ------------------------------------------
    
    def setup_method(self, method):
        """각 테스트 전 초기화"""
        self.admin_session_id = None
        self.locking_session_id = None
    
    def teardown_method(self, method):
        """각 테스트 후 정리"""
        pass
    
    # ------------------------------------------
    # Level 0 Discovery
    # ------------------------------------------
    
    def test_level0_discovery(self, ssd_h):
        """
        3.1.1 Level 0 Discovery
        
        TPer의 기능을 발견
        """
        # Discovery 요청 (빈 payload)
        send_buf = ssd_h.buffer(512)
        send_buf[:] = bytes(512)  # All zeros
        
        # pynvme API: security_send(buf, spsp, secp, nssf, size, cb)
        # spsp = ComID (TCG uses spsp as ComID)
        # secp = Security Protocol
        ssd_h.security_send(
            send_buf,                   # buf
            COMID_DISCOVERY,            # spsp (ComID)
            SECURITY_PROTOCOL_TCG,      # secp
            0,                          # nssf
            512,                        # size
            None                        # cb
        )
        ssd_h.waitdone()  # 비동기 명령이므로 대기 필수
        
        # Security Receive
        recv_buf = ssd_h.buffer(2048)
        ssd_h.security_receive(
            recv_buf,                   # buf
            COMID_DISCOVERY,            # spsp
            SECURITY_PROTOCOL_TCG,      # secp
            0,                          # nssf
            2048,                       # size
            None                        # cb
        )
        ssd_h.waitdone()
        
        # Buffer → bytes 변환
        response_data = bytes(recv_buf)
        
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
        send_buf = ssd_h.buffer(len(payload))
        send_buf[:] = payload
        
        ssd_h.security_send(
            send_buf,
            0x0001,                     # spsp (ComID)
            SECURITY_PROTOCOL_TCG,
            0,
            len(payload),
            None
        )
        ssd_h.waitdone()
        
        # Receive
        recv_buf = ssd_h.buffer(2048)
        ssd_h.security_receive(
            recv_buf,
            0x0001,
            SECURITY_PROTOCOL_TCG,
            0,
            2048,
            None
        )
        ssd_h.waitdone()
        
        response_data = bytes(recv_buf)
        
        # 응답 파싱
        # ComPacket(20) + Packet(20) + SubPacket(12) = 52 bytes 헤더
        # 하지만 실제로는 다를 수 있으므로 Length 필드를 파싱해야 함
        
        # ComPacket Length 추출 (offset 16-20, big-endian)
        com_length = struct.unpack('>I', response_data[16:20])[0]
        
        # Packet Length 추출 (offset 36-40, big-endian) 
        packet_length = struct.unpack('>I', response_data[36:40])[0]
        
        # SubPacket Length 추출 (offset 48-52, big-endian)
        subpacket_length = struct.unpack('>I', response_data[48:52])[0]
        
        # Payload는 SubPacket 헤더(52 bytes) 이후
        payload_data = response_data[52:]
        
        parsed = TCGResponseParser.parse_session_response(payload_data)
        
        assert parsed['status'] == STATUS_SUCCESS, \
            f"StartSession failed with status: {parsed['status']}"
        
        assert parsed['session_id'] is not None
        assert parsed['tper_session_id'] is not None
        
        print(f"\n✓ Session Started:")
        print(f"  Host Session ID:  {parsed['session_id']}")
        print(f"  TPer Session ID:  {parsed['tper_session_id']}")
        print(f"  Status:           {parsed['status']} (Success)")
        
        # Session ID 저장 (같은 테스트 내에서만 유효)
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
        send_buf = ssd_h.buffer(len(payload))
        send_buf[:] = payload
        
        ssd_h.security_send(
            send_buf,
            0x0001,
            SECURITY_PROTOCOL_TCG,
            0,
            len(payload),
            None
        )
        ssd_h.waitdone()
        
        # Receive
        recv_buf = ssd_h.buffer(2048)
        ssd_h.security_receive(
            recv_buf,
            0x0001,
            SECURITY_PROTOCOL_TCG,
            0,
            2048,
            None
        )
        ssd_h.waitdone()
        
        response_data = bytes(recv_buf)
        
        # 파싱 (52 bytes 헤더 스킵)
        payload_data = response_data[52:]
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
        
        send_buf = ssd_h.buffer(len(session_payload))
        send_buf[:] = session_payload
        
        ssd_h.security_send(send_buf, 0x0001, SECURITY_PROTOCOL_TCG, 0, len(session_payload), None)
        ssd_h.waitdone()
        
        recv_buf = ssd_h.buffer(2048)
        ssd_h.security_receive(recv_buf, 0x0001, SECURITY_PROTOCOL_TCG, 0, 2048, None)
        ssd_h.waitdone()
        
        response = bytes(recv_buf)
        parsed_session = TCGResponseParser.parse_session_response(response[52:])
        session_id = parsed_session['tper_session_id']
        
        # Properties Method 호출
        builder = TCGPayloadBuilder()
        
        builder.add_call()
        builder.add_uid(UID.SM_UID)  # Session Manager
        builder.add_uid(UID.PROPERTIES)  # Properties Method
        
        # Parameters: [ HostProperties ]
        builder.start_list()
        
        # Request: MaxComPacketSize
        builder.start_name()
        builder.add_bytes(b"MaxComPacketSize")
        builder.add_integer(0)  # Request current value
        builder.end_name()
        
        builder.end_list()
        builder.add_end_of_data()
        
        properties_payload = builder.get_payload()
        properties_packet = TCGComPacketBuilder.build(0x0001, properties_payload)
        
        # Send
        send_buf2 = ssd_h.buffer(len(properties_packet))
        send_buf2[:] = properties_packet
        
        ssd_h.security_send(send_buf2, 0x0001, SECURITY_PROTOCOL_TCG, 0, len(properties_packet), None)
        ssd_h.waitdone()
        
        # Receive
        recv_buf2 = ssd_h.buffer(2048)
        ssd_h.security_receive(recv_buf2, 0x0001, SECURITY_PROTOCOL_TCG, 0, 2048, None)
        ssd_h.waitdone()
        
        response2 = bytes(recv_buf2)
        
        # Parse
        payload_data = response2[52:]
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
        
        send_buf = ssd_h.buffer(len(session_payload))
        send_buf[:] = session_payload
        
        ssd_h.security_send(send_buf, 0x0001, SECURITY_PROTOCOL_TCG, 0, len(session_payload), None)
        ssd_h.waitdone()
        
        recv_buf = ssd_h.buffer(2048)
        ssd_h.security_receive(recv_buf, 0x0001, SECURITY_PROTOCOL_TCG, 0, 2048, None)
        ssd_h.waitdone()
        
        response = bytes(recv_buf)
        parsed_session = TCGResponseParser.parse_session_response(response[52:])
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
        send_buf2 = ssd_h.buffer(len(get_packet))
        send_buf2[:] = get_packet
        
        ssd_h.security_send(send_buf2, 0x0001, SECURITY_PROTOCOL_TCG, 0, len(get_packet), None)
        ssd_h.waitdone()
        
        # Receive
        recv_buf2 = ssd_h.buffer(2048)
        ssd_h.security_receive(recv_buf2, 0x0001, SECURITY_PROTOCOL_TCG, 0, 2048, None)
        ssd_h.waitdone()
        
        response2 = bytes(recv_buf2)
        
        # Parse
        payload_data = response2[52:]
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
        pytest.skip("Requires SID authentication - manual test only")
    
    def test_revert_tper(self, ssd_h):
        """
        4.3.3.2 RevertSP Method
        
        TPer 전체 초기화 (위험! 모든 데이터 삭제)
        """
        pytest.skip("Destructive test - manual execution only")
    
    # ------------------------------------------
    # Security Tests
    # ------------------------------------------
    
    def test_authenticate_method(self, ssd_h):
        """
        3.3.8.2.3 Authenticate Method
        
        세션 내에서 추가 인증
        """
        pytest.skip("Requires active session - integration test")
    
    def test_genkey_method(self, ssd_h):
        """
        5.4.3.2 GenKey Method
        
        암호화 키 생성
        """
        pytest.skip("Requires Locking SP activation")
    
    # ------------------------------------------
    # Locking Tests
    # ------------------------------------------
    
    def test_set_read_lock(self, ssd_h):
        """
        5.3.2.1 Locking 설정
        
        특정 범위를 읽기 잠금
        """
        pytest.skip("Requires Locking SP and Range configuration")
    
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
    
    # ------------------------------------------
    # Utility Tests
    # ------------------------------------------
    
    def test_random_method(self, ssd_h):
        """
        5.4.3.4 Random Method
        
        난수 생성 (테스트용)
        """
        pytest.skip("Random method UID varies by implementation")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
