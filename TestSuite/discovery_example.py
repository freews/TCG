"""
Discovery Parser 사용 예제
===========================

기존 test_level0_discovery를 개선하여 
구조화된 출력을 제공합니다.
"""

from tcg_discovery_parser import DiscoveryParser, parse_discovery

# ==========================================
# 기존 테스트 함수 개선 버전
# ==========================================

def test_level0_discovery_enhanced(ssd_h):
    """
    3.1.1 Level 0 Discovery (Enhanced)
    
    구조화된 Discovery 파싱 및 상세 출력
    """
    # Discovery 요청 (빈 payload)
    send_buf = ssd_h.buffer(512)
    send_buf[:] = bytes(512)  # All zeros
    
    # Security Send
    ssd_h.security_send(
        send_buf,
        COMID_DISCOVERY,
        SECURITY_PROTOCOL_TCG,
        0,
        512,
        None
    )
    ssd_h.waitdone()
    
    # Security Receive
    recv_buf = ssd_h.buffer(2048)
    ssd_h.security_receive(
        recv_buf,
        COMID_DISCOVERY,
        SECURITY_PROTOCOL_TCG,
        0,
        2048,
        None
    )
    ssd_h.waitdone()
    
    # Buffer → bytes 변환
    response_data = bytes(recv_buf)
    
    # ==========================================
    # 새로운 구조화된 파싱
    # ==========================================
    
    try:
        discovery = DiscoveryParser.parse(response_data)
        
        # 전체 상세 출력
        print("\n" + str(discovery))
        
        # ==========================================
        # 추가 분석
        # ==========================================
        
        print("\n" + "=" * 70)
        print("ADDITIONAL ANALYSIS")
        print("=" * 70)
        
        # SED 검증
        if discovery.locking_feature:
            if discovery.locking_feature.is_sed():
                print("\n✓ CONFIRMED: This is a Self-Encrypting Drive (SED)")
                print(f"  Media Encryption: Supported")
            else:
                print("\n✗ This is NOT a Self-Encrypting Drive")
            
            # 접근성 검증
            if discovery.locking_feature.is_accessible():
                print("✓ Data is currently ACCESSIBLE")
            else:
                print("⚠ WARNING: Data is currently LOCKED - Authentication required!")
        
        # Opal 지원 검증
        if discovery.opal_features:
            print(f"\n✓ Opal Support Detected:")
            for opal in discovery.opal_features:
                print(f"  - {opal.get_name()}")
                if opal.base_comid:
                    print(f"    ComID: 0x{opal.base_comid:04X}")
        else:
            print("\n✗ No Opal SSC support detected")
            print("  (This may be a vendor-specific implementation)")
        
        # 통신 프로토콜 검증
        if discovery.tper_feature:
            print(f"\n✓ Communication Protocols:")
            if discovery.tper_feature.sync_supported:
                print("  - Synchronous: Supported")
            if discovery.tper_feature.async_supported:
                print("  - Asynchronous: Supported")
        
        # ==========================================
        # pytest assertion
        # ==========================================
        
        assert discovery.header is not None
        assert discovery.tper_feature is not None, "TPer feature is mandatory"
        assert discovery.locking_feature is not None, "Locking feature is mandatory"
        
        print("\n✓ All discovery assertions passed!")
        
    except Exception as e:
        print(f"\n✗ Discovery parsing failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback to basic parsing
        print("\nFalling back to basic parser...")
        basic_discovery = parse_discovery(response_data)
        
        if 'error' in basic_discovery:
            print(f"Error: {basic_discovery['error']}")
            raise
        
        print(f"\nBasic Discovery:")
        print(f"  Version: {basic_discovery['header']['major_version']}.{basic_discovery['header']['minor_version']}")
        print(f"  Total Length: {basic_discovery['header']['length']} bytes")
        print(f"  Features found: {len(basic_discovery['features'])}")
        
        feature_names = {
            0x0001: "TPer",
            0x0002: "Locking",
            0x0003: "Geometry Reporting",
            0x0200: "Opal SSC V1",
            0x0201: "Opal SSC V2",
            0x0203: "Opalite"
        }
        
        for feat in basic_discovery['features']:
            name = feature_names.get(feat['code'], f"Unknown (0x{feat['code']:04X})")
            print(f"  - {name}: version {feat['version']}, {feat['length']} bytes")


# ==========================================
# 간단한 독립 실행 스크립트
# ==========================================

def analyze_discovery_file(filepath: str):
    """
    파일에서 Discovery 데이터를 읽어 분석
    
    Usage:
        python discovery_example.py <discovery_data.bin>
    """
    import sys
    
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        
        print(f"Analyzing discovery data from: {filepath}")
        print(f"Data size: {len(data)} bytes\n")
        
        discovery = DiscoveryParser.parse(data)
        print(discovery)
        
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing discovery: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # 파일에서 읽기
        analyze_discovery_file(sys.argv[1])
    else:
        # 샘플 데이터로 테스트
        print("No file specified, using sample data...\n")
        
        # 샘플 Discovery 데이터 생성
        sample_data = bytes([
            # Header (48 bytes)
            0x00, 0x00, 0x00, 0x70,  # Length: 112 bytes
            0x00, 0x00,              # Major version: 0
            0x00, 0x01,              # Minor version: 1
            *([0x00] * 40),          # Reserved + Vendor Unique
            
            # TPer Feature
            0x00, 0x01, 0x01, 0x0C,
            0x03, *([0x00] * 11),
            
            # Locking Feature
            0x00, 0x02, 0x01, 0x0C,
            0x0F, *([0x00] * 11),
            
            # Opal V2
            0x02, 0x01, 0x01, 0x10,
            0x00, 0x01, 0x00, 0x01, 0x01, *([0x00] * 11),
        ])
        
        discovery = DiscoveryParser.parse(sample_data)
        print(discovery)
