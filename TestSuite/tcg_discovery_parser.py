"""
TCG Opal Discovery Feature Parser
==================================

Level 0 Discovery 응답을 파싱하여 구조체로 변환하고 
사람이 읽을 수 있는 형식으로 출력합니다.

TCG Core Spec 참조:
- Section 3.3.6: Level 0 Discovery
- Section 3.3.6.4: TPer Feature (Table 42)
- Section 3.3.6.5: Locking Feature (Table 43)
"""

import struct
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import IntEnum


# ==========================================
# Feature Codes (Spec Table 40)
# ==========================================

class FeatureCode(IntEnum):
    """Feature Code 정의 (Spec 3.3.6.3)"""
    TPER = 0x0001                    # TPer Feature
    LOCKING = 0x0002                 # Locking Feature
    GEOMETRY_REPORTING = 0x0003      # Geometry Reporting
    
    # SSC Features
    OPAL_SSC_V1 = 0x0200            # Opal SSC V1.0
    OPAL_SSC_V2 = 0x0201            # Opal SSC V2.0
    OPALITE = 0x0203                 # Opalite SSC


# ==========================================
# Data Structures
# ==========================================

@dataclass
class DiscoveryHeader:
    """
    Level 0 Discovery Header (48 bytes)
    
    TCG Spec 참조: Section 3.3.6.2, Table 39
    """
    length: int                      # Total length of parameter data
    major_version: int               # Data structure major version
    minor_version: int               # Data structure minor version
    reserved: bytes                  # Reserved bytes (8-15)
    vendor_unique: bytes             # Vendor specific data (16-47)
    
    def __str__(self) -> str:
        return f"""Discovery Header:
  Length:          {self.length} bytes
  Version:         {self.major_version}.{self.minor_version}
  Reserved:        {self.reserved.hex()}
  Vendor Unique:   {self.vendor_unique.hex()}"""


@dataclass
class TPerFeature:
    """
    TPer Feature Descriptor
    
    TCG Spec 참조: Section 3.3.6.4, Table 42
    
    이 feature는 TPer의 통신 프로토콜 지원 정보를 제공합니다.
    """
    version: int
    length: int
    raw_data: bytes
    
    # Byte 4 flags
    sync_supported: bool             # Spec 3.3.6.4.1: Synchronous protocol
    async_supported: bool            # Spec 3.3.6.4.2: Asynchronous protocol
    ack_nak_supported: bool          # Spec 3.3.6.4.3: ACK/NAK flow control
    buffer_mgmt_supported: bool      # Spec 3.3.6.4.4: Buffer management
    streaming_supported: bool        # Spec 3.3.6.4.5: Data streaming
    comid_mgmt_supported: bool       # Spec 3.3.6.4.6: ComID management
    
    @classmethod
    def parse(cls, version: int, length: int, data: bytes) -> 'TPerFeature':
        """
        TPer Feature data 파싱
        
        Byte 4 bit layout (Spec Table 42):
        Bit 7-6: Reserved
        Bit 5:   ComID Mgmt Supported
        Bit 4:   Reserved
        Bit 3:   Streaming Supported
        Bit 2:   Buffer Mgmt Supported
        Bit 1:   ACK/NAK Supported
        Bit 0:   Async Supported
        
        다음 바이트(Byte 5):
        Bit 0:   Sync Supported
        """
        if len(data) < 1:
            raise ValueError("TPer feature data too short")
        
        byte4 = data[0]
        
        # Byte 4의 각 비트 추출
        async_supported = bool(byte4 & 0x01)
        ack_nak_supported = bool(byte4 & 0x02)
        buffer_mgmt_supported = bool(byte4 & 0x04)
        streaming_supported = bool(byte4 & 0x08)
        comid_mgmt_supported = bool(byte4 & 0x20)
        
        # Sync는 보통 다음 바이트 또는 항상 지원됨
        # 대부분의 구현에서 Sync는 기본 지원
        sync_supported = True
        
        return cls(
            version=version,
            length=length,
            sync_supported=sync_supported,
            async_supported=async_supported,
            ack_nak_supported=ack_nak_supported,
            buffer_mgmt_supported=buffer_mgmt_supported,
            streaming_supported=streaming_supported,
            comid_mgmt_supported=comid_mgmt_supported,
            raw_data=data
        )
    
    def __str__(self) -> str:
        return f"""TPer Feature:
  Version:              {self.version}
  Length:               {self.length} bytes
  
  Protocol Support:
    Sync Protocol:      {'✓ Supported' if self.sync_supported else '✗ Not supported'}
    Async Protocol:     {'✓ Supported' if self.async_supported else '✗ Not supported'}
  
  Flow Control:
    ACK/NAK:            {'✓ Supported' if self.ack_nak_supported else '✗ Not supported'}
    Buffer Management:  {'✓ Supported' if self.buffer_mgmt_supported else '✗ Not supported'}
  
  Advanced Features:
    Streaming:          {'✓ Supported' if self.streaming_supported else '✗ Not supported'}
    ComID Management:   {'✓ Supported' if self.comid_mgmt_supported else '✗ Not supported'}
  
  Raw Data:             {self.raw_data.hex()}"""


@dataclass
class LockingFeature:
    """
    Locking Feature Descriptor
    
    TCG Spec 참조: Section 3.3.6.5, Table 43
    
    이 feature는 암호화 및 잠금 기능의 상태를 제공합니다.
    """
    version: int
    length: int
    raw_data: bytes
    
    # Byte 4 flags
    locking_supported: bool          # Spec 3.3.6.5.1: Hardware support
    locking_enabled: bool            # Spec 3.3.6.5.2: Feature activated
    locked: bool                     # Spec 3.3.6.5.3: Currently locked
    media_encryption: bool           # Spec 3.3.6.5.4: Hardware encryption
    mbr_enabled: bool                # Spec 3.3.6.5.5: MBR shadow active
    mbr_done: bool                   # Spec 3.3.6.5.6: MBR shadow done
    
    @classmethod
    def parse(cls, version: int, length: int, data: bytes) -> 'LockingFeature':
        """
        Locking Feature data 파싱
        
        Byte 4 bit layout (Spec Table 43):
        Bit 7-6: Reserved
        Bit 5:   MBR Done
        Bit 4:   MBR Enabled
        Bit 3:   Media Encryption
        Bit 2:   Locked
        Bit 1:   Locking Enabled
        Bit 0:   Locking Supported
        """
        if len(data) < 1:
            raise ValueError("Locking feature data too short")
        
        byte4 = data[0]
        
        return cls(
            version=version,
            length=length,
            locking_supported=bool(byte4 & 0x01),
            locking_enabled=bool(byte4 & 0x02),
            locked=bool(byte4 & 0x04),
            media_encryption=bool(byte4 & 0x08),
            mbr_enabled=bool(byte4 & 0x10),
            mbr_done=bool(byte4 & 0x20),
            raw_data=data
        )
    
    def __str__(self) -> str:
        status_icon = "🔒" if self.locked else "🔓"
        encryption_icon = "🔐" if self.media_encryption else "❌"
        
        return f"""Locking Feature:
  Version:              {self.version}
  Length:               {self.length} bytes
  
  Hardware Capabilities:
    Locking Supported:  {'✓ Yes (hardware capable)' if self.locking_supported else '✗ No'}
    Media Encryption:   {encryption_icon} {'Yes (Self-Encrypting Drive)' if self.media_encryption else 'No'}
  
  Current Status:
    Locking Enabled:    {'✓ Active' if self.locking_enabled else '✗ Inactive'}
    Locked:             {status_icon} {'YES - Data is locked!' if self.locked else 'No - Data accessible'}
  
  MBR Shadow:
    MBR Enabled:        {'✓ Active' if self.mbr_enabled else '✗ Inactive'}
    MBR Done:           {'✓ Completed' if self.mbr_done else '✗ In progress' if self.mbr_enabled else 'N/A'}
  
  Raw Data:             {self.raw_data.hex()}"""
    
    def is_sed(self) -> bool:
        """Self-Encrypting Drive 여부 확인"""
        return self.media_encryption
    
    def is_accessible(self) -> bool:
        """데이터 접근 가능 여부 확인"""
        return not self.locked or not self.locking_enabled


@dataclass
class OpalSSCFeature:
    """
    Opal SSC Feature Descriptor
    
    Opal Security Subsystem Class 지원 정보
    """
    version: int
    length: int
    feature_code: int                # 0x0200, 0x0201, 0x0203 등
    raw_data: bytes
    
    base_comid: Optional[int] = None
    num_comids: Optional[int] = None
    range_crossing: Optional[bool] = None
    
    @classmethod
    def parse(cls, feature_code: int, version: int, length: int, data: bytes) -> 'OpalSSCFeature':
        """Opal SSC Feature data 파싱"""
        base_comid = None
        num_comids = None
        range_crossing = None
        
        if len(data) >= 2:
            base_comid = struct.unpack('>H', data[0:2])[0]
        if len(data) >= 4:
            num_comids = struct.unpack('>H', data[2:4])[0]
        if len(data) >= 5:
            range_crossing = bool(data[4] & 0x01)
        
        return cls(
            version=version,
            length=length,
            feature_code=feature_code,
            base_comid=base_comid,
            num_comids=num_comids,
            range_crossing=range_crossing,
            raw_data=data
        )
    
    def get_name(self) -> str:
        """Feature 이름 반환"""
        names = {
            0x0200: "Opal SSC V1",
            0x0201: "Opal SSC V2",
            0x0203: "Opalite"
        }
        return names.get(self.feature_code, f"Unknown SSC (0x{self.feature_code:04X})")
    
    def __str__(self) -> str:
        result = f"""{self.get_name()}:
  Version:              {self.version}
  Length:               {self.length} bytes"""
        
        if self.base_comid is not None:
            result += f"\n  Base ComID:           0x{self.base_comid:04X}"
        if self.num_comids is not None:
            result += f"\n  Number of ComIDs:     {self.num_comids}"
        if self.range_crossing is not None:
            result += f"\n  Range Crossing:       {'✓ Supported' if self.range_crossing else '✗ Not supported'}"
        
        result += f"\n  Raw Data:             {self.raw_data.hex()}"
        return result


@dataclass
class GenericFeature:
    """
    일반 Feature Descriptor (파싱되지 않은 feature용)
    """
    code: int
    version: int
    length: int
    data: bytes
    
    def get_name(self) -> str:
        """Feature 이름 반환"""
        names = {
            0x0003: "Geometry Reporting"
        }
        return names.get(self.code, f"Unknown Feature (0x{self.code:04X})")
    
    def __str__(self) -> str:
        return f"""{self.get_name()}:
  Code:                 0x{self.code:04X}
  Version:              {self.version}
  Length:               {self.length} bytes
  Data:                 {self.data.hex()}"""


# ==========================================
# Discovery Parser
# ==========================================

@dataclass
class DiscoveryResult:
    """
    Level 0 Discovery 전체 결과
    """
    header: DiscoveryHeader
    tper_feature: Optional[TPerFeature] = None
    locking_feature: Optional[LockingFeature] = None
    opal_features: List[OpalSSCFeature] = field(default_factory=list)
    other_features: List[GenericFeature] = field(default_factory=list)
    
    def __str__(self) -> str:
        lines = [
            "=" * 70,
            "TCG OPAL LEVEL 0 DISCOVERY RESULT",
            "=" * 70,
            "",
            str(self.header),
            "",
            "=" * 70,
            "FEATURES",
            "=" * 70
        ]
        
        if self.tper_feature:
            lines.extend(["", str(self.tper_feature)])
        
        if self.locking_feature:
            lines.extend(["", str(self.locking_feature)])
        
        for opal in self.opal_features:
            lines.extend(["", str(opal)])
        
        for other in self.other_features:
            lines.extend(["", str(other)])
        
        lines.extend([
            "",
            "=" * 70,
            "SUMMARY",
            "=" * 70
        ])
        
        # Summary 생성
        if self.locking_feature:
            if self.locking_feature.is_sed():
                lines.append("✓ This is a Self-Encrypting Drive (SED)")
            else:
                lines.append("✗ This is NOT a Self-Encrypting Drive")
            
            if self.locking_feature.locking_enabled:
                lines.append("✓ Locking feature is ENABLED")
                if self.locking_feature.locked:
                    lines.append("⚠ WARNING: Data is currently LOCKED")
                else:
                    lines.append("✓ Data is currently UNLOCKED")
            else:
                lines.append("✗ Locking feature is DISABLED")
        
        if self.opal_features:
            opal_names = [f.get_name() for f in self.opal_features]
            lines.append(f"✓ Supported SSCs: {', '.join(opal_names)}")
        else:
            lines.append("✗ No Opal SSC support detected")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)


class DiscoveryParser:
    """
    Level 0 Discovery Response Parser
    
    TCG Spec 참조: Section 3.3.6
    """
    
    @staticmethod
    def parse(data: bytes) -> DiscoveryResult:
        """
        Level 0 Discovery 응답 파싱
        
        Args:
            data: Discovery response raw bytes
            
        Returns:
            DiscoveryResult 구조체
            
        Raises:
            ValueError: 데이터가 너무 짧거나 형식이 잘못된 경우
        """
        if len(data) < 48:
            raise ValueError(f"Discovery data too short: {len(data)} bytes (minimum 48)")
        
        # Parse Header (Spec 3.3.6.2, Table 39)
        header = DiscoveryParser._parse_header(data[0:48])
        
        # Parse Features (Spec 3.3.6.3)
        result = DiscoveryResult(header=header)
        pos = 48
        
        while pos + 4 <= len(data):
            # Feature Descriptor format (Spec Table 41):
            # Byte 0-1: Feature Code (big-endian)
            # Byte 2:   Version
            # Byte 3:   Length
            # Byte 4-n: Feature Dependent Data
            
            feature_code = struct.unpack('>H', data[pos:pos+2])[0]
            version = data[pos+2]
            length = data[pos+3]
            
            # Feature data 추출
            feature_data_start = pos + 4
            feature_data_end = feature_data_start + length
            
            if feature_data_end > len(data):
                break
            
            feature_data = data[feature_data_start:feature_data_end]
            
            # Feature 종류별 파싱
            if feature_code == FeatureCode.TPER:
                result.tper_feature = TPerFeature.parse(version, length, feature_data)
            
            elif feature_code == FeatureCode.LOCKING:
                result.locking_feature = LockingFeature.parse(version, length, feature_data)
            
            elif feature_code in [FeatureCode.OPAL_SSC_V1, FeatureCode.OPAL_SSC_V2, FeatureCode.OPALITE]:
                opal = OpalSSCFeature.parse(feature_code, version, length, feature_data)
                result.opal_features.append(opal)
            
            else:
                # 기타 feature
                generic = GenericFeature(
                    code=feature_code,
                    version=version,
                    length=length,
                    data=feature_data
                )
                result.other_features.append(generic)
            
            # 다음 feature로 이동
            pos = feature_data_end
            
            # 4-byte boundary alignment (Spec 3.3.6.3.1.3)
            if length % 4 != 0:
                pos += 4 - (length % 4)
        
        return result
    
    @staticmethod
    def _parse_header(header_data: bytes) -> DiscoveryHeader:
        """Discovery Header 파싱 (Spec Table 39)"""
        return DiscoveryHeader(
            length=struct.unpack('>I', header_data[0:4])[0],
            major_version=struct.unpack('>H', header_data[4:6])[0],
            minor_version=struct.unpack('>H', header_data[6:8])[0],
            reserved=header_data[8:16],
            vendor_unique=header_data[16:48]
        )


# ==========================================
# Helper Functions
# ==========================================

def parse_discovery(data: bytes) -> Dict:
    """
    기존 parse_discovery 함수와의 호환성을 위한 wrapper
    
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
    
    while pos + 4 <= len(data):
        feature_code = struct.unpack('>H', data[pos:pos+2])[0]
        version = data[pos+2]
        length = data[pos+3]
        
        feature_data_end = pos + 4 + length
        if feature_data_end > len(data):
            break
        
        feature_data = data[pos+4:feature_data_end]
        
        features.append({
            'code': feature_code,
            'version': version,
            'length': length,
            'data': feature_data
        })
        
        pos = feature_data_end
        
        # Padding to 4-byte boundary
        if length % 4 != 0:
            pos += 4 - (length % 4)
    
    return {
        'header': header,
        'features': features
    }


# ==========================================
# Example Usage
# ==========================================

if __name__ == "__main__":
    # 예제: Discovery 데이터 파싱 및 출력
    
    # 샘플 데이터 (실제 SSD에서 받은 데이터로 교체 필요)
    sample_discovery = bytes([
        # Header (48 bytes)
        0x00, 0x00, 0x00, 0x70,  # Length: 112 bytes
        0x00, 0x00,              # Major version: 0
        0x00, 0x01,              # Minor version: 1
        # Reserved (8 bytes)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        # Vendor Unique (32 bytes)
        *([0x00] * 32),
        
        # TPer Feature (0x0001)
        0x00, 0x01,              # Feature code: TPer
        0x01,                    # Version: 1
        0x0C,                    # Length: 12 bytes
        0x03,                    # Byte 4: Sync(1) + Async(1)
        *([0x00] * 11),          # Reserved
        
        # Locking Feature (0x0002)
        0x00, 0x02,              # Feature code: Locking
        0x01,                    # Version: 1
        0x0C,                    # Length: 12 bytes
        0x0F,                    # Byte 4: All flags set
        *([0x00] * 11),          # Reserved
        
        # Opal SSC V2 (0x0201)
        0x02, 0x01,              # Feature code: Opal V2
        0x01,                    # Version: 1
        0x10,                    # Length: 16 bytes
        0x00, 0x01,              # Base ComID: 0x0001
        0x00, 0x01,              # Num ComIDs: 1
        0x01,                    # Range crossing: supported
        *([0x00] * 11),          # Reserved
    ])
    
    try:
        # 파싱
        result = DiscoveryParser.parse(sample_discovery)
        
        # 전체 출력
        print(result)
        
        print("\n" + "=" * 70)
        print("QUICK CHECKS")
        print("=" * 70)
        
        # Quick checks
        if result.locking_feature:
            print(f"Is SED? {result.locking_feature.is_sed()}")
            print(f"Is Accessible? {result.locking_feature.is_accessible()}")
        
    except Exception as e:
        print(f"Error parsing discovery: {e}")
        import traceback
        traceback.print_exc()
